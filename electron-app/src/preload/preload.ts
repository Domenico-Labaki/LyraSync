import { contextBridge, ipcRenderer } from "electron";
import { PlaybackWithLyrics } from "../main/PlaybackState";
import type { ModelProgressEvent } from "../main/modelManager";

export type AuthStatus = {
    authenticated: boolean;
    source: 'spotify' | 'guest' | null;
};

export interface AlignTrackResult {
  sentences:     Array<{ line: string; start: number; end: number; confidence: number }>;
  used_fallback: boolean;
  duration_sec:  number;
  cached:        boolean;
}

export interface AlignTrackParams {
  title:       string;
  artist:      string;
  durationSec: number | null;
  lyrics:      string;
  trackId:     string;
}

contextBridge.exposeInMainWorld("api", {
    onPlaybackStateChanged: (callback: (state: PlaybackWithLyrics) => void) => {
        ipcRenderer.on('playback-state-changed', (_, state) => callback(state));
    },
    onHoverChanged: (callback: (state: any) => void) => {
        ipcRenderer.on("hover-state", (_, state) => callback(state));
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
        ipcRenderer.send('start-spotify-login');
    },
    rendererReady: () => {
        ipcRenderer.send('renderer-ready');
    },
    onProgress: (cb: (event: ModelProgressEvent) => void): void => {
        ipcRenderer.on("model-manager:progress", (_ipcEvent, payload) => {
            cb(payload as ModelProgressEvent);
        });
    },
    onReady: (cb: () => void): void => {
        ipcRenderer.once("model-manager:ready", () => cb());
    },
    removeAllListeners: (): void => {
        ipcRenderer.removeAllListeners("model-manager:progress");
        ipcRenderer.removeAllListeners("model-manager:ready");
    },

    // ── Fixed: actual function, not a type annotation ──────────────────────
    alignTrack: (params: AlignTrackParams): Promise<AlignTrackResult> =>
        ipcRenderer.invoke("align-track", params),
});