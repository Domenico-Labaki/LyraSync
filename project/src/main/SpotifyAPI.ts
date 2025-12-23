import axios from 'axios';
import { getAccessToken } from './TokenStore';
import { PlaybackState } from './PlaybackState';

export class RateLimitError extends Error {
    public readonly retryAfterMs: number;

    constructor(retryAfterMs: number) {
        super('Spotify rate limit exceeded');
        this.retryAfterMs = retryAfterMs;
    }
}

export async function getCurrentPlayback(): Promise<PlaybackState | null> {
    try {
        const response = await axios.get(
            'https://api.spotify.com/v1/me/player',
            {
                headers: {
                    Authorization: `Bearer ${getAccessToken()}`
                },
                validateStatus: () => true
            }
        );

        if (response.status === 204) {
            return null;
        }

        if (response.status === 429) {
            const retryAfterSec = Number(response.headers['retry-after'] ?? 1);
            throw new RateLimitError(retryAfterSec * 1000);
        }

        if (response.status === 401) {
            throw new Error('UNAUTHORIZED');
        }

        if (response.status >= 400) {
            throw new Error(`Spotify API error ${response.status}`);
        }

        const data = response.data;

        return new PlaybackState(
            data.item?.id ?? '',
            data.item?.name ?? '',
            data.item?.artists?.map((a: any) => a.name).join(', ') ?? '',
            data.progress_ms ?? 0,
            data.item?.duration_ms ?? 0,
            data.is_playing ?? false
        );
    } catch (err) {
        throw err;
    }
}
