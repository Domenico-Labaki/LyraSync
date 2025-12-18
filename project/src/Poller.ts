import { PlaybackState } from "./PlaybackState.js";
import { PlaybackEvents } from "./PlaybackEvents.js";
import { fetchCurrentPlayback } from "./SpotifyAPI.js";
import { getAccessToken, getRefreshToken, setAccessToken } from './TokenStore.js';
import { refreshAccessToken } from './SpotifyAuth.js';


async function pollOnce(events: PlaybackEvents) {
    try {
        return await fetchCurrentPlayback(getAccessToken());
    } catch (err: any) {

        if (err.response?.status === 401) {
            const newToken = await refreshAccessToken(getRefreshToken());
            setAccessToken(newToken);

            // retry once
            return await fetchCurrentPlayback(newToken);
        }

        throw err;
    }
}


export async function startPolling(events: PlaybackEvents, intervalMs = 2000) {
    let previousState: PlaybackState | null = null;

    while (true) {
        try {
            
            // Fetch current state, check for changes and fire events if needed

            const currentState = await pollOnce(events);

            if (currentState) {
                if (!previousState || currentState.hasTrackChanged(previousState)) {
                    events.emit('trackChanged', currentState);
                }

                if (!previousState || currentState.hasPlaybackToggled(previousState)) {
                    if (currentState.getIsPlaying()) {
                        events.emit('playbackResumed', currentState);
                    } else {
                        events.emit('playbackPaused', currentState);
                    }
                }

                if (!previousState || currentState.hasProgressChanged(previousState)) {
                    events.emit('progressUpdated', currentState);
                }

                previousState = currentState;
            }

        } catch (err) {
            console.error('Error fetching playback:', err);
        }

        await new Promise(res => setTimeout(res, intervalMs));
    }
}
