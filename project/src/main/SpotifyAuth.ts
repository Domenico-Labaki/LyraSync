import dotenv from 'dotenv';
import { BrowserWindow } from 'electron';
dotenv.config();

import { shell } from 'electron';
import express from 'express';
import axios from 'axios';
import { startPolling } from './Poller.js';
import { PlaybackEvents } from './PlaybackEvents.js';
import { setAccessToken, setRefreshToken, getRefreshToken } from './TokenStore.js';

export class SpotifyAuth {
    private clientId = process.env.SPOTIFY_CLIENT_ID!;
    private clientSecret = process.env.SPOTIFY_CLIENT_SECRET!;
    private redirectUri = process.env.SPOTIFY_REDIRECT_URI!;
    private scopes = [
        "user-read-playback-state",
        "user-read-currently-playing"
    ];
    private app = express();
    public playbackEvents = new PlaybackEvents();
    public stopPolling: (() => void) | null = null;

    constructor(mainWindow: BrowserWindow) {
        this.setupCallbackRoute();
        this.playbackEvents.setMainWindow(mainWindow);
    }

    public async openAuthUrl() {
        try {
            const authUrl =
                `https://accounts.spotify.com/authorize` +
                `?response_type=code` +
                `&client_id=${this.clientId}` +
                `&scope=${encodeURIComponent(this.scopes.join(' '))}` +
                `&redirect_uri=${encodeURIComponent(this.redirectUri)}`;

            console.log("Opening browser for Spotify login...");
            await shell.openExternal(authUrl);
        } catch (err) {
            console.error("Failed to open Spotify login:", err);
        }
    }

    private setupCallbackRoute() {
        this.app.get('/callback', async (req, res) => {
            const code = req.query.code as string;
            if (!code) return res.send("No code found in query parameters.");

            try {
                const params = new URLSearchParams();
                params.append('grant_type', 'authorization_code');
                params.append('code', code);
                params.append('redirect_uri', this.redirectUri);

                const authString = Buffer.from(`${this.clientId}:${this.clientSecret}`).toString('base64');

                const response = await axios.post('https://accounts.spotify.com/api/token', params, {
                    headers: {
                        'Authorization': `Basic ${authString}`,
                        'Content-Type': 'application/x-www-form-urlencoded'
                    }
                });

                const { access_token, refresh_token, expires_in } = response.data;

                setAccessToken(access_token);
                await setRefreshToken(refresh_token);

                console.log('Spotify authorization successful');
                console.log('Access token expires in:', expires_in, 'seconds');

                res.send("Spotify authorization successful! You can close this tab.");
                
                this.stopPolling = startPolling(this.playbackEvents, 1000);

            } catch (err) {
                console.error(err);
                res.send("Authorization failed. Check console.");
            }
        });
    }

    public start(port: number = 8888) {
        this.app.listen(port, () => console.log(`Listening on ${this.redirectUri}`));
    }

    public async refreshAccessToken(refreshToken: string): Promise<string> {
        const params = new URLSearchParams();
        params.append('grant_type', 'refresh_token');
        params.append('refresh_token', refreshToken);

        const authString = Buffer.from(`${this.clientId}:${this.clientSecret}`).toString('base64');

        const response = await axios.post('https://accounts.spotify.com/api/token', params, {
            headers: {
                Authorization: `Basic ${authString}`,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });

        return response.data.access_token;
    }

    public async refreshLogin() {
        
        const refreshToken = await getRefreshToken();
        
        if (refreshToken) {
            console.log("Found refresh token, refreshing access token...");

            try {
                const accessToken = await this.refreshAccessToken(refreshToken);
                setAccessToken(accessToken);

                this.stopPolling = startPolling(this.playbackEvents, 1000);
                return true;
            } catch (err) {
                console.error("Refresh failed, forcing re-login");
            }
        }

        return false;

    }
}
