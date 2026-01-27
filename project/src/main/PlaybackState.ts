import { LyricsResult } from "./LyricsService";

// Data transfer object
export interface PlaybackDTO {
    readonly trackId: string;
    readonly trackName: string;
    readonly artist: string;
    readonly progressMs: number;
    readonly durationMs: number;
    readonly isPlaying: boolean;
    readonly imgUrl: string | null;
}

export interface PlaybackWithLyrics extends PlaybackDTO {
    lyrics?: LyricsResult | null;
}

export class PlaybackState {

    private dto: PlaybackDTO;

    constructor(dto: PlaybackDTO) {
        this.dto = dto;
    }

    // Getters
    get trackId(): string { return this.dto.trackId; }

    get trackName(): string { return this.dto.trackName; }

    get artist(): string { return this.dto.artist; }

    get progressMs(): number { return this.dto.progressMs; }

    get durationMs(): number { return this.dto.durationMs; }

    get isPlaying(): boolean { return this.dto.isPlaying; }

    get imgUrl(): string | null {return this.dto.imgUrl; }

    get progressRatio(): number { return this.dto.progressMs / this.dto.durationMs; }

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