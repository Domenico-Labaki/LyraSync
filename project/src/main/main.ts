import { app, BrowserWindow, screen, ipcMain } from "electron";
import path from "path";
import { SpotifyAuth } from "./SpotifyAuth.js";

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

  ipcMain.on('set-ignore-mouse', (_, ignore) => {
    win.setIgnoreMouseEvents(ignore, { forward: true });
  });

  if (process.env.NODE_ENV === "development") {
    win.loadURL("http://localhost:5173");
  } else {
    win.loadFile(
      path.join(__dirname, "../renderer/index.html")
    );
  }
  
  auth = new SpotifyAuth(win);
  auth.start();
}

app.whenReady().then(createWindow);