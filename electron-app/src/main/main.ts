import { app, BrowserWindow, screen, ipcMain } from "electron";
import path from "path";
import http from "http";
import { spawn, ChildProcess } from "child_process";
import { MediaSourceManager, MediaSource } from "./MediaSourceManager.js";
import { clearToken, clearCachedToken, setGuestModePreference, getGuestModePreference, clearGuestModePreference } from "./TokenStore.js";
import { SpotifyAuth } from "./SpotifyAuth.js";
import { startModelManager, stopModelManager } from "./modelManager.js";

// ── Python service config ─────────────────────────────────────────────────────

const PYTHON_PORT   = 8765;
const STATUS_PATH   = "/status";
const POLL_INTERVAL = 1_000;   // ms between /status polls
const MAX_POLLS     = 60;      // give Python up to 60s to start

// ── App state ─────────────────────────────────────────────────────────────────

let win: BrowserWindow;
let mediaSourceManager: MediaSourceManager;
let pythonProcess: ChildProcess | null = null;

export var auth: SpotifyAuth | null = null;

// ── Python service ────────────────────────────────────────────────────────────

function spawnPythonService(): void {
  const isDev = !app.isPackaged; // const isDev  = process.env.NODE_ENV === "development";
  const script = isDev
    ? path.join(__dirname, "../../../python-ml-service/src/app.py")
    : path.join(process.resourcesPath, "lyrasync-aligner");

  const proc = isDev
    ? spawn("python", [script], { stdio: "pipe" })
    : spawn(script,  [],        { stdio: "pipe" });

  proc.stdout?.on("data", (d: Buffer) =>
    console.log("[python]", d.toString().trim())
  );
  proc.stderr?.on("data", (d: Buffer) =>
    console.error("[python:err]", d.toString().trim())
  );
  proc.on("exit", (code) =>
    console.log(`[python] exited with code ${code}`)
  );

  pythonProcess = proc;
}

function waitForPythonService(): Promise<void> {
  return new Promise((resolve) => {
    let attempts = 0;

    const poll = (): void => {
      attempts++;
      const req = http.get(
        `http://127.0.0.1:${PYTHON_PORT}${STATUS_PATH}`,
        (res) => {
          res.resume();
          if (res.statusCode === 200) {
            console.log("[main] Python service ready");
            resolve();
          } else {
            retry();
          }
        }
      );
      req.on("error", retry);
      req.setTimeout(800, () => { req.destroy(); retry(); });
    };

    const retry = (): void => {
      if (attempts >= MAX_POLLS) {
        // Service failed to start — resolve anyway so the app still opens.
        // The renderer will see modelsReady=false and block the align button.
        console.error("[main] Python service did not start in time");
        resolve();
        return;
      }
      setTimeout(poll, POLL_INTERVAL);
    };

    poll();
  });
}

