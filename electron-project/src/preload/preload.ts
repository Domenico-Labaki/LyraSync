import { contextBridge, ipcRenderer } from "electron";
import { PlaybackWithLyrics } from "../main/PlaybackState";

contextBridge.exposeInMainWorld("api", {
    onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics) => void) => {
        ipcRenderer.on('playback-state-changed', (_, state) => callback(state));
    },
    onHoverChanged: (callback: (state: any) => void) => {
        ipcRenderer.on("hover-state", (_, state) => callback(state))
    }
    ,
    setFocusMode: (enabled: boolean) => {
        ipcRenderer.send('focus-mode', enabled);
    }
    ,
    logout: () => {
        ipcRenderer.send('logout');
    }
    ,
    onAuthStatus: (callback: (status: boolean) => void) => {
        ipcRenderer.on('auth-status', (_, status) => callback(status));
    },
    startLogin: () => {
        ipcRenderer.send('start-login');
    },
    rendererReady: () => {
        ipcRenderer.send('renderer-ready');
    }
});
