"""
model_manager.py — LyraSync
Manages download-on-first-launch for all three ML models:
  - Demucs   htdemucs        (~80 MB)
  - faster-whisper base.en   (~145 MB)
  - (wav2vec2 removed — sentence-level alignment no longer needs it)

Models are stored in the platform-appropriate config directory.
A model_versions.json file tracks installed versions so upgrades
can be detected in future releases.

SSE progress stream:
  Each event is a JSON object:
    { "model": "demucs", "pct": 42, "status": "downloading" }
    { "model": "demucs", "pct": 100, "status": "ready" }
    { "model": "all", "pct": 100, "status": "ready" }

  Status values: "downloading" | "ready" | "already_ready" | "error"

Usage (standalone check):
    from model_manager import models_ready, ensure_models

    if not models_ready():
        for event in ensure_models():
            print(event)

Usage (in FastAPI — see app.py):
    from fastapi.responses import StreamingResponse
    from model_manager import ensure_models_sse

    @app.get("/download-progress")
    async def download_progress():
        return StreamingResponse(
            ensure_models_sse(),
            media_type="text/event-stream",
        )
"""

import json
import logging
import os
import platform
from typing import Generator

logger = logging.getLogger(__name__)

# ── Model registry ────────────────────────────────────────────────────────────

# Bump these strings to force a re-download on next launch
MODEL_VERSIONS = {
    "demucs":         "htdemucs-v4",
    "faster-whisper": "base.en-ct2-v1",
}

# Display names for progress events
MODEL_LABELS = {
    "demucs":         "Demucs (vocal separation)",
    "faster-whisper": "Whisper (transcription)",
}


# ── Path helpers ──────────────────────────────────────────────────────────────

def _base_dir() -> str:
    """Platform-appropriate root for all LyraSync data."""
    system = platform.system()
    if system == "Windows":
        return os.path.join(os.environ.get("APPDATA", ""), "LyraSync")
    if system == "Darwin":
        return os.path.expanduser("~/Library/Application Support/LyraSync")
    return os.path.expanduser("~/.config/LyraSync")


def model_dir(name: str) -> str:
    """Return (and create) the directory for a specific model."""
    path = os.path.join(_base_dir(), "models", name)
    os.makedirs(path, exist_ok=True)
    return path


def _versions_path() -> str:
    base = os.path.join(_base_dir(), "models")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, "model_versions.json")


def _load_installed_versions() -> dict:
    path = _versions_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_installed_version(name: str, version: str) -> None:
    installed = _load_installed_versions()
    installed[name] = version
    with open(_versions_path(), "w") as f:
        json.dump(installed, f, indent=2)


# ── Per-model ready checks ────────────────────────────────────────────────────

def _lock_path(name: str) -> str:
    """Path to the in-progress download marker for a model."""
    base = os.path.join(_base_dir(), "models")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"{name}.downloading")


def _acquire_lock(name: str) -> None:
    """
    Write a lock file before starting a download.
    If this file exists on next launch, the previous download was
    interrupted and the partial files will be cleaned up.
    """
    with open(_lock_path(name), "w") as f:
        f.write(str(os.getpid()))


def _release_lock(name: str) -> None:
    """Remove the lock file after a successful download."""
    path = _lock_path(name)
    if os.path.exists(path):
        os.remove(path)


def _is_interrupted(name: str) -> bool:
    """Return True if a lock file exists — previous download was cut short."""
    return os.path.exists(_lock_path(name))


def _clean_partial(name: str) -> None:
    """
    Wipe any partial download files for a model so the next
    download starts from a clean state.
    """
    # Remove model directory contents
    mdir = model_dir(name)
    for fname in os.listdir(mdir):
        fpath = os.path.join(mdir, fname)
        try:
            os.remove(fpath)
        except OSError:
            pass
    logger.info(f"{name}: cleaned up partial download")

    # Remove from installed versions so ready check fails cleanly
    installed = _load_installed_versions()
    installed.pop(name, None)
    with open(_versions_path(), "w") as f:
        json.dump(installed, f, indent=2)

    # Remove the lock file itself
    _release_lock(name)


def _demucs_ready() -> bool:
    """
    Demucs stores its weights under torch hub cache, but we gate on
    our own version file so we control upgrade timing.
    Returns False if an interrupted download lock exists.
    """
    if _is_interrupted("demucs"):
        return False
    installed = _load_installed_versions()
    return installed.get("demucs") == MODEL_VERSIONS["demucs"]


def _whisper_ready() -> bool:
    """
    faster-whisper models are downloaded into model_dir("faster-whisper").
    The directory contains model.bin when ready.
    Returns False if an interrupted download lock exists.
    """
    if _is_interrupted("faster-whisper"):
        return False
    installed = _load_installed_versions()
    if installed.get("faster-whisper") != MODEL_VERSIONS["faster-whisper"]:
        return False
    mdir = model_dir("faster-whisper")
    return os.path.exists(os.path.join(mdir, "model.bin"))


READY_CHECKS = {
    "demucs":         _demucs_ready,
    "faster-whisper": _whisper_ready,
}


def models_ready() -> bool:
    """Return True only if every model is downloaded and version-matched."""
    return all(check() for check in READY_CHECKS.values())


# ── Per-model downloaders ─────────────────────────────────────────────────────

def _download_demucs(on_pct: callable) -> None:
    """
    Download htdemucs via Demucs's own pretrained loader.
    Demucs manages its own cache under torch hub — we just trigger
    the load and record the version when it completes.
    """
    on_pct(5)
    from demucs.pretrained import get_model
    on_pct(10)
    # get_model downloads weights on first call if not cached
    get_model("htdemucs")
    on_pct(95)
    _save_installed_version("demucs", MODEL_VERSIONS["demucs"])
    on_pct(100)


