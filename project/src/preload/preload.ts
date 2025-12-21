import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("api", {
    onPlaybackStateChanged: (callback: (state: any) => void) => {
        ipcRenderer.on('playback-state-changed', (event, state) => callback(state));
    }
});
