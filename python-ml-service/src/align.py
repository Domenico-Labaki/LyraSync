"""
align.py — LyraSync
Two-stage local ML alignment pipeline:
  1. Demucs        — vocal source separation (htdemucs)
  2. faster-whisper — ASR transcription (base.en)
  3. Fuzzy matcher  — maps whisper segments → lyric lines (no ML)

Output is sentence-level timestamps, one per lyric line:
  [ { "line": "I've been on my own...", "start": 4.2, "end": 7.8 } ]

Usage:
    from align import align_track, AlignmentResult

    def on_progress(stage: str, pct: int):
        print(f"[{pct}%] {stage}")

    result = align_track(
        wav_path    = "/tmp/audio.wav",
        lyrics      = "First line\nSecond line\nThird line",
        on_progress = on_progress,
    )

    for sentence in result.sentences:
        print(sentence["line"], sentence["start"], sentence["end"])
"""

import gc
import logging
import os
import platform
import re
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

import torch
import torchaudio
import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

WHISPER_MODEL_SIZE = "base.en"
DEMUCS_MODEL       = "htdemucs"
TARGET_SR          = 16_000   # Hz — whisper expects 16 kHz

# Minimum token-overlap ratio to accept a fuzzy match (0–1)
MATCH_THRESHOLD = 0.35


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class AlignmentResult:
    """
    sentences     — ordered list of { line, start, end, confidence }
    used_fallback — True if any lines needed interpolated timestamps
    duration_sec  — total audio duration in seconds
    """
    sentences:     list[dict]
    used_fallback: bool
    duration_sec:  float

    def to_dict(self) -> dict:
        return {
            "sentences":     self.sentences,
            "used_fallback": self.used_fallback,
            "duration_sec":  round(self.duration_sec, 3),
        }


# ── Progress helper ───────────────────────────────────────────────────────────

ProgressCallback = Callable[[str, int], None]   # (label, pct 0-100)


def _noop(_stage: str, _pct: int) -> None:
    pass


def _progress(cb: ProgressCallback, stage: str, pct: int) -> None:
    logger.info(f"[{pct:3d}%] {stage}")
    cb(stage, pct)


# ── Path helper ───────────────────────────────────────────────────────────────

def _model_dir(name: str) -> str:
    """Return the platform-appropriate model cache directory."""
    system = platform.system()
    if system == "Windows":
        base = os.path.join(os.environ.get("APPDATA", ""), "LyraSync", "models")
    elif system == "Darwin":
        base = os.path.expanduser("~/Library/Application Support/LyraSync/models")
    else:
        base = os.path.expanduser("~/.config/LyraSync/models")
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    return path


# ── Stage 1: Demucs vocal separation ─────────────────────────────────────────

def _separate_vocals(
    wav_path:    str,
    out_dir:     str,
    on_progress: ProgressCallback,
) -> str:
    """
    Isolate vocals from a mixed audio file using Demucs htdemucs.
    Returns path to a 16 kHz mono vocals WAV written under out_dir.
    """
    _progress(on_progress, "Separating vocals…", 5)

    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    model = get_model(DEMUCS_MODEL)
    model.eval()

    audio_np, sr = sf.read(wav_path, dtype="float32", always_2d=True)
    waveform = torch.from_numpy(audio_np.T)  # (channels, samples)


    # Demucs expects 44,100 Hz — resample if needed
    if sr != model.samplerate:
        waveform = torchaudio.transforms.Resample(sr, model.samplerate)(waveform)

    # apply_model expects shape (batch, channels, samples)
    waveform = waveform.unsqueeze(0)

    _progress(on_progress, "Separating vocals…", 14)

    with torch.no_grad():
        sources = apply_model(model, waveform, device="cpu", progress=False)

    # sources: (1, num_sources, channels, samples)
    # htdemucs order: drums, bass, other, vocals
    vocals_idx  = model.sources.index("vocals")
    vocals      = sources[0, vocals_idx]              # (channels, samples)

    # Stereo → mono, then resample to 16 kHz for whisper
    vocals_mono = vocals.mean(dim=0, keepdim=True)
    if model.samplerate != TARGET_SR:
        vocals_mono = torchaudio.transforms.Resample(
            model.samplerate, TARGET_SR
        )(vocals_mono)

    vocals_path = os.path.join(out_dir, "vocals.wav")
    sf.write(vocals_path, vocals_mono.squeeze(0).numpy(), TARGET_SR)

    # Free Demucs from memory before loading whisper
    del model, sources, waveform, vocals, vocals_mono
    gc.collect()

    _progress(on_progress, "Vocal separation complete", 30)
    logger.info(f"Vocals saved to: {vocals_path}")
    return vocals_path


