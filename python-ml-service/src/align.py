"""
align.py — LyraSync
Three-stage alignment pipeline:
  1. Demucs        — vocal source separation (htdemucs)
  2. faster-whisper — ASR transcription, segment-level timestamps only
  3. LLM matcher   — Groq API maps each lyric line to its Whisper segment
                     and derives the final sentence timestamps directly

The LLM replaces the previous DP + NW matching stack entirely.  It handles
ASR substitution errors, merged/split segments, and repeated chorus sections
naturally through semantic understanding rather than token overlap scoring.

Output is sentence-level timestamps, one per lyric line:
  [ { "line": "I've been on my own...", "start": 4.2, "end": 7.8 } ]

Usage:
    from align import align_track, AlignmentResult

    def on_progress(stage: str, pct: int):
        print(f"[{pct}%] {stage}")

    result = align_track(
        wav_path    = "/tmp/audio.wav",
        lyrics      = "First line\\nSecond line\\nThird line",
        on_progress = on_progress,
    )

    for sentence in result.sentences:
        print(sentence["line"], sentence["start"], sentence["end"])

Environment:
    GROQ_API_KEY — required, set in environment or .env file
"""

import gc
import json
import logging
import os
import platform
import re
import tempfile
from dataclasses import dataclass
from typing import Callable, Optional

import torch
import torchaudio
import soundfile as sf

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

WHISPER_MODEL_SIZE = "base.en"
DEMUCS_MODEL       = "htdemucs"
TARGET_SR          = 16_000   # Hz — whisper expects 16 kHz

GROQ_MODEL         = "llama-3.3-70b-versatile"   # free tier, strong reasoning
GROQ_TIMEOUT       = 30        # seconds per request


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

    if sr != model.samplerate:
        waveform = torchaudio.transforms.Resample(sr, model.samplerate)(waveform)

    waveform = waveform.unsqueeze(0)  # (batch, channels, samples)

    _progress(on_progress, "Separating vocals…", 14)

    with torch.no_grad():
        sources = apply_model(model, waveform, device="cpu", progress=False)

    # htdemucs source order: drums, bass, other, vocals
    vocals_idx  = model.sources.index("vocals")
    vocals      = sources[0, vocals_idx]              # (channels, samples)

    vocals_mono = vocals.mean(dim=0, keepdim=True)
    if model.samplerate != TARGET_SR:
        vocals_mono = torchaudio.transforms.Resample(
            model.samplerate, TARGET_SR
        )(vocals_mono)

    vocals_path = os.path.join(out_dir, "vocals.wav")
    sf.write(vocals_path, vocals_mono.squeeze(0).numpy(), TARGET_SR)

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

    Returns a list of segments: [ { "text", "start", "end" } ]

    Word timestamps are not requested — the LLM matcher works at segment
    level and derives line timestamps from segment start/end directly.

    VAD tuning:
      - min_silence_duration_ms=100 catches short inter-phrase gaps in sung
        music (vs the default 400ms which merges entire sections).
      - threshold=0.35 is more sensitive than the default 0.5 so quieter
        pauses still register as boundaries.
      - condition_on_previous_text=False prevents Whisper hallucinating
        continuation across chorus repeats.
    """
    _progress(on_progress, "Transcribing…", 35)

    from faster_whisper import WhisperModel

    model = WhisperModel(
        WHISPER_MODEL_SIZE,
        device        = "cpu",
        compute_type  = "int8",
        download_root = _model_dir("faster-whisper"),
    )

    segments_iter, _ = model.transcribe(
        vocals_path,
        language                   = "en",
        word_timestamps            = False,   # not needed — LLM works at segment level
        vad_filter                 = True,
        vad_parameters             = {
            "min_silence_duration_ms": 100,
            "threshold":               0.35,
        },
        condition_on_previous_text = False,
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
    logger.info("=== Whisper segments ===")
    for s in segments:
        logger.info(f"  [{s['start']:.2f} → {s['end']:.2f}] {s['text']}")
    logger.info(f"=== End ({len(segments)} segments) ===")
    return segments


# ── Stage 3: LLM lyric-to-segment matching ───────────────────────────────────

_SYSTEM_PROMPT = """\
You are a music lyric alignment assistant. Match song lyric lines to \
timestamped Whisper ASR segments and produce sentence-level timestamps.

Input:
- LYRICS: clean song lyrics numbered 0–N in order
- SEGMENTS: Whisper output with start/end times in seconds

CRITICAL RULES:
- Every lyric line must have unique, non-overlapping timeframes.
- Each line maps to one or more segments; timestamps span first segment start to last segment end.
- When multiple lines map to the same segment, you MUST split the time proportionally by word count.