def _download_whisper(on_pct: callable) -> None:
    """
    Download faster-whisper base.en into model_dir("faster-whisper").
    faster-whisper uses ctranslate2 format — WhisperModel handles the
    download automatically when given a download_root.
    We hook into the directory size to approximate progress since
    faster-whisper doesn't expose a download callback.
    """
    import threading
    import time

    dest = model_dir("faster-whisper")

    # Known approximate final size of base.en in CT2 format (~145 MB)
    EXPECTED_BYTES = 145 * 1024 * 1024

    download_done = threading.Event()

    def _size_watcher():
        """Poll directory size and emit progress while download runs."""
        while not download_done.is_set():
            try:
                total = sum(
                    os.path.getsize(os.path.join(dest, f))
                    for f in os.listdir(dest)
                    if os.path.isfile(os.path.join(dest, f))
                )
                pct = min(int(total / EXPECTED_BYTES * 90), 90)
                on_pct(max(pct, 5))
            except OSError:
                pass
            time.sleep(0.5)

    watcher = threading.Thread(target=_size_watcher, daemon=True)
    watcher.start()

    try:
        from faster_whisper import WhisperModel
        # Triggers download if model.bin not present
        WhisperModel(
            "base.en",
            device        = "cpu",
            compute_type  = "int8",
            download_root = dest,
        )
    finally:
        download_done.set()
        watcher.join(timeout=2)

    _save_installed_version("faster-whisper", MODEL_VERSIONS["faster-whisper"])
    on_pct(100)


DOWNLOADERS = {
    "demucs":         _download_demucs,
    "faster-whisper": _download_whisper,
}


# ── SSE event builder ─────────────────────────────────────────────────────────

def _sse(data: dict) -> str:
    """Format a dict as a single SSE data line."""
    return f"data: {json.dumps(data)}\n\n"


# ── Core generator ────────────────────────────────────────────────────────────

def ensure_models() -> Generator[str, None, None]:
    """
    Check each model and download any that are missing or outdated.
    Yields SSE-formatted strings suitable for a StreamingResponse.

    Electron should open GET /download-progress on launch and consume
    this stream until it receives the final { "model": "all", "status": "ready" }
    event, at which point the app is fully operational.

    Example stream:
        data: {"model": "demucs", "pct": 0, "status": "downloading", "label": "Demucs (vocal separation)"}
        data: {"model": "demucs", "pct": 45, "status": "downloading", ...}
        data: {"model": "demucs", "pct": 100, "status": "ready", ...}
        data: {"model": "faster-whisper", "pct": 0, "status": "downloading", ...}
        ...
        data: {"model": "all", "pct": 100, "status": "ready"}
    """
    for name in MODEL_VERSIONS:
        label        = MODEL_LABELS[name]
        ready_check  = READY_CHECKS[name]
        downloader   = DOWNLOADERS[name]

        if ready_check():
            logger.info(f"{name}: already ready")
            yield _sse({
                "model":  name,
                "pct":    100,
                "status": "already_ready",
                "label":  label,
            })
            continue

        # Clean up any partial files from a previous interrupted download
        if _is_interrupted(name):
            logger.warning(f"{name}: previous download was interrupted — cleaning up")
            _clean_partial(name)

        logger.info(f"{name}: downloading…")
        yield _sse({
            "model":  name,
            "pct":    0,
            "status": "downloading",
            "label":  label,
        })

        last_pct     = [0]
        _pct_events: list[str] = []

        def on_pct(pct: int, _name=name, _label=label) -> None:
            if pct > last_pct[0]:
                last_pct[0] = pct
                _pct_events.append(_sse({
                    "model":  _name,
                    "pct":    pct,
                    "status": "downloading",
                    "label":  _label,
                }))

        try:
            _acquire_lock(name)
            downloader(on_pct)
            _release_lock(name)        # only reached on clean completion
            yield from _pct_events
            logger.info(f"{name}: ready")
            yield _sse({
                "model":  name,
                "pct":    100,
                "status": "ready",
                "label":  label,
            })

        except Exception as e:
            # Lock intentionally left in place — signals interrupted download
            # to the next launch, which will clean up and retry.
            logger.error(f"{name}: download failed — {e}")
            yield _sse({
                "model":   name,
                "pct":     last_pct[0],
                "status":  "error",
                "label":   label,
                "message": str(e),
            })
            continue

    # Final all-clear event
    all_ready = models_ready()
    yield _sse({
        "model":  "all",
        "pct":    100 if all_ready else 0,
        "status": "ready" if all_ready else "error",
    })


async def ensure_models_sse() -> Generator[str, None, None]:
    """
    Async wrapper around ensure_models() for FastAPI StreamingResponse.

    FastAPI requires an async generator for StreamingResponse — this
    wraps the synchronous ensure_models() generator so it can be used
    directly as the response body.
    """
    for event in ensure_models():
        yield event


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if "--check" in sys.argv:
        installed = _load_installed_versions()
        print("Installed versions:", json.dumps(installed, indent=2))
        print("Models ready:", models_ready())
        sys.exit(0)

    print("Ensuring all models are downloaded…\n")
    for event in ensure_models():
        data = json.loads(event.replace("data: ", "").strip())
        model  = data["model"]
        pct    = data["pct"]
        status = data["status"]
        label  = data.get("label", model)
        if model == "all":
            print(f"\nAll models ready: {status == 'ready'}")
        else:
            bar = "#" * (pct // 5) + "." * (20 - pct // 5)
            print(f"\r  {label:<35} [{bar}] {pct:3d}%  {status}    ", end="", flush=True)
            if status in ("ready", "already_ready", "error"):
                print()