# ── Stage 2: faster-whisper transcription ────────────────────────────────────

def _transcribe(
    vocals_path: str,
    on_progress: ProgressCallback,
) -> list[dict]:
    """
    Transcribe isolated vocals with faster-whisper (base.en, INT8).

    Returns a list of segments: [ { text, start, end } ]

    Each segment naturally covers a phrase or sentence — whisper splits
    on detected speech pauses, which aligns well with lyric line boundaries
    when vocals are clean (hence keeping Demucs in the pipeline).
    """
    _progress(on_progress, "Transcribing…", 35)

    from faster_whisper import WhisperModel

    model = WhisperModel(
        WHISPER_MODEL_SIZE,
        device        = "cpu",
        compute_type  = "int8",       # halves memory, negligible quality loss
        download_root = _model_dir("faster-whisper"),
    )

    segments_iter, _ = model.transcribe(
        vocals_path,
        language       = "en",
        vad_filter     = True,        # skip silence / instrumentals
        vad_parameters = {"min_silence_duration_ms": 400},
        # word_timestamps intentionally omitted — not needed at sentence level
    )

    segments = [
        {
            "text":  seg.text.strip(),
            "start": round(seg.start, 3),
            "end":   round(seg.end,   3),
        }
        for seg in segments_iter
        if seg.text.strip()
    ]

    del model
    gc.collect()

    _progress(on_progress, "Transcription complete", 60)
    logger.info(f"Whisper returned {len(segments)} segments")
    return segments


# ── Stage 3: fuzzy lyric line matcher ────────────────────────────────────────

