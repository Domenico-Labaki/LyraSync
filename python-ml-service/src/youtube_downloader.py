"""
youtube_downloader.py — LyraSync
Downloads audio from a YouTube URL via yt-dlp, converts it to
16kHz mono WAV (ready for Wav2Vec2), and stores it in a temp file
that is automatically cleaned up after use.

Requires ffmpeg to be installed and on PATH.

Usage:
    from youtube_downloader import download_audio

    with download_audio(url) as wav_path:
        # wav_path is a 16kHz mono WAV file
        run_alignment(wav_path)
    # file is deleted here automatically
"""

import os
import tempfile
import logging
from contextlib import contextmanager
from typing import Generator

import yt_dlp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Audio quality passed to yt-dlp (best available source before conversion)
_PREFERRED_QUALITY = "0"  # 0 = best

# Target sample rate expected by Wav2Vec2
_TARGET_SAMPLE_RATE = 16000

# Max download duration in seconds — safety guard against full albums/mixes
_MAX_DURATION_SEC = 60 * 15  # 15 minutes


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_ydl_opts(output_path: str) -> dict:
    """
    Build yt-dlp options to download and convert audio to 16kHz mono WAV.
    ffmpeg is used as the postprocessor for format conversion.

    Args:
        output_path: Full path (without extension) for the output file.
                     yt-dlp will append the correct extension.
    """
    return {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "noplaylist": True,

        # Convert to WAV via ffmpeg postprocessor
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": _PREFERRED_QUALITY,
            }
        ],

        # Resample to 16kHz mono via ffmpeg postprocessor args
        "postprocessor_args": {
            "FFmpegExtractAudio": [
                "-ar", str(_TARGET_SAMPLE_RATE),   # sample rate
                "-ac", "1",                          # mono
            ]
        },

        # Safety: skip anything longer than the max duration
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {_MAX_DURATION_SEC}"
        ),
    }


def _find_output_file(base_path: str) -> str:
    """
    yt-dlp appends extensions itself. Locate the actual output file
    by checking for the expected .wav output next to the base path.

    Args:
        base_path: The outtmpl path passed to yt-dlp (without extension).

    Returns:
        Full path to the .wav file.

    Raises:
        FileNotFoundError: If the expected output file is not found.
    """
    wav_path = base_path + ".wav"
    if os.path.exists(wav_path):
        return wav_path

    # Fallback: scan the temp directory for any .wav with matching stem
    directory = os.path.dirname(base_path)
    stem = os.path.basename(base_path)
    for fname in os.listdir(directory):
        if fname.startswith(stem) and fname.endswith(".wav"):
            return os.path.join(directory, fname)

    raise FileNotFoundError(
        f"Expected WAV output not found at '{wav_path}'. "
        "Make sure ffmpeg is installed and on PATH."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@contextmanager
def download_audio(url: str) -> Generator[str, None, None]:
    """
    Context manager that downloads a YouTube URL as a 16kHz mono WAV,
    yields the path to the temp file, then deletes it on exit.

    Args:
        url: A YouTube video URL (from youtube_search.find_youtube_url).

    Yields:
        Path to a temporary 16kHz mono WAV file.

    Raises:
        yt_dlp.utils.DownloadError: If download or conversion fails.
        FileNotFoundError: If the converted WAV file can't be located.
        RuntimeError: If the track exceeds the max duration limit.

    Example:
        with download_audio("https://youtube.com/watch?v=...") as wav_path:
            result = run_alignment(wav_path, lyrics)
    """
    tmp_dir = tempfile.mkdtemp(prefix="lyrasync_")
    # Use a fixed stem; yt-dlp will append .wav after conversion
    base_path = os.path.join(tmp_dir, "audio")
    wav_path: str | None = None

    try:
        logger.info(f"Downloading audio from: {url}")
        ydl_opts = _build_ydl_opts(base_path)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            duration = info.get("duration")
            title = info.get("title", "unknown")

            if duration and duration > _MAX_DURATION_SEC:
                raise RuntimeError(
                    f"Track '{title}' is {duration}s, exceeds max allowed "
                    f"{_MAX_DURATION_SEC}s. Skipping."
                )

            logger.info(f"Downloaded: '{title}' ({duration}s)")

        wav_path = _find_output_file(base_path)
        logger.info(f"WAV ready at: {wav_path}")

        yield wav_path

    finally:
        # Always clean up the temp file and directory
        if wav_path and os.path.exists(wav_path):
            os.remove(wav_path)
            logger.debug(f"Deleted temp file: {wav_path}")

        # Remove any leftover files in the temp dir (e.g. intermediate formats)
        for fname in os.listdir(tmp_dir):
            fpath = os.path.join(tmp_dir, fname)
            try:
                os.remove(fpath)
            except OSError:
                pass

        try:
            os.rmdir(tmp_dir)
            logger.debug(f"Deleted temp dir: {tmp_dir}")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI — quick manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    url = sys.argv[1] if len(sys.argv) > 1 else None

    if not url:
        # Use youtube_search to find one automatically
        sys.path.insert(0, os.path.dirname(__file__))
        from youtube_search import find_youtube_url

        title  = sys.argv[1] if len(sys.argv) > 2 else "Blinding Lights"
        artist = sys.argv[2] if len(sys.argv) > 3 else "The Weeknd"

        print(f"Searching for '{title}' by '{artist}'...")
        url = find_youtube_url(title=title, artist=artist)

        if not url:
            print("❌ No URL found.")
            sys.exit(1)

        print(f"Found: {url}")

    print(f"Downloading: {url}")
    try:
        with download_audio(url) as wav_path:
            size_mb = os.path.getsize(wav_path) / (1024 * 1024)
            print(f"✅ WAV ready: {wav_path} ({size_mb:.1f} MB)")
            input("   [Press Enter to delete and exit]")
        print("🗑️  Temp file deleted.")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)