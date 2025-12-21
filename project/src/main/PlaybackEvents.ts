import { EventEmitter } from 'events';
import { BrowserWindow } from 'electron';
import { PlaybackState } from './PlaybackState.js';

export class PlaybackEvents extends EventEmitter {
    private mainWindow: BrowserWindow | null = null;

    constructor(mainWindow?: BrowserWindow) {
        super();
        this.mainWindow = mainWindow || null;
        this.attachDefaultListeners();
    }

    public setMainWindow(mainWindow: BrowserWindow) {
        this.mainWindow = mainWindow;
    }

    private sendToRenderer(state: PlaybackState) {
        if (this.mainWindow && !this.mainWindow.isDestroyed()) {
            this.mainWindow.webContents.send('playback-state-changed', {
                trackName: state.trackName,
                artist: state.artist,
                progressMs: state.getProgressMs(),
                durationMs: state.getDurationMs(),
                isPlaying: state.getIsPlaying()
            });
        }
    }

    private attachDefaultListeners() {
        this.on('trackChanged', (state: PlaybackState) => {
            console.log('Track changed:', state.trackName, 'by', state.artist);
            this.sendToRenderer(state);
        });

        this.on('playbackPaused', (state: PlaybackState) => {
            console.log('Playback paused at', state.getProgressMs(), 'ms');
            this.sendToRenderer(state);
        });

        this.on('playbackResumed', (state: PlaybackState) => {
            console.log('Playback resumed at', state.getProgressMs(), 'ms');
            this.sendToRenderer(state);
        });

        this.on('progressUpdated', (state: PlaybackState) => {
            console.log('Progress updated:', state.getProgressMs(), 'ms');
            this.sendToRenderer(state);
        });
    }
}
