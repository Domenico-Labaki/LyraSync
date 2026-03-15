import { contextBridge, ipcRenderer } from "electron";
import { PlaybackWithLyrics } from "../main/PlaybackState";
import type { ModelProgressEvent } from "../main/modelManager";

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
    },

    /**
     * Subscribe to per-model download progress events.
     * Callback receives a ModelProgressEvent on each SSE tick.
     */
    onProgress: (cb: (event: ModelProgressEvent) => void): void => {
        ipcRenderer.on("model-manager:progress", (_ipcEvent, payload) => {
        cb(payload as ModelProgressEvent);
        });
    },
    
    /**
     * Subscribe to the one-shot ready event.
     * Fires once when all models are confirmed downloaded.
     */
    onReady: (cb: () => void): void => {
        ipcRenderer.once("model-manager:ready", () => cb());
    },
    
    /**
     * Remove all model manager listeners.
     * Call this in React cleanup (useEffect return) to avoid leaks.
     */
    removeAllListeners: (): void => {
        ipcRenderer.removeAllListeners("model-manager:progress");
        ipcRenderer.removeAllListeners("model-manager:ready");
    },
});

// Type declaration for renderer-side window augmentation
declare global {
  interface Window {
    modelManager: {
      onProgress: (cb: (event: ModelProgressEvent) => void) => void;
      onReady:    (cb: () => void) => void;
      removeAllListeners: () => void;
    };
  }
}