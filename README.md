![Banner Logo Image](banner.png)

# LyraSync 🎵

LyraSync is a cross-platform desktop app that connects to your Spotify account and displays the lyrics of the music you are currently playing in a clean, non-invasive interface designed for focus and flow.

Built with Electron and React, LyraSync lets you follow along with lyrics while you work, without pulling you out of your concentration.

---

## Download

Download the [latest stable release](https://github.com/Domenico-Labaki/LyraSync/releases/tag/Stable) of LyraSync for Windows.

---

## Features

### 🎧 Spotify Integration

- Securely connect your Spotify account via OAuth 2.0.
- Detect the song you are currently playing in real time.
- Automatically update track and playback state.

### 🎼 Lyrics Display

- Load **synced lyrics** when available.
- Fallback to **unsynced lyrics** when synced timing data is not available.
- Real-time lyric highlighting for supported tracks.

### 🧠 Focus-First Design

- Minimal, distraction-free UI that blends into your workflow.
- **Focus Mode** hides non-essential UI elements.
- Designed to stay present without demanding attention.

### ✨ User Experience

- Beautiful, modern UI inspired by music-first platforms.
- Smooth transitions and subtle animations.
- Always-on-top friendly without being intrusive.

### 🔐 Secure Authentication

- OAuth 2.0 authentication handled via a local Express server.
- Tokens managed securely within the Electron main process.
- No credentials exposed to the renderer.

---

## Tech Stack

### Frontend

- React
- TypeScript
- Custom CSS (modern, minimal aesthetic)

### Desktop & Backend

- Electron
- Node.js
- Express (local OAuth callback handling)
- IPC for renderer ↔ main process communication

### Tooling & Packaging

- Electron Forge
- Squirrel (Windows installer)
- Vite

---

## Architecture Overview

React Renderer
│
│ IPC
▼
Electron Main Process
│
│ OAuth callbacks
▼
Local Express Server

This architecture allows LyraSync to behave like a native desktop application while maintaining a clean and secure separation of concerns.

---

## Lyrics API

Lyrics are sourced from free, open APIs and are never stored server-side.

[LRCLIB]() is used as the main provider, with [lyrics.ovh](https://lyricsovh.docs.apiary.io/#) used as a fallback option.

---

© 2026 Domenico Labaki
