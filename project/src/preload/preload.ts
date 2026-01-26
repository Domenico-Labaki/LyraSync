import { contextBridge, ipcRenderer } from "electron";
import { PlaybackWithLyrics } from "../main/PlaybackState";

contextBridge.exposeInMainWorld("api", {
    onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics) => void) => {
        ipcRenderer.on('playback-state-changed', (_, state) => callback(state));
    },
    onHoverChanged: (callback: (state: any) => void) => {
        ipcRenderer.on("hover-state", (_, state) => callback(state))
    }
});
