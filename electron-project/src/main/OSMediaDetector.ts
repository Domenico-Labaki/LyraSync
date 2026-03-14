import { execFile } from 'child_process';
import { PlaybackEvents } from './PlaybackEvents.js';
import { PlaybackState } from './PlaybackState.js';

interface RawMediaInfo {
    title: string;
    artist: string;
    isPlaying: boolean;
    progressMs: number;
    durationMs: number;
    thumbnailBase64: string | null;  // <-- add this
    contentType: string;
}

export class OSMediaDetector {
    public playbackEvents = new PlaybackEvents();
    public stopPolling: (() => void) | null = null;
    private lastState: PlaybackState | null = null;
    private initialized: boolean = false;
    private thumbnail: string | null = null;

    private static readonly PS_SCRIPT = `
        Add-Type -AssemblyName System.Runtime.WindowsRuntime

        function Await([object]$WinRtTask, [type]$ResultType) {
            $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
                $_.Name -eq 'AsTask' -and
                $_.GetParameters().Count -eq 1 -and
                $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation\`1'
            })[0]
            $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
            $task = $asTask.Invoke($null, @($WinRtTask))
            $task.Wait() | Out-Null
            $task.Result
        }

        try {
            $mgrType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime]
            $mgr = Await $mgrType::RequestAsync() $mgrType
            $propsType = [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties]

            $playing = $mgr.GetSessions() | ForEach-Object {
                $info = $_.GetPlaybackInfo()
                if ($info.PlaybackStatus -eq 4) {
                    $props = Await $_.TryGetMediaPropertiesAsync() $propsType
                    $tl = $_.GetTimelineProperties()
                    $progress = [long]$tl.Position.TotalMilliseconds
                    $duration = [long]$tl.EndTime.TotalMilliseconds
                    "$($props.Title)|$($props.Artist)|1|$progress|$duration"
                }
            } | Select-Object -First 1

            if (-not $playing) {
                $session = $mgr.GetSessions() | Select-Object -First 1
                if ($session) {
                    $props = Await $session.TryGetMediaPropertiesAsync() $propsType
                    $tl = $session.GetTimelineProperties()
                    $progress = [long]$tl.Position.TotalMilliseconds
                    $duration = [long]$tl.EndTime.TotalMilliseconds
                    Write-Output "$($props.Title)|$($props.Artist)|0|$progress|$duration"
                }
            } else {
                Write-Output $playing
            }
        } catch {
            exit 0
        }
    `;

    private getRawMediaInfo(): Promise<RawMediaInfo | null> {
        return new Promise((resolve) => {
            execFile('powershell', ['-NoProfile', '-Command', OSMediaDetector.PS_SCRIPT], (err, stdout) => {
                if (err || !stdout.trim()) {
                    console.log('PowerShell error or empty output:', err?.message);
                    return resolve(null);
                }

                const parts = stdout.trim().split('|');
                console.log('PowerShell output parts count:', parts.length, 'Raw output:', stdout.trim().substring(0, 100));
                
                const [title, artist, playing, progress, duration, thumb, contentType] = parts;
                if (!title && !artist) return resolve(null);

                console.log('Parsed media info:', {
                    title,
                    artist,
                    hasThumbnail: !!thumb,
                    thumbnailLength: thumb?.length || 0,
                    contentType: contentType || 'image/png'
                });

                resolve({
                    title:           title  || 'Unknown Track',
                    artist:          artist || 'Unknown Artist',
                    isPlaying:       playing === '1',
                    progressMs:      parseInt(progress) || 0,
                    durationMs:      parseInt(duration) || 0,
                    thumbnailBase64: thumb || null,
                    contentType:     contentType || 'image/png',
                });
            });
        });
    }

    private async getAlbumArt(artist: string, title: string): Promise<string | null> {
        try {
            // Search Spotify public API (no auth needed for search)
            const query = encodeURIComponent(`${artist} ${title}`);
            const res = await fetch(`https://itunes.apple.com/search?term=${query}&media=music&limit=1`);
            const data = await res.json();
            
            if (data.results?.length > 0) {
                // iTunes returns 100x100, replace with 600x600
                return data.results[0].artworkUrl100.replace('100x100', '600x600');
            }
            return null;
        } catch {
            return null;
        }
    }

    public async initialize(): Promise<boolean> {
        try {
            // Verify PowerShell can reach the media session API before starting
            const test = await this.getRawMediaInfo();
            console.log(test !== null
                ? 'Windows Media Control (PowerShell) initialized successfully'
                : 'Windows Media Control initialized — no active session yet'
            );
            this.startMonitoring();
            this.initialized = true;
            return true;
        } catch (err) {
            console.error('Failed to initialize OS media detector:', err);
            return false;
        }
    }

    private startMonitoring(): void {
        const pollIntervalMs = 200;
        let shouldStop = false;

        const pollLoop = async () => {
            while (!shouldStop) {
                try {
                    const raw = await this.getRawMediaInfo();

                    if (!raw) {
                        if (this.lastState) {
                            this.lastState = null;
                        }
                        await new Promise(r => setTimeout(r, pollIntervalMs));
                        continue;
                    }

                    const trackId = `${raw.artist}|${raw.title}`.toLowerCase().replace(/\s+/g, '_');

                    const playbackState = new PlaybackState({
                        trackId: `${raw.artist}::${raw.title}`.toLowerCase().trim().replace(/\s+/g, '_'),
                        trackName:  raw.title,
                        artist:     raw.artist,
                        progressMs: raw.progressMs,
                        durationMs: raw.durationMs,
                        isPlaying:  raw.isPlaying,
                        imgUrl: this.thumbnail ? this.thumbnail : null,
                    });

                    console.log(this.thumbnail);

                    if (!this.lastState) {
                        this.playbackEvents.emit('playbackResumed', playbackState);
                    } else {
                        if (playbackState.trackId !== this.lastState.trackId || this.thumbnail == null) {
                            this.thumbnail = await this.getAlbumArt(raw.artist, raw.title);
                            this.playbackEvents.emit('trackChanged', playbackState);
                        }
                        if (playbackState.isPlaying !== this.lastState.isPlaying) {
                            playbackState.isPlaying
                                ? this.playbackEvents.emit('playbackResumed', playbackState)
                                : this.playbackEvents.emit('playbackPaused', playbackState);
                        }
                        if (playbackState.progressMs !== this.lastState.progressMs) {
                            this.playbackEvents.emit('progressUpdated', playbackState);
                        }
                    }

                    this.lastState = playbackState;
                } catch (err) {
                    console.error('Error in media poll loop:', err);
                }

                await new Promise(r => setTimeout(r, pollIntervalMs));
            }
        };

        pollLoop().catch(err => console.error('Poll loop error:', err));
        this.stopPolling = () => { shouldStop = true; };
    }

    public stop(): void {
        if (this.stopPolling) {
            this.stopPolling();
            this.stopPolling = null;
        }
        this.lastState = null;
    }

    public isInitialized(): boolean {
        return this.initialized;
    }
}