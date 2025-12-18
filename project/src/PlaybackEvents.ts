import { EventEmitter } from 'events';
import { PlaybackState } from './PlaybackState.js';

export class PlaybackEvents extends EventEmitter {
    constructor() {
        super();
        this.attachDefaultListeners();
    }

    private attachDefaultListeners() {
        this.on('trackChanged', (state: PlaybackState) => {
            console.log('Track changed:', state.trackName, 'by', state.artist);
        });

        this.on('playbackPaused', (state: PlaybackState) => {
            console.log('Playback paused at', state.getProgressMs(), 'ms');
        });

        this.on('playbackResumed', (state: PlaybackState) => {
            console.log('Playback resumed at', state.getProgressMs(), 'ms');
        });

        this.on('progressUpdated', (state: PlaybackState) => {
            console.log('Progress updated:', state.getProgressMs(), 'ms');
        });
    }
}
