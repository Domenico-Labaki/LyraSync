import { PlaybackState } from "./PlaybackState.js";

// Fetch the current playback state from the Spotify API
export async function fetchCurrentPlayback(accessToken: string): Promise<PlaybackState | null> {
    
    const response = await fetch('https://api.spotify.com/v1/me/player/currently-playing', {
        headers: {
            Authorization: `Bearer ${accessToken}`,
        }
    });

    // Check if nothing is playing
    if (response.status == 202 || response.status == 204) {return null;}

    const data = await response.json();

    return new PlaybackState(
        data.item.id,
        data.item.name, 
        data.item.artists.map((a: any) => a.name).join(', '),
        data.progress_ms,
        data.item.duration_ms,
        data.is_playing
    );
}