![LyraSync Banner](banner.png)

# 🎵 LyraSync

[![Version](https://img.shields.io/badge/version-2.0.0-blue.svg)](https://github.com/Domenico-Labaki/LyraSync/releases) [![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE) [![Electron](https://img.shields.io/badge/Electron-41.0.0-47848F.svg)](https://electronjs.org/) [![React](https://img.shields.io/badge/React-19.2.3-61DAFB.svg)](https://reactjs.org/) [![Python](https://img.shields.io/badge/Python-3.8+-3776AB.svg)](https://python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-0.100.0-009688.svg)](https://fastapi.tiangolo.com/)

**LyraSync** is a desktop application that displays synchronized lyrics for your music playback in a clean, distraction-free interface. It seamlessly integrates with Spotify or works in guest mode with any media player, using advanced machine learning to align lyrics when official synced versions aren't available.

## ✨ Features

### 🎧 Multi-Source Media Integration

- **Spotify Integration**: Secure OAuth 2.0 authentication with real-time playback detection
- **Guest Mode**: Universal media player support via OS media controls
- **Automatic Detection**: Real-time track and playback state updates

### 🎼 Intelligent Lyrics Display

- **Synced Lyrics**: Real-time highlighting for officially timed lyrics
- **ML-Powered Alignment**: Advanced AI alignment for unsynced lyrics using:
  - Vocal source separation (Demucs)
  - Speech recognition (Whisper)
  - Semantic matching (Groq LLM)
- **Fallback Support**: Graceful degradation from synced → AI-aligned → plain text

### 🧠 Focus-First Design

- **Minimal UI**: Distraction-free interface that blends into your workflow
- **Focus Mode**: Hide non-essential elements for maximum concentration
- **Always-on-Top**: Non-intrusive overlay that stays visible without demanding attention
- **Smooth Animations**: Subtle transitions and modern design inspired by music platforms

### 🔧 Advanced Features

- **Lyrics Caching**: Intelligent caching system for alignment results
- **Model Management**: Automatic download and management of ML models
- **Progress Tracking**: Real-time progress for model downloads and alignment processing
- **Cross-Platform**: Native desktop experience on Windows, macOS, and Linux

## 🏗️ Architecture

LyraSync follows a **dual-mode architecture** with clean separation of concerns:

```
┌─────────────────┐    ┌──────────────────┐
│   React UI      │    │  Electron Main   │
│   (Renderer)    │◄──►│    Process       │
│                 │    │                  │
│ • Login Screen  │    │ • IPC Handlers   │
│ • Lyrics Display│    │ • Media Detection│
│ • Settings      │    │ • Python Service │
└─────────────────┘    └──────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌──────────────────┐
│  Python ML      │    │   OS Media       │
│   Service       │    │   Controls       │
│                 │    │                  │
│ • Vocal Sep.    │    │ • Universal       │
│ • Transcription │    │   Detection      │
│ • LLM Matching  │    │ • Playback State │
└─────────────────┘    └──────────────────┘
```

### Core Components

#### Electron Application (`electron-app/`)

- **Main Process**: Handles system integration, IPC, and Python service management
- **Renderer Process**: React-based UI with TypeScript
- **Authentication**: Secure OAuth flow with token management
- **Media Detection**: Unified interface for Spotify API and OS media controls

#### Python ML Service (`python-ml-service/`)

- **FastAPI Server**: RESTful API for alignment operations
- **Model Pipeline**: Three-stage ML processing for lyrics alignment
- **Caching System**: Efficient storage and retrieval of alignment results
- **Progress Streaming**: Server-sent events for real-time progress updates

## 🛠️ Tech Stack

### Frontend & Desktop

- **Electron**: Cross-platform desktop framework
- **React 19**: Modern UI framework with hooks
- **TypeScript**: Type-safe JavaScript development
- **Vite**: Fast build tool and dev server
- **Electron Forge**: Application packaging and distribution

### Backend & ML

- **Python**: Core language for ML processing
- **FastAPI**: High-performance async web framework
- **PyTorch**: Deep learning framework for audio processing
- **Whisper**: OpenAI's speech recognition model
- **Demucs**: Music source separation model
- **Groq API**: Large language model for semantic matching

### Key Dependencies

- **Media Detection**: `node-global-media-controls` for OS integration
- **Security**: `keytar` for secure token storage
- **HTTP Client**: `axios` for API communications
- **Audio Processing**: `torchaudio`, `soundfile` for audio I/O

## 📦 Installation

### Prerequisites

- **Node.js** 18+ and **npm**
- **Python** 3.8+ with **pip**
- **FFmpeg** (for audio processing)
- **Git** (for cloning the repository)

### Quick Start

1. **Clone the repository**

   ```bash
   git clone https://github.com/Domenico-Labaki/LyraSync.git
   cd LyraSync
   ```
2. **Setup Python ML Service**

   ```bash
   cd python-ml-service
   pip install -r requirements.txt
   # Set your Groq API key
   echo "GROQ_API_KEY=your_api_key_here" > .env
   ```
3. **Setup Electron Application**

   ```bash
   cd ../electron-app
   npm install
   ```
4. **Development**

   ```bash
   # Terminal 1: Start Python service
   cd python-ml-service/src
   uvicorn app:app --port 8765 --reload

   # Terminal 2: Start Electron app
   cd electron-app
   npm run dev
   ```
5. **Build for Production**

   ```bash
   cd electron-app
   npm run build
   npm run make
   ```

### Environment Setup

#### Spotify API (Optional)

Create a Spotify app at [Spotify Developer Dashboard](https://developer.spotify.com/dashboard):

1. Create a new app
2. Set redirect URI to `http://localhost:3000/callback`
3. Copy client ID and secret to `electron-app/.env`:
   ```
   SPOTIFY_CLIENT_ID=your_client_id
   SPOTIFY_CLIENT_SECRET=your_client_secret
   ```

#### Groq API (Required for ML Alignment)

Get an API key from [Groq Console](https://console.groq.com/):

```
GROQ_API_KEY=your_groq_api_key
```

## 🚀 Usage

### First Launch

1. **Choose Mode**: Select Spotify login or Guest Mode
2. **Model Download**: First run downloads required ML models (~225MB)
3. **Start Listening**: Play music and watch lyrics appear

### Interface Overview

- **Login Screen**: Choose between Spotify authentication or guest mode
- **Main Interface**: Clean lyrics display with album art
- **Focus Mode**: Toggle with eye icon for minimal distraction
- **Settings**: Access via hamburger menu

## 🔌 API Reference

### Python ML Service

The service runs on `http://localhost:8765` and provides the following endpoints:

#### `GET /status`

Returns service health and model readiness status.

**Response:**

```json
{
  "ffmpeg": {
    "ok": true,
    "version": "6.0"
  },
  "models": {
    "demucs": "ready",
    "faster-whisper": "ready"
  },
  "cache": {
    "entries": 15,
    "size_mb": 2.3
  }
}
```

#### `GET /download-progress`

Server-sent events stream for model download progress.

**Event Format:**

```json
{
  "model": "demucs",
  "pct": 75,
  "status": "downloading"
}
```

#### `POST /align`

Align lyrics to audio using ML pipeline.

**Request:**

```json
{
  "title": "Bohemian Rhapsody",
  "artist": "Queen",
  "duration_sec": 355,
  "lyrics": "Is this the real life?...",
  "lyrics_type": "plain",
  "track_id": "spotify:track:123456"
}
```

**Response:**

```json
{
  "sentences": [
    {
      "line": "Is this the real life?",
      "start": 0.0,
      "end": 3.2
    }
  ],
  "used_fallback": false,
  "duration_sec": 355.0,
  "cached": false
}
```

#### `POST /cache/clear`

Clear all cached alignments.

#### `DELETE /cache/{track_id}`

Delete cached alignment for specific track.

## 🤖 ML Pipeline Details

LyraSync uses a sophisticated three-stage pipeline for lyrics alignment:

### Stage 1: Vocal Separation

- **Model**: Demucs (htdemucs)
- **Purpose**: Isolate vocals from instrumental backing
- **Output**: Clean vocal audio track

### Stage 2: Speech Recognition

- **Model**: Faster-Whisper (base.en)
- **Purpose**: Transcribe vocals to text with timestamps
- **Output**: Time-aligned speech segments

### Stage 3: Semantic Matching

- **Model**: Groq LLM (mixtral-8x7b)
- **Purpose**: Map lyric lines to speech segments
- **Method**: Semantic understanding handles:
  - ASR transcription errors
  - Merged/split segments
  - Repeated sections (choruses)
  - Natural language variations

## 📁 Project Structure

```
LyraSync/
├── electron-app/                 # Electron desktop application
│   ├── src/
│   │   ├── main/                 # Main process (Node.js)
│   │   │   ├── main.ts           # Application entry point
│   │   │   ├── MediaSourceManager.ts # Unified media detection
│   │   │   ├── SpotifyAuth.ts    # OAuth authentication
│   │   │   ├── modelManager.ts   # Python service integration
│   │   │   └── ...               # Other main process modules
│   │   ├── renderer/             # Renderer process (React)
│   │   │   ├── App.tsx           # Main UI component
│   │   │   ├── components/       # React components
│   │   │   └── theme/            # Styling and colors
│   │   ├── preload/              # Preload scripts
│   │   └── types/                # TypeScript definitions
│   ├── package.json
│   └── forge.config.js           # Build configuration
├── python-ml-service/            # ML alignment service
│   ├── src/
│   │   ├── app.py                # FastAPI application
│   │   ├── align.py              # ML alignment pipeline
│   │   ├── model_manager.py      # Model download/management
│   │   ├── cache.py              # Alignment result caching
│   │   ├── youtube_downloader.py # Audio download utility
│   │   └── youtube_search.py     # YouTube search utility
│   └── requirements.txt          # Python dependencies
├── media/                        # Media assets
└── README.md                     # This file
```

---

**Made with ❤️ by [Domenico Labaki](https://github.com/Domenico-Labaki)**

*Follow along with your music, stay in the flow.*
