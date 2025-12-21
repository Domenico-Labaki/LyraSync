import { app, BrowserWindow } from "electron";
import path from "path";
import { SpotifyAuth } from "./SpotifyAuth.js";

let win: BrowserWindow | null = null;
export var auth: SpotifyAuth;

function createWindow() {
  win = new BrowserWindow({
    width: 900,
    height: 180,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    resizable: false,
    hasShadow: false,
    webPreferences: {
      preload: path.join(__dirname, "../preload/preload.js")
    }
  });

  win.setIgnoreMouseEvents(true);

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