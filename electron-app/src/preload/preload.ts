import { contextBridge, ipcRenderer } from "electron";
import { PlaybackWithLyrics } from "../main/PlaybackState";

export type AuthStatus = {
    authenticated: boolean;
    source: 'spotify' | 'guest' | null;
};

contextBridge.exposeInMainWorld("api", {
    onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics) => void) => {
        ipcRenderer.on('playback-state-changed', (_, state) => callback(state));
    },
    onHoverChanged: (callback: (state: any) => void) => {
        ipcRenderer.on("hover-state", (_, state) => callback(state))
    },
    setFocusMode: (enabled: boolean) => {
        ipcRenderer.send('focus-mode', enabled);
    },
    logout: () => {
        ipcRenderer.send('logout');
    },
    onAuthStatus: (callback: (status: AuthStatus) => void) => {
        ipcRenderer.on('auth-status', (_, status) => callback(status));
    },
    startSpotifyLogin: () => {
        ipcRenderer.send('start-spotify-login');
    },
    startGuestMode: () => {
        ipcRenderer.send('start-guest-mode');
    },
    startLogin: () => {
        // Backward compatibility
        ipcRenderer.send('start-spotify-login');
    },
    rendererReady: () => {
        ipcRenderer.send('renderer-ready');
    }
});
