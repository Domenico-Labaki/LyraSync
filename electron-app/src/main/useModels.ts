/**
 * useModelManager.ts — LyraSync (renderer)
 *
 * React hook that consumes model manager IPC events and exposes
 * clean state to any component that needs to gate on model readiness.
 *
 * Usage:
 *   const { modelsReady, progress } = useModelManager()
 *
 *   <button disabled={!modelsReady} onClick={handleAlign}>
 *     Sync lyrics
 *   </button>
 *
 * The hook is designed to be used once at the app root (e.g. App.tsx)
 * and the state passed down via props or context. Avoid mounting it
 * in multiple components — each mount adds IPC listeners.
 */

import { useEffect, useRef, useState } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ModelProgress {
  model:   string;    // "demucs" | "faster-whisper" | "all"
  pct:     number;    // 0–100
  status:  string;    // "downloading" | "ready" | "already_ready" | "error"
  label?:  string;
  message?: string;
}

export interface ModelManagerState {
  /** True once the final { model: "all", status: "ready" } event arrives. */
  modelsReady: boolean;

  /**
   * Latest progress event per model, keyed by model name.
   * e.g. { "demucs": { pct: 80, status: "downloading", ... } }
   * Empty object until the first event arrives.
   */
  progress: Record<string, ModelProgress>;
}

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useModelManager(): ModelManagerState {
  const [modelsReady, setModelsReady] = useState(false);
  const [progress, setProgress] = useState<Record<string, ModelProgress>>({});

  // Stable ref so the IPC callbacks don't capture stale state
  const progressRef = useRef<Record<string, ModelProgress>>({});

  useEffect(() => {
    const { api } = window;

    if (!api) {
      // Running outside Electron (e.g. browser dev) — mark as ready immediately
      setModelsReady(true);
      return;
    }

    api.onProgress((event: ModelProgress) => {
      // Update the progress map for this model
      const updated = { ...progressRef.current, [event.model]: event };
      progressRef.current = updated;
      setProgress(updated);
    });

    api.onReady(() => {
      setModelsReady(true);
    });

    return () => {
      api.removeAllListeners();
    };
  }, []);

  return { modelsReady, progress };
}