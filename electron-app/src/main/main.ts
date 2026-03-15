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
  const isDev  = process.env.NODE_ENV === "development";
  const script = isDev
    ? path.join(__dirname, "../../python-ml-service/src/app.py")
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