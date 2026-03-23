"""
cache.py — LyraSync
Read/write alignment results to a per-track JSON cache.

Cache location (platform-appropriate):
  Windows : %APPDATA%\\LyraSync\\cache\\{track_id}.json
  macOS   : ~/Library/Application Support/LyraSync/cache/{track_id}.json
  Linux   : ~/.config/LyraSync/cache/{track_id}.json

Each file contains the full AlignmentResult dict plus a timestamp
of when it was written, so stale entries can be detected if needed.

Usage:
    from cache import read_cache, write_cache, cache_exists

    if cache_exists(track_id):
        result = read_cache(track_id)   # returns dict or None
    else:
        result = run_alignment(...)
        write_cache(track_id, result.to_dict())
"""

import hashlib
import json
import logging
import os
import platform
import re
import time

logger = logging.getLogger(__name__)


# ── Path helpers ──────────────────────────────────────────────────────────────

def _cache_dir() -> str:
    """Return (and create) the platform-appropriate cache directory."""
    system = platform.system()
    if system == "Windows":
        base = os.path.join(os.environ.get("APPDATA", ""), "LyraSync")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/LyraSync")
    else:
        base = os.path.expanduser("~/.config/LyraSync")
    path = os.path.join(base, "cache")
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_key(track_id: str) -> str:
    """
    Produce a safe filename from any track_id string.

    Spotify IDs (e.g. "4uLU6hMCjMI75M1A2tKUQC") are already filename-safe.
    For anything else (URLs, freeform strings), we hash to a fixed-length hex.
    Only allow alphanumeric, hyphen, underscore — anything else gets hashed.
    """
    if re.fullmatch(r"[a-zA-Z0-9_\-]{1,128}", track_id):
        return track_id
    return hashlib.sha256(track_id.encode()).hexdigest()[:40]


def _cache_path(track_id: str) -> str:
    return os.path.join(_cache_dir(), f"{_sanitize_key(track_id)}.json")


# ── Public API ────────────────────────────────────────────────────────────────

def cache_exists(track_id: str) -> bool:
    """Return True if a cache entry exists for this track."""
    return os.path.exists(_cache_path(track_id))


def read_cache(track_id: str) -> dict | None:
    """
    Load and return the cached alignment result for a track.

    Returns the stored dict (same shape as AlignmentResult.to_dict(),
    plus a "cached_at" timestamp), or None if the file is missing
    or corrupt.
    """
    path = _cache_path(track_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.info(f"Cache hit: {track_id} ({path})")
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Cache read failed for {track_id}: {e} — will realign")
        return None


def write_cache(track_id: str, result: dict) -> None:
    """
    Persist an alignment result dict to the cache.

    Adds a "cached_at" Unix timestamp to the stored payload so
    future tooling can detect and expire stale entries if needed.
    Writes atomically via a temp file to avoid corrupt cache files
    if the process is killed mid-write.
    """
    path     = _cache_path(track_id)
    tmp_path = path + ".tmp"

    payload = {**result, "cached_at": time.time()}

    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)   # atomic on all platforms
        logger.info(f"Cache written: {track_id} ({path})")
    except OSError as e:
        logger.error(f"Cache write failed for {track_id}: {e}")
        # Clean up temp file if it was created
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def delete_cache(track_id: str) -> bool:
    """
    Delete the cache entry for a track.
    Returns True if a file was deleted, False if it didn't exist.
    """
    path = _cache_path(track_id)
    if not os.path.exists(path):
        return False
    try:
        os.remove(path)
        logger.info(f"Cache deleted: {track_id}")
        return True
    except OSError as e:
        logger.error(f"Cache delete failed for {track_id}: {e}")
        return False


def clear_all_cache() -> int:
    """
    Delete all cache entries. Returns the number of files deleted.
    Useful for a "clear cache" settings button in Electron.
    """
    cache = _cache_dir()
    deleted = 0
    for fname in os.listdir(cache):
        if fname.endswith(".json"):
            try:
                os.remove(os.path.join(cache, fname))
                deleted += 1
            except OSError:
                pass
    logger.info(f"Cache cleared: {deleted} entries deleted")
    return deleted


def cache_info() -> dict:
    """
    Return metadata about the current cache state.
    Used by GET /status to report cache stats to Electron.
    """
    cache = _cache_dir()
    files = [f for f in os.listdir(cache) if f.endswith(".json")]
    total_bytes = sum(
        os.path.getsize(os.path.join(cache, f))
        for f in files
    )
    return {
        "entries":     len(files),
        "size_mb":     round(total_bytes / (1024 * 1024), 2),
        "cache_dir":   cache,
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cmd = sys.argv[1] if len(sys.argv) > 1 else "--info"

    if cmd == "--info":
        info = cache_info()
        print(json.dumps(info, indent=2))

    elif cmd == "--exists" and len(sys.argv) > 2:
        tid = sys.argv[2]
        print(f"{tid}: {'exists' if cache_exists(tid) else 'not found'}")

    elif cmd == "--read" and len(sys.argv) > 2:
        tid  = sys.argv[2]
        data = read_cache(tid)
        print(json.dumps(data, indent=2) if data else f"No cache entry for {tid}")

    elif cmd == "--delete" and len(sys.argv) > 2:
        tid = sys.argv[2]
        ok  = delete_cache(tid)
        print(f"Deleted: {ok}")

    elif cmd == "--clear":
        n = clear_all_cache()
        print(f"Cleared {n} cache entries")

    else:
        print("Usage:")
        print("  python cache.py --info")
        print("  python cache.py --exists <track_id>")
        print("  python cache.py --read   <track_id>")
        print("  python cache.py --delete <track_id>")
        print("  python cache.py --clear")