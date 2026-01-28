import { EventEmitter } from 'events';
import { BrowserWindow } from 'electron';
import { PlaybackState } from './PlaybackState.js';
import { LyricsResult, LyricsService } from './LyricsService.js';

export class PlaybackEvents extends EventEmitter {
    private mainWindow: BrowserWindow | null = null;
    public firstPlayback: boolean = true;

    constructor(mainWindow?: BrowserWindow) {
        super();
        this.mainWindow = mainWindow || null;
        this.attachDefaultListeners();
    }

    public setMainWindow(mainWindow: BrowserWindow) {
        this.mainWindow = mainWindow;
    }

    private async sendToRenderer(state: PlaybackState, lyrics: LyricsResult | null = null) {
        if (this.mainWindow && !this.mainWindow.isDestroyed()) {
            this.mainWindow.webContents.send('playback-state-changed', {
                trackId: state.trackId,
                trackName: state.trackName,
                artist: state.artist,
                progressms: state.progressMs,
                durationMs: state.durationMs,
                isPlaying: state.isPlaying,
                imgUrl: state.imgUrl,
                lyrics: lyrics
            });
        }
    }

    private async attachDefaultListeners() {
        this.on('trackChanged', async (state: PlaybackState) => {
            console.log('Track changed:', state.trackName, 'by', state.artist);

            // Fetch new lyrics
            const lyrics = await LyricsService.getLyrics(
                state.artist,
                state.trackName
            );

            this.sendToRenderer(state, lyrics);
        });

        this.on('playbackPaused', (state: PlaybackState) => {
            console.log('Playback paused at', state.progressMs, 'ms');
            this.sendToRenderer(state);
        });

        this.on('playbackResumed', async (state: PlaybackState) => {
            console.log('Playback resumed at', state.progressMs, 'ms');

            if (this.firstPlayback) {

                // If this is the first track
                const lyrics = await LyricsService.getLyrics(
                    state.artist,
                    state.trackName
                );

                this.sendToRenderer(state, lyrics);
                this.firstPlayback = false;

            } else {
                this.sendToRenderer(state);
            }
        });

        this.on('progressUpdated', (state: PlaybackState) => {
            console.log('Progress updated:', state.progressMs, 'ms');
            this.sendToRenderer(state);
        });
    }
}