def _normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, return token list."""
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split()


def _similarity(a: str, b: str) -> float:
    """
    Token overlap similarity (Jaccard-like). Returns 0.0–1.0.

    Uses set intersection over the larger set so that a short lyric
    line matching a long whisper segment doesn't get penalised for
    the extra words whisper included.
    """
    tokens_a = set(_normalize(a))
    tokens_b = set(_normalize(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / max(len(tokens_a), len(tokens_b))


def _match_lines_to_segments(
    lyric_lines: list[str],
    segments:    list[dict],
    duration:    float,
) -> tuple[list[dict], bool]:
    """
    Assign each lyric line a (start, end) timestamp by matching it to
    the best-fitting whisper segment.

    Algorithm:
      1. Score every (line, segment) pair by token overlap.
      2. Greedy left-to-right assignment — each line must map to a
         segment index >= the previous line's segment (monotonicity).
         Lines below MATCH_THRESHOLD are left unassigned.
      3. Multiple lines mapped to the same segment share it equally.
      4. Unassigned lines are linearly interpolated between the nearest
         matched neighbours on each side.

    Returns (sentences, used_fallback).
    """
    n_lines    = len(lyric_lines)
    n_segs     = len(segments)
    used_fallback = False

    # ── Edge case: no segments ────────────────────────────────────────────
    if n_segs == 0:
        logger.warning("No whisper segments — distributing lines evenly across duration")
        step = duration / max(n_lines, 1)
        return [
            {
                "line":       line,
                "start":      round(i * step, 3),
                "end":        round((i + 1) * step, 3),
                "confidence": 0.0,
            }
            for i, line in enumerate(lyric_lines)
        ], True

    # ── Step 1: score matrix ──────────────────────────────────────────────
    scores = [
        [_similarity(lyric_lines[i], segments[j]["text"]) for j in range(n_segs)]
        for i in range(n_lines)
    ]

    # ── Step 2: greedy monotonic assignment ───────────────────────────────
    assignments: list[Optional[int]] = [None] * n_lines
    min_seg = 0

    for i in range(n_lines):
        best_score = -1.0
        best_j     = None
        for j in range(min_seg, n_segs):
            if scores[i][j] > best_score:
                best_score = scores[i][j]
                best_j     = j
        if best_score >= MATCH_THRESHOLD and best_j is not None:
            assignments[i] = best_j
            min_seg        = best_j   # next line must use same seg or later
        else:
            assignments[i] = None
            used_fallback  = True

    # ── Step 3: build helper — matched timestamp for a line index ─────────
    def _matched_end(i: int) -> Optional[float]:
        j = assignments[i]
        return segments[j]["end"] if j is not None else None

    def _matched_start(i: int) -> Optional[float]:
        j = assignments[i]
        return segments[j]["start"] if j is not None else None

    # ── Step 4: build output ──────────────────────────────────────────────
    sentences: list[dict] = []

    for i, line in enumerate(lyric_lines):
        j = assignments[i]

        if j is not None:
            # ── Direct match ─────────────────────────────────────────────
            # If multiple lines share the same segment, divide it evenly
            seg           = segments[j]
            lines_in_seg  = [k for k in range(n_lines) if assignments[k] == j]
            pos           = lines_in_seg.index(i)
            n_sharing     = len(lines_in_seg)
            slice_dur     = (seg["end"] - seg["start"]) / n_sharing

            start = round(seg["start"] + pos * slice_dur, 3)
            end   = round(start + slice_dur, 3)
            conf  = round(scores[i][j], 3)

        else:
            # ── Interpolation ─────────────────────────────────────────────
            # Find the nearest matched lines on either side
            prev_end  = next(
                (_matched_end(k)   for k in range(i - 1, -1,      -1) if assignments[k] is not None),
                0.0
            )
            next_start = next(
                (_matched_start(k) for k in range(i + 1,  n_lines, 1) if assignments[k] is not None),
                duration
            )

            # Count consecutive unmatched lines in the same gap
            gap_lines = [
                k for k in range(n_lines)
                if assignments[k] is None
                and (
                    # prev neighbour is the same
                    next(
                        (_matched_end(m) for m in range(k - 1, -1, -1) if assignments[m] is not None),
                        0.0
                    ) == prev_end
                )
                and (
                    # next neighbour is the same
                    next(
                        (_matched_start(m) for m in range(k + 1, n_lines, 1) if assignments[m] is not None),
                        duration
                    ) == next_start
                )
            ]

            # Fallback: if gap detection fails, treat this line as the only one
            if i not in gap_lines:
                gap_lines = [i]

            pos      = gap_lines.index(i)
            n_gap    = len(gap_lines)
            gap_dur  = next_start - prev_end
            step     = gap_dur / n_gap

            start = round(prev_end + pos * step, 3)
            end   = round(start + step, 3)
            conf  = 0.0

        sentences.append({
            "line":       line,
            "start":      start,
            "end":        end,
            "confidence": conf,
        })

    return sentences, used_fallback


# ── Public API ────────────────────────────────────────────────────────────────

def align_track(
    wav_path:    str,
    lyrics:      str,
    on_progress: Optional[ProgressCallback] = None,
) -> AlignmentResult:
    """
    Align newline-separated lyric lines to audio.

    Args:
        wav_path:    Path to a 16 kHz mono WAV (from youtube_downloader.py).
        lyrics:      Newline-separated lyric lines from Electron.
        on_progress: Optional callback(stage: str, pct: int).

    Returns:
        AlignmentResult — one sentence entry per lyric line.

    Raises:
        FileNotFoundError: If wav_path does not exist.
        ValueError:        If lyrics string contains no lines.
        RuntimeError:      If transcription returns nothing.
    """
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    cb = on_progress or _noop

    lyric_lines = [ln.strip() for ln in lyrics.splitlines() if ln.strip()]
    if not lyric_lines:
        raise ValueError("lyrics string contains no non-empty lines.")

    import soundfile as sf
    audio_info   = sf.info(wav_path)
    duration_sec = audio_info.frames / audio_info.samplerate

    _progress(cb, "Starting…", 0)

    with tempfile.TemporaryDirectory(prefix="lyrasync_align_") as tmp_dir:
        vocals_path = _separate_vocals(wav_path, tmp_dir, cb)
        segments    = _transcribe(vocals_path, cb)

    if not segments:
        raise RuntimeError(
            "Transcription returned no segments. "
            "The track may be purely instrumental, silent, or too short."
        )

    _progress(cb, "Matching lines to audio…", 65)
    sentences, used_fallback = _match_lines_to_segments(
        lyric_lines, segments, duration_sec
    )

    _progress(cb, "Done", 100)
    logger.info(
        f"Aligned {len(sentences)} lines | "
        f"fallback={used_fallback} | "
        f"duration={duration_sec:.1f}s"
    )

    return AlignmentResult(
        sentences     = sentences,
        used_fallback = used_fallback,
        duration_sec  = duration_sec,
    )


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python align.py <path_to_wav> <path_to_lyrics_txt>")
        sys.exit(1)

    with open(sys.argv[2], "r", encoding="utf-8") as f:
        lyrics_text = f.read()

    def progress(stage: str, pct: int) -> None:
        print(f"  [{pct:3d}%] {stage}")

    result = align_track(
        wav_path    = sys.argv[1],
        lyrics      = lyrics_text,
        on_progress = progress,
    )

    print(f"\n{len(result.sentences)} lines aligned | fallback={result.used_fallback}\n")
    print(json.dumps(result.to_dict(), indent=2))