import { PlaybackEvents } from './PlaybackEvents.js';
import { PlaybackState } from './PlaybackState.js';
import * as WindowsMediaControl from '@nodert-win11/windows.media.control';

/**
 * OSMediaDetector handles playback detection from OS media controls
 * Uses Windows Media Control API for Windows 11/10 media session tracking
 */
export class OSMediaDetector {
    private sessionManager: any = null;
    public playbackEvents = new PlaybackEvents();
    public stopPolling: (() => void) | null = null;
    private lastSessionId: string | null = null;
    private lastState: PlaybackState | null = null;
    private initialized: boolean = false;
    private pollInterval: NodeJS.Timeout | null = null;

    /**
     * Initialize the OS media controls detector
     */
    public async initialize(): Promise<boolean> {
        try {
            // Get the global media control session manager
            this.sessionManager = await WindowsMediaControl.GlobalSystemMediaTransportControlsSessionManager.requestAsync();

            if (!this.sessionManager) {
                console.error('Failed to get Windows Media Control session manager');
                return false;
            }

            console.log('Windows Media Control initialized successfully');

            // Start polling for media session changes
            this.startMonitoring();
            this.initialized = true;
            return true;
        } catch (err) {
            console.error('Failed to initialize OS media detector:', err);
            return false;
        }
    }

    /**
     * Start monitoring media session for playback changes
     */
    private startMonitoring(): void {
        if (!this.sessionManager) return;

        const pollIntervalMs = 1000; // 1 second
        let shouldStop = false;

        const pollLoop = async () => {
            while (!shouldStop) {
                try {
                    if (!this.sessionManager) return;

                    // Get all active media sessions
                    const sessions = this.sessionManager.getSessions();
                    
                    if (!sessions || sessions.length === 0) {
                        // No active sessions
                        if (this.lastState) {
                            this.lastState = null;
                            this.lastSessionId = null;
                        }
                        await new Promise(r => setTimeout(r, pollIntervalMs));
                        continue;
                    }

                    // Get the first active/current session
                    const session = sessions[0];
                    const sessionId = session.sourceAppUserModelId || session.nativeDisplayName || 'unknown';
                    const playbackState = await this.convertSessionToPlaybackState(session);

                    if (!playbackState) {
                        await new Promise(r => setTimeout(r, pollIntervalMs));
                        continue;
                    }

                    if (!this.lastState) {
                        // First detection
                        this.playbackEvents.emit('playbackResumed', playbackState);
                    } else {
                        // Check for changes
                        if (playbackState.trackId !== this.lastState.trackId) {
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
                    this.lastSessionId = sessionId;

                    await new Promise(r => setTimeout(r, pollIntervalMs));
                } catch (err) {
                    console.error('Error monitoring media session:', err);
                    await new Promise(r => setTimeout(r, pollIntervalMs));
                }
            }
        };

        // Start polling loop in background
        pollLoop().catch(err => console.error('Poll loop error:', err));

        // Store stop function
        this.stopPolling = () => {
            shouldStop = true;
        };
    }

    /**
     * Convert Windows Media Control session to PlaybackState
     */
    private async convertSessionToPlaybackState(session: any): Promise<PlaybackState | null> {
        try {
            // Get metadata information
            const mediaProperties = session.tryGetMediaPropertiesAsync();
            if (!mediaProperties) return null;

            const trackName = mediaProperties.title || 'Unknown Track';
            const artist = mediaProperties.artist || 'Unknown Artist';
            const duration = mediaProperties.subtitle ? parseInt(mediaProperties.subtitle) : 0;

            // Get playback info
            const playbackInfo = session.getPlaybackInfo();
            const isPlaying = playbackInfo?.playbackStatus === 4; // 4 = Playing in Windows Media Control
            const progress = playbackInfo?.controls?.position || 0;

            // Create a unique track ID from artist + title
            const trackId = `${artist}|${trackName}`.toLowerCase().replace(/\s+/g, '_');

            // Try to get album art thumbnail
            const thumbnail = mediaProperties.thumbnail || null;

            return new PlaybackState({
                trackId: trackId,
                trackName: trackName,
                artist: artist,
                progressMs: progress,
                durationMs: duration,
                isPlaying: isPlaying,
                imgUrl: thumbnail
            });
        } catch (err) {
            console.error('Error converting session to playback state:', err);
            return null;
        }
    }

    /**
     * Stop detecting media sessions
     */
    public stop(): void {
        if (this.stopPolling) {
            this.stopPolling();
            this.stopPolling = null;
        }
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
        }
        this.sessionManager = null;
        this.lastState = null;
        this.lastSessionId = null;
    }

    /**
     * Check if detector is initialized
     */ 
    public isInitialized(): boolean {
        return this.initialized;
    }
}
