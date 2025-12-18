import dotenv from 'dotenv';
dotenv.config();

import open from 'open';
import express from 'express';
import axios from 'axios';
import { startPolling } from './Poller.js';
import { PlaybackEvents } from './PlaybackEvents.js';
import { setAccessToken, setRefreshToken } from './TokenStore.js';

const clientId = process.env.SPOTIFY_CLIENT_ID!;
const clientSecret = process.env.SPOTIFY_CLIENT_SECRET!;
const redirectUri = process.env.SPOTIFY_REDIRECT_URI!;
const scopes = [
  "user-read-playback-state",
  "user-read-currently-playing"
];

// Build Spotify authorization URL
const authUrl =
  `https://accounts.spotify.com/authorize` +
  `?response_type=code` +
  `&client_id=${clientId}` +
  `&scope=${encodeURIComponent(scopes.join(' '))}` +
  `&redirect_uri=${encodeURIComponent(redirectUri)}`;

console.log("Opening browser for Spotify login...");
open(authUrl);

// Setup local Express server to handle callback
const app = express();

// Initialize events (listeners attached internally)
const playbackEvents = new PlaybackEvents();


app.get('/callback', async (req, res) => {
    const code = req.query.code as string;
    if (!code) return res.send("No code found in query parameters.");

    try {
        const params = new URLSearchParams();
        params.append('grant_type', 'authorization_code');
        params.append('code', code);
        params.append('redirect_uri', redirectUri);

        const authString = Buffer.from(`${clientId}:${clientSecret}`).toString('base64');

        const response = await axios.post('https://accounts.spotify.com/api/token', params, {
            headers: {
                'Authorization': `Basic ${authString}`,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
        });

        const { access_token, refresh_token, expires_in } = response.data;

        // Store tokens
        setAccessToken(access_token);
        setRefreshToken(refresh_token);

        console.log('Spotify authorization successful');
        console.log('Access token expires in:', expires_in, 'seconds');

        res.send("Spotify authorization successful! You can close this tab.");
        
        // Start polling AFTER auth succeeds
        startPolling(playbackEvents, 1000);

    } catch (err) {
        console.error(err);
        res.send("Authorization failed. Check console.");
    }
});

app.listen(8888, () => console.log(`Listening on ${redirectUri}`));
