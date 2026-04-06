"""
app.py — LyraSync Python ML service
FastAPI entrypoint. Spawned by Electron on launch.

Endpoints:
  GET  /status             — ffmpeg check, model readiness, cache stats
  GET  /download-progress  — SSE stream for model downloads (consumed by modelManager.ts)
  POST /align              — run alignment pipeline, returns sentence timestamps
  POST /cache/clear        — wipe all cached alignments
  DELETE /cache/{track_id} — delete a single cache entry

Run locally:
  uvicorn app:app --port 8765 --reload
"""

import logging
import os
import sys

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# ── Local imports ─────────────────────────────────────────────────────────────

sys.path.insert(0, os.path.dirname(__file__))

from ffmpeg_check import require_ffmpeg, FFmpegStatus
from model_manager import models_ready, ensure_models_sse, model_dir
from cache import cache_exists, read_cache, write_cache, delete_cache, clear_all_cache, cache_info
from align import align_track, AlignmentResult
from youtube_search import find_youtube_url
from youtube_downloader import download_audio

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt = "%H:%M:%S",
)
logger = logging.getLogger("app")

# ── Startup ───────────────────────────────────────────────────────────────────

# Run ffmpeg check once at startup — result cached here for /status
_ffmpeg_status: Optional[FFmpegStatus] = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    global _ffmpeg_status
    logger.info("LyraSync ML service starting…")
    _ffmpeg_status = require_ffmpeg()
    if not _ffmpeg_status.ok:
        logger.warning("ffmpeg not found — downloads will fail until installed")
    logger.info("Service ready")
    yield
    logger.info("LyraSync ML service shutting down")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title    = "LyraSync ML Service",
    version  = "1.0.0",
    lifespan = lifespan,
)

# Allow localhost origins — Electron renderer + dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins  = ["http://localhost:5173", "http://localhost:3000"],
    allow_methods  = ["GET", "POST", "DELETE"],
    allow_headers  = ["*"],
)

# ── Request / response models ─────────────────────────────────────────────────

class AlignRequest(BaseModel):
    title:        str
    artist:       str
    duration_sec: Optional[int]  = None
    lyrics:       str
    lyrics_type:  str            = "plain"   # "plain" | "synced"
    track_id:     str


class AlignResponse(BaseModel):
    sentences:     list[dict]
    used_fallback: bool
    duration_sec:  float
    cached:        bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/status")
def get_status() -> dict:
    """
    Called by Electron on launch to check service readiness.
    Returns ffmpeg status, model readiness, and cache stats.
    """
    return {
        "ffmpeg":       _ffmpeg_status.to_dict() if _ffmpeg_status else {"ok": False},
        "models_ready": models_ready(),
        "cache":        cache_info(),
    }


@app.get("/download-progress")
async def download_progress() -> StreamingResponse:
    """
    SSE stream consumed by modelManager.ts in the Electron main process.
    Streams model download progress events until all models are ready.

    Each event: data: { model, pct, status, label? }\n\n
    Final event: data: { model: "all", pct: 100, status: "ready" }\n\n
    """
    return StreamingResponse(
        ensure_models_sse(),
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind proxy
        },
    )


@app.post("/align", response_model=AlignResponse)
async def align(req: AlignRequest) -> AlignResponse:
    """
    Main alignment endpoint.

    Flow:
      1. If lyrics_type is "synced", Electron already has timestamps —
         this endpoint should not be called, but we handle it gracefully.
      2. Check alignment cache — return instantly if hit.
      3. Search YouTube for the track URL.
      4. Download audio as 16 kHz mono WAV (temp file).
      5. Run Demucs → faster-whisper → fuzzy matcher.
      6. Write result to cache.
      7. Return sentence timestamps.
    """
    # Guard: ffmpeg required for audio download
    if _ffmpeg_status and not _ffmpeg_status.ok:
        raise HTTPException(
            status_code = 503,
            detail      = {
                "error":   "ffmpeg_missing",
                "message": "ffmpeg is not installed.",
                "install": _ffmpeg_status.to_dict().get("install"),
            },
        )

    # Guard: models must be ready
    if not models_ready():
        raise HTTPException(
            status_code = 503,
            detail      = {
                "error":   "models_not_ready",
                "message": "Models are still downloading. Please wait.",
            },
        )

    # Guard: synced lyrics should never reach here
    if req.lyrics_type == "synced":
        raise HTTPException(
            status_code = 400,
            detail      = {
                "error":   "synced_lyrics",
                "message": "Synced lyrics already have timestamps — alignment not needed.",
            },
        )

    # ── Cache check ───────────────────────────────────────────────────────────
    if cache_exists(req.track_id):
        cached = read_cache(req.track_id)
        if cached:
            logger.info(f"Cache hit: {req.track_id}")
            return AlignResponse(
                sentences     = cached["sentences"],
                used_fallback = cached.get("used_fallback", False),
                duration_sec  = cached.get("duration_sec", 0.0),
                cached        = True,
            )

    # ── YouTube search + download + align ─────────────────────────────────────
    logger.info(f"Aligning: {req.artist} — {req.title}")

    # Find YouTube URL
    url = find_youtube_url(
        title        = req.title,
        artist       = req.artist,
        duration_sec = req.duration_sec,
    )
    if not url:
        raise HTTPException(
            status_code = 404,
            detail      = {
                "error":   "track_not_found",
                "message": f"Could not find '{req.title}' by '{req.artist}' on YouTube.",
            },
        )

    logger.info(f"Found URL: {url}")

    # Download audio and run alignment pipeline
    try:
        with download_audio(url) as wav_path:
            result: AlignmentResult = align_track(
                wav_path    = wav_path,
                lyrics      = req.lyrics,
                on_progress = lambda stage, pct: logger.info(f"  [{pct:3d}%] {stage}"),
            )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail={"error": "download_failed", "message": str(e)})
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail={"error": "alignment_failed", "message": str(e)})
    except Exception as e:
        logger.exception(f"Unexpected alignment error: {e}")
        raise HTTPException(status_code=500, detail={"error": "internal_error", "message": str(e)})

    # ── Cache write ───────────────────────────────────────────────────────────
    write_cache(req.track_id, result.to_dict())

    return AlignResponse(
        sentences     = result.sentences,
        used_fallback = result.used_fallback,
        duration_sec  = result.duration_sec,
        cached        = False,
    )


@app.delete("/cache/{track_id}")
def delete_track_cache(track_id: str) -> dict:
    """Delete the cached alignment for a single track."""
    deleted = delete_cache(track_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"deleted": True, "track_id": track_id}


@app.post("/cache/clear")
def clear_cache() -> dict:
    """Wipe all cached alignments. Exposed for a 'Clear cache' settings button."""
    n = clear_all_cache()
    return {"deleted": n}


@app.post("/shutdown")
async def shutdown() -> dict:
    """
    Graceful shutdown endpoint called by Electron on close.
    Logs shutdown request and initiates service termination.
    """
    logger.info("Shutdown request received from Electron")
    import asyncio
    # Schedule shutdown on next event loop iteration
    asyncio.get_event_loop().call_soon(lambda: os._exit(0))
    return {"status": "shutting_down"}


# ── Dev entry ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8765, reload=False)