// ── Window ────────────────────────────────────────────────────────────────────

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;

  const iconPath = path.join(__dirname, '../imgs/icon.ico');

  win = new BrowserWindow({
    width: 500,
    height: 300,
    x: width - 550,
    y: height - 350,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/preload.js")
    },
    title: "LyraSync",
    icon: iconPath,
  });

  win.setIgnoreMouseEvents(false);

  let isIgnoringMouse = false;
  let focusMode = false;

  setInterval(() => {
    if (win && !win.isDestroyed()) {
      const cursor = screen.getCursorScreenPoint();
      const bounds = win.getBounds();

      const inside =
        cursor.x >= bounds.x &&
        cursor.x <= bounds.x + bounds.width &&
        cursor.y >= bounds.y &&
        cursor.y <= bounds.y + bounds.height;

      const relY      = cursor.y - bounds.y;
      const inLyrics  = inside && relY < bounds.height * 0.9;
      const inSongBar = inside && relY >= bounds.height * 0.9;

      if (inLyrics && focusMode && !isIgnoringMouse) {
        isIgnoringMouse = true;
        win.setIgnoreMouseEvents(true, { forward: true });
      } else if ((inSongBar || !inside || !focusMode) && isIgnoringMouse) {
        isIgnoringMouse = false;
        win.setIgnoreMouseEvents(false);
      }
      win.webContents.send("hover-state", inside);
    }
  }, 16);

  if (process.env.NODE_ENV === "development") {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(path.join(__dirname, "../renderer/index.html"));
  }

  win.show();

  // Initialize MediaSourceManager
  mediaSourceManager = new MediaSourceManager(win);

  // ── Existing IPC handlers ─────────────────────────────────────────────────

  ipcMain.on('focus-mode', (_event, enabled: boolean) => {
    focusMode = !!enabled;
    if (!focusMode && isIgnoringMouse) {
      isIgnoringMouse = false;
      win.setIgnoreMouseEvents(false);
    }
  });

  ipcMain.on('logout', async () => {
    try {
      await mediaSourceManager.stopSource();
      clearToken();
      await clearCachedToken();
      await clearGuestModePreference();
      if (win && !win.isDestroyed()) {
        win.webContents.send('playback-state-changed', null);
        win.webContents.send('auth-status', { authenticated: false, source: null });
      }
    } catch (err) {
      console.error('Logout failed:', err);
    }
  });

  ipcMain.on('renderer-ready', async () => {
    try {
      const guestModeEnabled = await getGuestModePreference();
      if (guestModeEnabled) {
        const success = await mediaSourceManager.startSource('guest');
        if (success) {
          if (win && !win.isDestroyed()) {
            win.webContents.send('auth-status', { authenticated: true, source: 'guest' });
          }
          return;
        }
        await clearGuestModePreference();
      }

      const spotifyAuth = new SpotifyAuth(win);
      spotifyAuth.start();
      const spotifySuccess = await spotifyAuth.refreshLogin();

      if (spotifySuccess) {
        auth = spotifyAuth;
        if (win && !win.isDestroyed()) {
          win.webContents.send('auth-status', { authenticated: true, source: 'spotify' });
        }
        return;
      }

      if (win && !win.isDestroyed()) {
        win.webContents.send('auth-status', { authenticated: false, source: null });
      }
    } catch (err) {
      console.error('Failed to restore session:', err);
      if (win && !win.isDestroyed()) {
        win.webContents.send('auth-status', { authenticated: false, source: null });
      }
    }
  });

  ipcMain.on('start-spotify-login', async () => {
    const success = await mediaSourceManager.startSource('spotify');
    if (!success) {
      await mediaSourceManager.initiateSpotifyLogin();
    }
  });

  ipcMain.on('start-guest-mode', async () => {
    try {
      const success = await mediaSourceManager.startSource('guest');
      if (success) {
        await setGuestModePreference(true);
        if (win && !win.isDestroyed()) {
          win.webContents.send('auth-status', { authenticated: true, source: 'guest' });
        }
      } else {
        console.error('Failed to initialize guest mode');
        if (win && !win.isDestroyed()) {
          win.webContents.send('auth-status', { authenticated: false, source: null });
        }
      }
    } catch (err) {
      console.error('Guest mode error:', err);
    }
  });

  ipcMain.handle("align-track", async (_event, params: {
    title:       string;
    artist:      string;
    durationSec: number | null;
    lyrics:      string;
    trackId:     string;
  }) => {
    const body = JSON.stringify({
      title:        params.title,
      artist:       params.artist,
      duration_sec: params.durationSec,
      lyrics:       params.lyrics,
      lyrics_type:  "plain",
      track_id:     params.trackId,
    });
  
    return new Promise((resolve, reject) => {
      const req = http.request(
        {
          hostname: "127.0.0.1",
          port:     PYTHON_PORT,
          path:     "/align",
          method:   "POST",
          headers:  {
            "Content-Type":   "application/json",
            "Content-Length": Buffer.byteLength(body),
          },
        },
        (res) => {
          let data = "";
          res.setEncoding("utf8");
          res.on("data", (chunk) => { data += chunk; });
          res.on("end", () => {
            try {
              const parsed = JSON.parse(data);
              if (res.statusCode === 200) {
                resolve(parsed);
              } else {
                // Return a typed error so the renderer can handle it gracefully
                reject(new Error(parsed?.detail?.message ?? `HTTP ${res.statusCode}`));
              }
            } catch {
              reject(new Error("Failed to parse alignment response"));
            }
          });
        }
      );
  
      req.on("error", (err) => reject(err));
      req.setTimeout(180_000, () => {   // 3 min — Demucs can be slow
        req.destroy();
        reject(new Error("Alignment timed out"));
      });
  
      req.write(body);
      req.end();
    });
  });

  ipcMain.on('close-app', () => {
    try {
      stopModelManager();
      
      // Gracefully shut down the Python service (whether it's a spawned process or external)
      const shutdownReq = http.request(
        {
          hostname: "127.0.0.1",
          port: PYTHON_PORT,
          path: "/shutdown",
          method: "POST",
        },
        (res) => {
          res.resume(); // consume response
          console.log("[main] Python service shutdown signal sent");
        }
      );
      
      shutdownReq.on("error", () => {
        // Service may already be stopped or unreachable — that's fine
        console.log("[main] Python service not reachable (may already be stopped)");
      });
      
      shutdownReq.setTimeout(2000, () => {
        shutdownReq.destroy();
      });
      
      shutdownReq.end();
      
      // Kill spawned process if it exists (dev mode)
      if (pythonProcess && !pythonProcess.killed) {
        pythonProcess.kill();
      }
    } catch (err) {
      console.error('Error shutting down services:', err);
    }
    
    // Exit after brief delay to allow shutdown signal to be sent
    setTimeout(() => {
      app.quit();
    }, 500);
  });
}

// ── App lifecycle ─────────────────────────────────────────────────────────────

app.whenReady().then(async () => {
  // Spawn Python service first so it has maximum time to start
  // while Electron is still loading the window.
  spawnPythonService();

  // Create the window immediately — don't block UI on Python startup.
  createWindow();

  // Wait for Python to be reachable in the background, then open
  // the SSE stream for model downloads. The window is already
  // visible and interactive by the time this resolves.
  waitForPythonService().then(() => {
    startModelManager(win);
  });
});

app.on("window-all-closed", () => {
  stopModelManager();
  pythonProcess?.kill();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  stopModelManager();
  pythonProcess?.kill();
});