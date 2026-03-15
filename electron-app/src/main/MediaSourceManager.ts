import { SpotifyAuth } from './SpotifyAuth.js';
import { OSMediaDetector } from './OSMediaDetector.js';
import { PlaybackEvents } from './PlaybackEvents.js';
import { BrowserWindow } from 'electron';

export type MediaSource = 'spotify' | 'guest';

/**
 * MediaSourceManager handles switching between different media sources
 * Currently supports: Spotify API and OS Media Controls
 */
export class MediaSourceManager {
    private currentSource: MediaSource | null = null;
    private spotifyAuth: SpotifyAuth | null = null;
    private osMediaDetector: OSMediaDetector | null = null;
    private mainWindow: BrowserWindow;
    private playbackEvents: PlaybackEvents;

    constructor(mainWindow: BrowserWindow) {
        this.mainWindow = mainWindow;
        this.playbackEvents = new PlaybackEvents(mainWindow);
    }

    /**
     * Initialize and start a specific media source
     */
    public async startSource(source: MediaSource): Promise<boolean> {
        // Stop current source if already running
        if (this.currentSource) {
            await this.stopSource();
        }

        try {
            if (source === 'spotify') {
                return await this.startSpotify();
            } else if (source === 'guest') {
                return await this.startGuestMode();
            }
            return false;
        } catch (err) {
            console.error(`Failed to start ${source} source:`, err);
            return false;
        }
    }

    /**
     * Start Spotify mode
     */
    private async startSpotify(): Promise<boolean> {
        try {
            this.spotifyAuth = new SpotifyAuth(this.mainWindow);
            this.spotifyAuth.start();

            // Connect Spotify's playback events to our main event emitter
            this.connectSpotifyEvents();
            
            // Try to automatically refresh existing session
            const success = await this.spotifyAuth.refreshLogin();
            
            if (success) {
                this.currentSource = 'spotify';
                return true;
            }
            // No existing session
            return false;
        } catch (err) {
            console.error('Failed to initialize Spotify source:', err);
            return false;
        }
    }

    /**
     * Connect Spotify's playback events to the main manager's event emitter
     */
    private connectSpotifyEvents(): void {
        if (!this.spotifyAuth) return;

        const spotifyEvents = this.spotifyAuth.playbackEvents;

        // Forward all events from Spotify to main playback events
        spotifyEvents.on('trackChanged', (state) => {
            this.playbackEvents.emit('trackChanged', state);
        });

        spotifyEvents.on('playbackResumed', (state) => {
            this.playbackEvents.emit('playbackResumed', state);
        });

        spotifyEvents.on('playbackPaused', (state) => {
            this.playbackEvents.emit('playbackPaused', state);
        });

        spotifyEvents.on('progressUpdated', (state) => {
            this.playbackEvents.emit('progressUpdated', state);
        });
    }

    /**
     * Start Guest mode (OS media controls)
     */
    private async startGuestMode(): Promise<boolean> {
        try {
            this.osMediaDetector = new OSMediaDetector();
            const initialized = await this.osMediaDetector.initialize();

            if (initialized) {
                this.currentSource = 'guest';
                // Connect OS media detector's events to main playback events
                this.connectGuestModeEvents();
                return true;
            }

            return false;
        } catch (err) {
            console.error('Failed to initialize guest mode:', err);
            return false;
        }
    }

    /**
     * Connect Guest mode's playback events to the main manager's event emitter
     */
    private connectGuestModeEvents(): void {
        if (!this.osMediaDetector) return;

        const guestEvents = this.osMediaDetector.playbackEvents;

        // Forward all events from guest mode to main playback events
        guestEvents.on('trackChanged', (state) => {
            this.playbackEvents.emit('trackChanged', state);
        });

        guestEvents.on('playbackResumed', (state) => {
            this.playbackEvents.emit('playbackResumed', state);
        });

        guestEvents.on('playbackPaused', (state) => {
            this.playbackEvents.emit('playbackPaused', state);
        });

        guestEvents.on('progressUpdated', (state) => {
            this.playbackEvents.emit('progressUpdated', state);
        });
    }

    /**
     * Initiate login flow for Spotify
     */
    public async initiateSpotifyLogin(): Promise<void> {
        await this.spotifyAuth?.openAuthUrl();
    }

    /**
     * Stop current media source
     */
    public async stopSource(): Promise<void> {
        if (this.currentSource === 'spotify' && this.spotifyAuth) {
            // Use the new internal method to properly stop polling
            this.spotifyAuth.stopPollingInternal();
        } else if (this.currentSource === 'guest' && this.osMediaDetector) {
            this.osMediaDetector.stop();
        }

        this.currentSource = null;
    }

    /**
     * Get current media source
     */
    public getCurrentSource(): MediaSource | null {
        return this.currentSource;
    }

    /**
     * Get playback events emitter
     */
    public getPlaybackEvents(): PlaybackEvents {
        return this.playbackEvents;
    }

    /**
     * Get SpotifyAuth instance (for advanced operations)
     */
    public getSpotifyAuth(): SpotifyAuth | null {
        return this.spotifyAuth;
    }

    /**
     * Check if Spotify source is initialized
     */
    public isSpotifyInitialized(): boolean {
        return this.spotifyAuth !== null;
    }

    /**
     * Check if guest mode is initialized
     */
    public isGuestModeInitialized(): boolean {
        return this.osMediaDetector !== null && this.osMediaDetector.isInitialized();
    }
}
