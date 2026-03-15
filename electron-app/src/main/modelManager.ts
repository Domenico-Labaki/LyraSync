/**
 * modelManager.ts — LyraSync (main process)
 *
 * Connects to the Python service's SSE stream at GET /download-progress,
 * forwards structured progress events to the renderer via IPC, and
 * retries indefinitely on failure with exponential backoff.
 *
 * Flow:
 *   1. startModelManager() is called from main.ts after the Python
 *      service has started (wait for /status to respond first).
 *   2. Opens an SSE connection to http://localhost:{PORT}/download-progress.
 *   3. Forwards each event to the renderer as "model-manager:progress".
 *   4. On final { model: "all", status: "ready" } event, emits
 *      "model-manager:ready" and closes the connection.
 *   5. On any error (network drop, Python crash), waits with backoff
 *      and reconnects automatically.
 */

import { BrowserWindow } from "electron";
import http from "http";

// ── Config ────────────────────────────────────────────────────────────────────

const PYTHON_PORT  = 8765;
const SSE_PATH     = "/download-progress";
const RETRY_BASE_MS  = 2_000;   // initial retry delay
const RETRY_MAX_MS   = 30_000;  // cap on retry delay
const RETRY_FACTOR   = 1.5;     // backoff multiplier

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ModelProgressEvent {
  model:    string;       // "demucs" | "faster-whisper" | "all"
  pct:      number;       // 0–100
  status:   string;       // "downloading" | "ready" | "already_ready" | "error"
  label?:   string;       // human-readable model name
  message?: string;       // error message if status === "error"
}

// ── State ─────────────────────────────────────────────────────────────────────

let _window:       BrowserWindow | null = null;
let _ready         = false;
let _stopped       = false;
let _retryDelay    = RETRY_BASE_MS;
let _retryTimeout: ReturnType<typeof setTimeout> | null = null;
let _activeReq:    http.ClientRequest | null = null;

// ── IPC channel names (shared with preload + renderer) ────────────────────────

export const IPC_PROGRESS = "model-manager:progress";  // main → renderer
export const IPC_READY    = "model-manager:ready";     // main → renderer, once

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Start the model manager. Call this from main.ts after the Python
 * service is confirmed running (i.e. after /status returns 200).
 *
 * @param win  The BrowserWindow to forward IPC events to.
 */
export function startModelManager(win: BrowserWindow): void {
  _window  = win;
  _stopped = false;
  _connect();
}

/**
 * Stop all retries and close any open connection.
 * Call this when the app is quitting.
 */
export function stopModelManager(): void {
  _stopped = true;
  if (_retryTimeout) {
    clearTimeout(_retryTimeout);
    _retryTimeout = null;
  }
  if (_activeReq) {
    _activeReq.destroy();
    _activeReq = null;
  }
}

/**
 * Whether all models have been confirmed ready in this session.
 * Use this to gate the align button state on startup.
 */
export function areModelsReady(): boolean {
  return _ready;
}

// ── SSE connection ────────────────────────────────────────────────────────────

function _connect(): void {
  if (_stopped) return;

  const options: http.RequestOptions = {
    hostname: "127.0.0.1",
    port:     PYTHON_PORT,
    path:     SSE_PATH,
    method:   "GET",
    headers:  { Accept: "text/event-stream" },
  };

  let buffer = "";

  const req = http.request(options, (res) => {
    // Non-200 means the Python service isn't ready yet — retry
    if (res.statusCode !== 200) {
      res.resume();
      _scheduleRetry();
      return;
    }

    // Reset backoff on successful connection
    _retryDelay = RETRY_BASE_MS;

    res.setEncoding("utf8");

    res.on("data", (chunk: string) => {
      buffer += chunk;
      // SSE events are separated by double newlines
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";   // keep incomplete trailing chunk

      for (const part of parts) {
        _handleSsePart(part.trim());
      }
    });

    res.on("end", () => {
      // Stream closed — if not yet ready, reconnect
      if (!_ready) {
        _scheduleRetry();
      }
    });

    res.on("error", () => {
      _scheduleRetry();
    });
  });

  req.on("error", () => {
    _scheduleRetry();
  });

  req.setTimeout(0);   // no timeout — SSE streams are long-lived
  req.end();

  _activeReq = req;
}

// ── SSE parsing ───────────────────────────────────────────────────────────────

function _handleSsePart(raw: string): void {
  if (!raw || !raw.startsWith("data:")) return;

  const jsonStr = raw.replace(/^data:\s*/, "").trim();

  let event: ModelProgressEvent;
  try {
    event = JSON.parse(jsonStr) as ModelProgressEvent;
  } catch {
    return;   // malformed event — ignore
  }

  // Forward every event to the renderer
  _send(IPC_PROGRESS, event);

  // All models ready — emit ready signal and stop
  if (event.model === "all" && event.status === "ready") {
    _ready = true;
    _send(IPC_READY, { timestamp: Date.now() });
    stopModelManager();
  }

  // Error on a specific model — Python will retry internally,
  // but we log it here for visibility
  if (event.status === "error") {
    console.error(`[model-manager] ${event.model} error: ${event.message ?? "unknown"}`);
  }
}

// ── Retry logic ───────────────────────────────────────────────────────────────

function _scheduleRetry(): void {
  if (_stopped) return;

  console.log(`[model-manager] retrying in ${_retryDelay}ms…`);

  _retryTimeout = setTimeout(() => {
    _retryTimeout = null;
    _connect();
  }, _retryDelay);

  // Exponential backoff capped at RETRY_MAX_MS
  _retryDelay = Math.min(_retryDelay * RETRY_FACTOR, RETRY_MAX_MS);
}

// ── IPC send helper ───────────────────────────────────────────────────────────

function _send(channel: string, payload: unknown): void {
  if (_window && !_window.isDestroyed()) {
    _window.webContents.send(channel, payload);
  }
}