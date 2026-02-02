import { app, BrowserWindow, screen, ipcMain } from "electron";
import path from "path";
import { SpotifyAuth } from "./SpotifyAuth.js";
import { clearToken, clearCachedToken, getRefreshToken } from "./TokenStore.js";

let win: BrowserWindow;
export var auth: SpotifyAuth;

function createWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width, height } = primaryDisplay.workAreaSize;
  
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
    }
  });

  win.setIgnoreMouseEvents(false);
  //win.setIgnoreMouseEvents(true, { forward: true });

  let isIgnoringMouse = false;
  let focusMode = false; // renderer-controlled: when true, allow passthrough in lyrics area

  // Check cursor position ~60fps and toggle mouse event passthrough
  setInterval(() => {
    if (win && !win.isDestroyed()) {
      const cursor = screen.getCursorScreenPoint();
      const bounds = win.getBounds();

      const inside =
        cursor.x >= bounds.x &&
        cursor.x <= bounds.x + bounds.width &&
        cursor.y >= bounds.y &&
        cursor.y <= bounds.y + bounds.height;

      const relY = cursor.y - bounds.y;
      const inLyrics = inside && relY < bounds.height * 0.9; // top 90% is lyricsContainer
      const inSongBar = inside && relY >= bounds.height * 0.9; // bottom 10% is songBar

      if (inLyrics && focusMode && !isIgnoringMouse) {
        isIgnoringMouse = true;
        win.setIgnoreMouseEvents(true, { forward: true });
      } else if ((inSongBar || !inside || !focusMode) && isIgnoringMouse) {
        isIgnoringMouse = false;
        win.setIgnoreMouseEvents(false);
      }
      win.webContents.send("hover-state", inside);
    }
  }, 16); // ~60fps

  if (process.env.NODE_ENV === "development") {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(
      path.join(__dirname, "../renderer/index.html")
    );
  }

  win.show();
  // Receive focusMode updates from renderer
  ipcMain.on('focus-mode', (_event, enabled: boolean) => {
    focusMode = !!enabled;
    if (!focusMode && isIgnoringMouse) {
      isIgnoringMouse = false;
      win.setIgnoreMouseEvents(false);
    }
  });

  // Handle logout requests from renderer: clear stored tokens and stop polling
  ipcMain.on('logout', async () => {
    try {
      // Stop polling if active
      if (auth.stopPolling) {
        auth.stopPolling();
        auth.stopPolling = null;
      }
      
      auth.playbackEvents.firstPlayback = true;
      clearToken();
      await clearCachedToken();
      // Inform renderer to clear UI and show login screen
      if (win && !win.isDestroyed()) {
        win.webContents.send('playback-state-changed', null);
        win.webContents.send('auth-status', false);
      }
    } catch (err) {
      console.error('Logout failed:', err);
    }
  });
  
  auth = new SpotifyAuth(win);
  auth.start();

  // Ensure renderer listener is registered before sending auth status
  ipcMain.on('renderer-ready', () => {
    auth.refreshLogin().then((success) => {
      if (win && !win.isDestroyed()) {
        win.webContents.send('auth-status', success);
      }
    }).catch(() => {
      if (win && !win.isDestroyed()) {
        win.webContents.send('auth-status', false);
      }
    });
  });

  // Allow renderer to explicitly start login flow
  ipcMain.on('start-login', () => {
    auth.openAuthUrl();
  });
}

app.whenReady().then(createWindow);