export class PlaybackState {

    public readonly trackId: string;
    public readonly trackName: string;
    public readonly artist: string;
    private readonly progressMs: number;
    private readonly durationMs: number;
    private readonly isPlaying: boolean;

    constructor(trackId = '', trackName = '', artist = '', progressMs = 0, durationMs = 0, isPlaying = false) {
        this.trackId = trackId;
        this.trackName = trackName;
        this.artist = artist;
        this.progressMs = progressMs;
        this.durationMs = durationMs;
        this.isPlaying = isPlaying;
    }

    // Getters
    public getProgressMs(): number { return this.progressMs; }

    public getDurationMs(): number { return this.durationMs; }

    public getIsPlaying(): boolean { return this.isPlaying; }

    // Comparison methods
    public hasTrackChanged(other: PlaybackState): boolean {
        return this.trackId != other.trackId;
    }

    public hasPlaybackToggled(other: PlaybackState): boolean {
        return this.isPlaying != other.isPlaying;
    }

    public hasProgressChanged(other: PlaybackState): boolean {
        return this.progressMs != other.progressMs;
    }

}