EXAMPLE - Proportional splitting:
  If segment [5.0 → 10.0] contains TWO lines:
    - Line A: "Hello world" (2 words)
    - Line B: "How are you today" (4 words)
  
  Total words = 6. Duration = 5.0 seconds. Rate = 5.0/6 ≈ 0.833 sec/word.
  
  - Line A: start=5.0, end=5.0 + 2*0.833 = 6.666
  - Line B: start=6.666, end=6.666 + 4*0.833 = 10.0 ✓

OTHER RULES:
- Match despite ASR errors (wrong words, merged/split lines).
- If a line is not found (instrumental, inaudible), set start/end to null, confidence to 0.0.
- confidence: 1.0 = exact match, 0.5 = found with errors, 0.0 = not found.
- Output ONLY valid JSON array, no markdown or extra text.
- All "start" and "end" must be pre-computed decimals, NEVER expressions or division symbols.

Output format — JSON array, one object per line in order:
[
    {"line": "lyric text", "start": 12.34, "end": 15.67, "confidence": 1.0},
    ...
]
"""


def _build_user_prompt(lyric_lines: list[str], segments: list[dict]) -> str:
    lyrics_block = "\n".join(f"{i}: {line}" for i, line in enumerate(lyric_lines))
    segments_block = "\n".join(
        f"[{s['start']:.2f}→{s['end']:.2f}] {s['text']}"
        for s in segments
    )
    return f"LYRICS:\n{lyrics_block}\n\nSEGMENTS:\n{segments_block}"


def _call_groq(prompt: str, api_key: str) -> str:
    """
    Call the Groq API using the official groq-python SDK.
    Using the SDK (backed by httpx) rather than urllib ensures requests pass
    through Cloudflare without being blocked by TLS fingerprinting filters.
    Returns the assistant message content string.
    Raises RuntimeError if the call fails.
    """
    from groq import Groq, APIError

    client = Groq(api_key=api_key, timeout=GROQ_TIMEOUT)

    try:
        response = client.chat.completions.create(
            model           = GROQ_MODEL,
            temperature     = 0.0,
            response_format = {"type": "json_object"},
            messages        = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
        )
        return response.choices[0].message.content
    except APIError as exc:
        raise RuntimeError(f"Groq API error {exc.status_code}: {exc.message}") from exc
    except Exception as exc:
        raise RuntimeError(f"Groq call failed: {exc}") from exc


def _parse_llm_response(
    raw:         str,
    lyric_lines: list[str],
    duration:    float,
) -> tuple[list[dict], bool]:
    """
    Parse the LLM's JSON response directly with zero post-processing.
    
    The LLM output is the source of truth — we extract it as-is.
    No interpolation, no monotonicity enforcement, no timestamp adjustment.
    
    Returns (sentences, used_fallback).
    """
    used_fallback = False
    
    # Strip markdown fences if the model added them despite instructions
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-z]*\n?", "", clean)
        clean = re.sub(r"\n?```$",        "", clean)
        clean = clean.strip()

    try:
        parsed = json.loads(clean)
        # If wrapped in {"lyrics": [...]}, extract the array
        if isinstance(parsed, dict) and "lyrics" in parsed:
            parsed = parsed["lyrics"]
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON array at top level")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(f"LLM returned unparseable JSON: {exc}\nRaw:\n{raw[:500]}")
        return [], True

    # Extract each entry exactly as the LLM provided it
    sentences: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        
        line = item.get("line", "").strip()
        start = item.get("start")
        end = item.get("end")
        confidence = item.get("confidence", 0.0)
        
        # Type conversion only — no semantic changes
        try:
            start = round(float(start), 3) if start is not None else None
            end = round(float(end), 3) if end is not None else None
            confidence = round(float(confidence), 3)
        except (TypeError, ValueError):
            start = end = None
            confidence = 0.0
        
        sentences.append({
            "line": line,
            "start": start,
            "end": end,
            "confidence": confidence,
        })
        
        # Mark as fallback if any line was marked as not found by the LLM
        if start is None or end is None:
            used_fallback = True
        
    
    return sentences, used_fallback


def _resolve_overlaps(sentences: list[dict]) -> None:
    """
    Resolve overlapping segments by splitting proportionally by word count.
    
    Modifies sentences in-place. When consecutive lines share overlapping
    time ranges, divides the overlap proportionally based on word counts.
    
    This implements the LLM's intended behavior when it fails to split
    shared segments correctly.
    """
    n = len(sentences)
    i = 0
    
    while i < n:
        # Find the range of lines that overlap with line i
        if sentences[i]["start"] is None:
            i += 1
            continue
        
        # Collect all consecutive lines that overlap with line i
        group = [i]
        for j in range(i + 1, n):
            if sentences[j]["start"] is None:
                break
            # Check if line j overlaps with the current group's span
            group_end = max(sentences[k]["end"] for k in group)
            if sentences[j]["start"] < group_end:
                group.append(j)
            else:
                break
        
        # If no overlaps, move on
        if len(group) == 1:
            i += 1
            continue
        
        # Overlaps detected — split proportionally by word count
        group_start = sentences[group[0]]["start"]
        group_end = sentences[group[-1]]["end"]
        duration = group_end - group_start
        
        # Count total words in the group
        total_words = sum(len(sentences[k]["line"].split()) for k in group)
        
        if total_words == 0:
            i += len(group)
            continue
        
        # Assign time proportionally
        cursor = group_start
        for k in group:
            word_count = len(sentences[k]["line"].split())
            portion = (word_count / total_words) * duration
            sentences[k]["start"] = round(cursor, 3)
            sentences[k]["end"] = round(cursor + portion, 3)
            cursor += portion
        
        # Ensure the last line in the group reaches the original end
        sentences[group[-1]]["end"] = round(group_end, 3)
        
        i += len(group)


def _interpolate_missing_lines(sentences: list[dict], duration: float) -> None:
    """
    Interpolate timestamps for lines where the LLM couldn't find a match (null start/end).
    
    For each null-timestamp line, estimates time based on neighbors:
      - Finds the last valid timestamp before it
      - Finds the first valid timestamp after it
      - Divides the gap evenly among all consecutive null lines in that span
    
    Modifies sentences in-place.
    """
    n = len(sentences)
    i = 0
    
    while i < n:
        if sentences[i]["start"] is not None:
            i += 1
            continue
        
        # Collect all consecutive null lines starting at i
        null_group = [i]
        for j in range(i + 1, n):
            if sentences[j]["start"] is None:
                null_group.append(j)
            else:
                break
        
        # Find boundaries
        prev_idx = next((k for k in range(i - 1, -1, -1) if sentences[k]["end"] is not None), -1)
        next_idx = next((k for k in range(i + len(null_group), n) if sentences[k]["start"] is not None), -1)
        
        prev_end = sentences[prev_idx]["end"] if prev_idx >= 0 else 0.0
        next_start = sentences[next_idx]["start"] if next_idx >= 0 else duration
        
        # Divide the gap evenly among null lines
        gap_duration = next_start - prev_end
        step = gap_duration / len(null_group)
        
        for idx, k in enumerate(null_group):
            sentences[k]["start"] = round(prev_end + idx * step, 3)
            sentences[k]["end"] = round(prev_end + (idx + 1) * step, 3)
        
        # Ensure last null line doesn't exceed next_start
        if null_group and next_idx >= 0:
            sentences[null_group[-1]]["end"] = round(next_start, 3)
        
        i += len(null_group)


def _match_lines_to_segments(
    lyric_lines: list[str],
    segments:    list[dict],
    duration:    float,
    on_progress: ProgressCallback,
) -> tuple[list[dict], bool]:
    """
    Use a Groq-hosted LLM to directly produce sentence-level timestamps
    from the raw lyric lines and Whisper segments.

    Falls back to linear interpolation for any lines the LLM could not place.
    """
    if not segments:
        logger.warning("No Whisper segments — distributing lines evenly")
        step = duration / max(len(lyric_lines), 1)
        return [
            {
                "line":       line,
                "start":      round(i * step, 3),
                "end":        round((i + 1) * step, 3),
                "confidence": 0.0,
            }
            for i, line in enumerate(lyric_lines)
        ], True

    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Get a free key at https://console.groq.com"
        )

    _progress(on_progress, "Matching lyrics with LLM…", 65)

    prompt            = _build_user_prompt(lyric_lines, segments)
    raw               = _call_groq(prompt, api_key)

    logger.info("=== LLM raw response ===")
    logger.info(raw[:2000] + ("…" if len(raw) > 2000 else ""))
    logger.info("=== End LLM response ===")

    sentences, used_fallback = _parse_llm_response(raw, lyric_lines, duration)
    
    # Resolve any overlapping segments by splitting proportionally
    _resolve_overlaps(sentences)
    
    # Interpolate lines that the LLM couldn't find (null timestamps)
    _interpolate_missing_lines(sentences, duration)

    _progress(on_progress, "Matching complete", 85)
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
        wav_path:    Path to a WAV file (any sample rate; Demucs will resample).
        lyrics:      Newline-separated lyric lines.
        on_progress: Optional callback(stage: str, pct: int).

    Returns:
        AlignmentResult — one sentence entry per lyric line.

    Raises:
        FileNotFoundError: If wav_path does not exist.
        ValueError:        If lyrics string contains no non-empty lines.
        RuntimeError:      If transcription returns nothing, or GROQ_API_KEY unset.
    """
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    cb = on_progress or _noop

    lyric_lines = [ln.strip() for ln in lyrics.splitlines() if ln.strip()]
    if not lyric_lines:
        raise ValueError("lyrics string contains no non-empty lines.")

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

    sentences, used_fallback = _match_lines_to_segments(
        lyric_lines, segments, duration_sec, cb
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