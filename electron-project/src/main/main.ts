import { app, BrowserWindow, screen, ipcMain } from "electron";
import path from "path";
import { MediaSourceManager, MediaSource } from "./MediaSourceManager.js";
import { clearToken, clearCachedToken } from "./TokenStore.js";
import { SpotifyAuth } from "./SpotifyAuth.js";

let win: BrowserWindow;
let mediaSourceManager: MediaSourceManager;

// Keep auth for backward compatibility if needed
export var auth: SpotifyAuth | null = null;

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

  // Initialize MediaSourceManager
  mediaSourceManager = new MediaSourceManager(win);

  // Receive focusMode updates from renderer
  ipcMain.on('focus-mode', (_event, enabled: boolean) => {
    focusMode = !!enabled;
    if (!focusMode && isIgnoringMouse) {
      isIgnoringMouse = false;
      win.setIgnoreMouseEvents(false);
    }
  });

  // Handle logout requests from renderer
  ipcMain.on('logout', async () => {
    try {
      await mediaSourceManager.stopSource();
      
      // Clear Spotify tokens if Spotify was the source
      clearToken();
      await clearCachedToken();

      // Inform renderer to clear UI and show login screen
      if (win && !win.isDestroyed()) {
        win.webContents.send('playback-state-changed', null);
        win.webContents.send('auth-status', { authenticated: false, source: null });
      }
    } catch (err) {
      console.error('Logout failed:', err);
    }
  });

  // Renderer ready: try to restore previous session
  ipcMain.on('renderer-ready', async () => {
    try {
      // Try to restore Spotify session first
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

      // No previous session found
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

  // Start Spotify login flow
  ipcMain.on('start-spotify-login', async () => {
    try {
      const success = await mediaSourceManager.startSource('spotify');
      if (success) {
        mediaSourceManager.initiateSpotifyLogin();
      } else {
        console.error('Failed to initialize Spotify source');
      }
    } catch (err) {
      console.error('Spotify login error:', err);
    }
  });

  // Start Guest Mode (OS media controls)
  ipcMain.on('start-guest-mode', async () => {
    try {
      const success = await mediaSourceManager.startSource('guest');
      if (success) {
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

app.whenReady().then(createWindow);
