"""
ffmpeg_check.py — LyraSync
Detects whether ffmpeg is installed and available on PATH.
Called once at Python service startup — result is returned to Electron
so the frontend can show an install prompt if needed.

Usage:
    from ffmpeg_check import check_ffmpeg, FFmpegStatus

    status = check_ffmpeg()
    if not status.ok:
        # Send status.to_dict() to Electron → show install prompt
        ...
"""

import shutil
import subprocess
import sys
import platform
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Install instructions per platform
# ---------------------------------------------------------------------------

_INSTALL_INSTRUCTIONS: dict[str, dict] = {
    "windows": {
        "command": "winget install ffmpeg",
        "guide_url": "https://www.gyan.dev/ffmpeg/builds/",
        "note": "After installing, restart LyraSync.",
    },
    "darwin": {
        "command": "brew install ffmpeg",
        "guide_url": "https://ffmpeg.org/download.html#build-mac",
        "note": "Requires Homebrew. After installing, restart LyraSync.",
    },
    "linux": {
        "command": "sudo apt install ffmpeg",
        "guide_url": "https://ffmpeg.org/download.html#build-linux",
        "note": "Command may vary by distro (apt / dnf / pacman). After installing, restart LyraSync.",
    },
}


def _get_platform() -> str:
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"
    return "linux"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FFmpegStatus:
    ok: bool
    version: Optional[str] = None       # e.g. "6.1.1" if found
    path: Optional[str] = None          # full path to binary if found
    error: Optional[str] = None         # human-readable error if not found
    install_command: Optional[str] = None
    install_guide_url: Optional[str] = None
    install_note: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to dict for JSON response to Electron."""
        return {
            "ok": self.ok,
            "version": self.version,
            "path": self.path,
            "error": self.error,
            "install": {
                "command": self.install_command,
                "guide_url": self.install_guide_url,
                "note": self.install_note,
            } if not self.ok else None,
        }


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------

def check_ffmpeg() -> FFmpegStatus:
    """
    Check whether ffmpeg is installed and on PATH.

    Returns:
        FFmpegStatus with ok=True and version/path if found,
        or ok=False with install instructions if not.
    """
    plat = _get_platform()
    instructions = _INSTALL_INSTRUCTIONS[plat]

    # Step 1: Check if binary exists on PATH
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return FFmpegStatus(
            ok=False,
            error="ffmpeg not found on PATH.",
            install_command=instructions["command"],
            install_guide_url=instructions["guide_url"],
            install_note=instructions["note"],
        )

    # Step 2: Try running ffmpeg -version to confirm it's functional
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # Parse version string from first line: "ffmpeg version 6.1.1 ..."
        first_line = result.stdout.splitlines()[0] if result.stdout else ""
        version = None
        if "version" in first_line:
            parts = first_line.split()
            try:
                version = parts[parts.index("version") + 1]
            except (ValueError, IndexError):
                version = "unknown"

        return FFmpegStatus(
            ok=True,
            version=version,
            path=ffmpeg_path,
        )

    except FileNotFoundError:
        return FFmpegStatus(
            ok=False,
            error="ffmpeg binary found on PATH but could not be executed.",
            install_command=instructions["command"],
            install_guide_url=instructions["guide_url"],
            install_note=instructions["note"],
        )
    except subprocess.TimeoutExpired:
        return FFmpegStatus(
            ok=False,
            error="ffmpeg check timed out.",
            install_command=instructions["command"],
            install_guide_url=instructions["guide_url"],
            install_note=instructions["note"],
        )


# ---------------------------------------------------------------------------
# Startup guard — call this once in app.py (FastAPI startup event)
# ---------------------------------------------------------------------------

def require_ffmpeg() -> FFmpegStatus:
    """
    Run the ffmpeg check and log the result.
    Returns the status — caller (app.py) decides whether to abort or continue.
    Does NOT raise — lets the FastAPI app start so Electron can query /status.
    """
    import logging
    logger = logging.getLogger(__name__)

    status = check_ffmpeg()

    if status.ok:
        logger.info(f"ffmpeg found: version={status.version}, path={status.path}")
    else:
        logger.warning(f"ffmpeg not available: {status.error}")

    return status


# ---------------------------------------------------------------------------
# CLI — quick manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    status = check_ffmpeg()
    print(json.dumps(status.to_dict(), indent=2))
    sys.exit(0 if status.ok else 1)