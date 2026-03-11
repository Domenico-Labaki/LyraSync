import { PlaybackEvents } from './PlaybackEvents.js';
import { PlaybackState } from './PlaybackState.js';
import { MediaSession, MediaSessionManager } from 'node-global-media-controls';

/**
 * OSMediaDetector handles playback detection from OS media controls
 * Works across Windows, macOS, and Linux using dbus on Linux
 */
export class OSMediaDetector {
    private mediaSessionManager: MediaSessionManager | null = null;
    public playbackEvents = new PlaybackEvents();
    public stopPolling: (() => void) | null = null;
    private lastSession: MediaSession | null = null;
    private initialized: boolean = false;

    /**
     * Initialize the OS media controls detector
     */
    public async initialize(): Promise<boolean> {
        try {
            this.mediaSessionManager = new MediaSessionManager({
                serviceName: 'LyraSync'
            });

            // Start listening for media session updates
            this.mediaSessionManager.on('sessionOpened', (session) => {
                console.log('Media session opened:', session.name || 'Unknown');
            });

            this.mediaSessionManager.on('sessionClosed', (session) => {
                console.log('Media session closed:', session.name || 'Unknown');
                if (this.lastSession?.id === session.id) {
                    this.lastSession = null;
                }
            });

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
        if (!this.mediaSessionManager) return;

        const pollInterval = 1000; // 1 second
        let lastState: PlaybackState | null = null;
        let shouldStop = false;

        const pollLoop = async () => {
            while (!shouldStop) {
                try {
                    if (!this.mediaSessionManager) return;

                    // Get the active media session
                    const sessions = this.mediaSessionManager.getActiveSessions();
                    if (sessions.length === 0) {
                        // No active sessions
                        await new Promise(r => setTimeout(r, pollInterval));
                        continue;
                    }

                    // Use the first active session (usually the current/primary player)
                    const session = sessions[0];
                    const playbackState = this.convertSessionToPlaybackState(session);

                    if (!playbackState) {
                        await new Promise(r => setTimeout(r, pollInterval));
                        continue;
                    }

                    if (!lastState) {
                        // First detection
                        this.playbackEvents.emit('playbackResumed', playbackState);
                    } else {
                        // Check for changes
                        if (playbackState.trackId !== lastState.trackId) {
                            this.playbackEvents.emit('trackChanged', playbackState);
                        }

                        if (playbackState.isPlaying !== lastState.isPlaying) {
                            playbackState.isPlaying
                                ? this.playbackEvents.emit('playbackResumed', playbackState)
                                : this.playbackEvents.emit('playbackPaused', playbackState);
                        }

                        this.playbackEvents.emit('progressUpdated', playbackState);
                    }

                    lastState = playbackState;
                    this.lastSession = session;

                    await new Promise(r => setTimeout(r, pollInterval));
                } catch (err) {
                    console.error('Error monitoring media session:', err);
                    await new Promise(r => setTimeout(r, pollInterval));
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
     * Convert MediaSession to PlaybackState
     */
    private convertSessionToPlaybackState(session: MediaSession): PlaybackState | null {
        try {
            const metadata = session.metadata;
            if (!metadata) return null;

            const trackName = metadata.title || 'Unknown Track';
            const artist = metadata.artist || 'Unknown Artist';
            const duration = session.getMetadata()?.duration ?? 0;
            const progress = session.getMetadata()?.position ?? 0;

            // Create a unique track ID from artist + title
            const trackId = `${artist}|${trackName}`.toLowerCase().replace(/\s+/g, '_');

            return new PlaybackState({
                trackId: trackId,
                trackName: trackName,
                artist: artist,
                progressMs: progress,
                durationMs: duration,
                isPlaying: session.getPlaybackStatus() === 'playing',
                imgUrl: metadata.thumbnail || null
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
        if (this.mediaSessionManager) {
            this.mediaSessionManager.removeAllListeners();
        }
    }

    /**
     * Check if detector is initialized
     */ 
    public isInitialized(): boolean {
        return this.initialized;
    }
}
