import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("api", {
    onPlaybackStateChanged: (callback: (state: any) => void) => {
        ipcRenderer.on('playback-state-changed', (_, state) => callback(state));
    },
    onHoverChanged: (callback: (state: any) => void) => {
        ipcRenderer.on("hover-state", (_, state) => callback(state))
    }
});
