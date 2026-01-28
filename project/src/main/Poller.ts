import { getCurrentPlayback, RateLimitError } from './SpotifyAPI';
import { PlaybackEvents } from './PlaybackEvents';
import { PlaybackState } from './PlaybackState';

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

export function startPolling(
    events: PlaybackEvents,
    intervalMs = 2000
): () => void {
    let lastState: PlaybackState | null = null;
    let backoffUntil = 0;
    let shouldStop = false;

    const pollLoop = async () => {
        while (!shouldStop) {
            const now = Date.now();

            if (now < backoffUntil) {
                await sleep(backoffUntil - now);
                continue;
            }

            try {
                const state = await getCurrentPlayback();

                if (!state) {
                    await sleep(intervalMs);
                    continue;
                }

                if (!lastState) {
                    events.emit('playbackResumed', state);
                } else {
                    if (state.trackId !== lastState.trackId) {
                        events.emit('trackChanged', state);
                    }

                    if (state.isPlaying !== lastState.isPlaying) {
                        state.isPlaying
                            ? events.emit('playbackResumed', state)
                            : events.emit('playbackPaused', state);
                    }

                    events.emit('progressUpdated', state);
                }

                lastState = state;
                await sleep(intervalMs);

            } catch (err) {
                if (err instanceof RateLimitError) {
                    backoffUntil = Date.now() + err.retryAfterMs;
                    continue;
                }

                console.error('Polling error:', err);
                await sleep(intervalMs);
            }
        }
    };

    // Start polling in background
    pollLoop();

    // Return a function to stop polling
    return () => {
        shouldStop = true;
    };
}
