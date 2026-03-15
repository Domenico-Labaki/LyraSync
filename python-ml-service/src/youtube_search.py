"""
youtube_search.py — LyraSync
Searches YouTube Music (with YouTube fallback) for a track
given metadata from Spotify API or OS media controls.

Usage:
    from youtube_search import find_youtube_url
    url = find_youtube_url(title="Blinding Lights", artist="The Weeknd", duration_sec=200)
"""

import yt_dlp
import re
from typing import Optional


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# How many results to fetch and evaluate per search pass
_SEARCH_RESULTS = 5

# Penalty applied per second of duration mismatch when scoring candidates
_DURATION_PENALTY_PER_SEC = 0.5

# Score bonus for YouTube Music URLs (music.youtube.com)
_YT_MUSIC_BONUS = 10.0

# Score bonus when the uploader name contains the artist name
_ARTIST_MATCH_BONUS = 6.0

# Score bonus when the video title contains the track title
_TITLE_MATCH_BONUS = 4.0

# Score penalty for likely non-music results (live, cover, remix, karaoke, tutorial)
_NOISE_PENALTY = 8.0
_NOISE_KEYWORDS = ["live", "cover", "remix", "karaoke", "tutorial", "lesson", "reaction", "lyrics video"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase and strip punctuation for loose comparisons."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def _build_queries(title: str, artist: str) -> list[str]:
    """
    Returns an ordered list of search queries to try.
    yt-dlp only supports 'ytsearch:' natively — ytmsearch is not valid.
    We bias toward music results via query suffixes instead.
    """
    base = f"{artist} {title}"
    return [
        f"ytsearch{_SEARCH_RESULTS}:{base} official audio",
        f"ytsearch{_SEARCH_RESULTS}:{base} audio",
        f"ytsearch{_SEARCH_RESULTS}:{base}",
    ]


def _score_candidate(
    entry: dict,
    title: str,
    artist: str,
    duration_sec: Optional[int],
) -> float:
    """
    Score a single yt-dlp result entry. Higher = better match.
    Returns -inf if the entry is clearly unusable.
    """
    if not entry or entry.get("_type") == "playlist":
        return float("-inf")

    url = entry.get("webpage_url", "") or entry.get("url", "")
    video_title = entry.get("title", "")
    uploader = entry.get("uploader", "") or entry.get("channel", "")
    entry_duration = entry.get("duration")  # seconds, may be None

    score = 0.0

    # --- YouTube Music URL bonus ---
    if "music.youtube.com" in url:
        score += _YT_MUSIC_BONUS

    # --- Title match ---
    if _normalize(title) in _normalize(video_title):
        score += _TITLE_MATCH_BONUS

    # --- Artist match in uploader / channel name ---
    if _normalize(artist) in _normalize(uploader):
        score += _ARTIST_MATCH_BONUS

    # --- Duration match (if we have both values) ---
    if duration_sec and entry_duration:
        drift = abs(duration_sec - entry_duration)
        score -= drift * _DURATION_PENALTY_PER_SEC

    # --- Noise penalties ---
    combined = _normalize(video_title)
    for keyword in _NOISE_KEYWORDS:
        if keyword in combined:
            score -= _NOISE_PENALTY
            break  # one penalty max

    return score


def _extract_entries(ydl: yt_dlp.YoutubeDL, query: str) -> list[dict]:
    """Run a yt-dlp extract_info call and return a flat list of entries."""
    try:
        result = ydl.extract_info(query, download=False)
    except yt_dlp.utils.DownloadError:
        return []

    if not result:
        return []

    # Search results come back as a playlist-type dict with an 'entries' list
    if "entries" in result:
        return [e for e in result["entries"] if e]

    # Single result
    return [result]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_youtube_url(
    title: str,
    artist: str,
    duration_sec: Optional[int] = None,
) -> Optional[str]:
    """
    Search YouTube for the best matching URL.

    Args:
        title:        Track title (from Spotify or OS media controls).
        artist:       Artist name.
        duration_sec: Track duration in seconds (improves match accuracy).

    Returns:
        Best matching YouTube URL string, or None if nothing found.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,      # we need duration metadata
        "noplaylist": True,
        "default_search": "ytsearch",
    }

    queries = _build_queries(title, artist)

    best_url: Optional[str] = None
    best_score: float = float("-inf")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for query in queries:
            entries = _extract_entries(ydl, query)
            for entry in entries:
                score = _score_candidate(entry, title, artist, duration_sec)
                if score > best_score:
                    best_score = score
                    best_url = (
                        entry.get("webpage_url")
                        or entry.get("url")
                    )

            # Early exit if we have a strong title + artist match
            if best_score >= (_TITLE_MATCH_BONUS + _ARTIST_MATCH_BONUS):
                break

    return best_url


# ---------------------------------------------------------------------------
# CLI — quick manual test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) >= 3:
        t = sys.argv[1]
        a = sys.argv[2]
        d = int(sys.argv[3]) if len(sys.argv) > 3 else None
    else:
        # Default test case
        t, a, d = "Blinding Lights", "The Weeknd", 200

    print(f"Searching: '{t}' by '{a}'" + (f" (~{d}s)" if d else ""))
    url = find_youtube_url(title=t, artist=a, duration_sec=d)

    if url:
        print(f"✅ Best match: {url}")
    else:
        print("❌ No match found.")