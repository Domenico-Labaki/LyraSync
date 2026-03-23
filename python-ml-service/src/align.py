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

Rules:
- Match despite ASR errors (wrong words, merged/split lines).
- Every lyric line appears in output exactly once, in original order.
- For each line, find its segment(s) and assign timestamps.
- If a line shares a segment with others, divide time proportionally by word count.
- If a line is not found (instrumental, inaudible), set start/end to null, confidence to 0.0.
- confidence: 1.0 = exact match, 0.5 = found with errors, 0.0 = not found.
- Output ONLY valid JSON array, no markdown or extra text.
- CRITICAL: all "start" and "end" must be pre-computed decimals, never expressions.

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
    Parse the LLM's JSON response into the sentences list.

    Handles two failure modes gracefully:
      - Malformed / partial JSON: missing lines are interpolated.
      - null timestamps (LLM marked a line as not found): interpolated
        between the nearest valid neighbours.

    Also enforces strict monotonicity — timestamps never go backwards.

    Returns (sentences, used_fallback).
    """
    used_fallback = False
    
    # Strip markdown fences if the model added them despite instructions
    clean = raw.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```[a-z]*\n?", "", clean)
        clean = re.sub(r"\n?```$",        "", clean)
        clean = clean.strip()

    # Evaluate any arithmetic expressions the LLM wrote instead of literals.
    # JSON does not allow expressions like "2.70 + (10.72 - 2.70) / 9", but
    # some models produce them anyway despite being told not to.  This regex
    # finds every JSON value position that contains arithmetic operators and
    # replaces it with the pre-computed float.  It only matches sequences of
    # digits, spaces, and the four operators — it will never touch string values.
    def _eval_expr(m: re.Match) -> str:
        expr = m.group(1).strip()
        # Only evaluate if the expression actually contains an operator —
        # plain numbers like "12.34" should pass through untouched.
        if not re.search(r"[+\-*/]", expr):
            return m.group(0)
        try:
            result = float(eval(expr, {"__builtins__": {}}, {}))
            return f": {round(result, 3)}"
        except Exception:
            return m.group(0)   # leave unchanged if eval fails

    clean = re.sub(r":\s*([\d\s.+\-*/()]+)", _eval_expr, clean)

    try:
        parsed = json.loads(clean)
        if not isinstance(parsed, list) and "lyrics" in parsed:
            parsed = parsed["lyrics"]
        if not isinstance(parsed, list):
            raise ValueError("Expected a JSON array at top level")
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error(f"LLM returned unparseable JSON: {exc}\nRaw:\n{raw[:500]}")
        parsed        = []
        used_fallback = True

    # Build lookup by line text (for fallback) and by position (primary)
    parsed_by_text: dict[str, dict] = {}
    for item in parsed:
        if isinstance(item, dict) and "line" in item:
            parsed_by_text[item["line"].strip()] = item

    # Match each lyric line to its parsed entry
    sentences: list[dict] = []
    for i, line in enumerate(lyric_lines):
        # Try positional match first — LLM is instructed to return in order
        item = parsed[i] if i < len(parsed) and isinstance(parsed[i], dict) else None

        # If the positional entry's text doesn't match, fall back to text lookup
        if item is None or item.get("line", "").strip() != line.strip():
            item = parsed_by_text.get(line.strip())

        start = item.get("start") if item else None
        end   = item.get("end")   if item else None
        conf  = float(item.get("confidence", 0.0)) if item else 0.0

        if start is None or end is None:
            used_fallback = True
            sentences.append({"line": line, "start": None, "end": None, "confidence": 0.0})
        else:
            sentences.append({
                "line":       line,
                "start":      round(float(start), 3),
                "end":        round(float(end),   3),
                "confidence": round(conf, 3),
            })

    # Interpolate lines whose timestamps are still None
    n = len(sentences)
    for i in range(n):
        if sentences[i]["start"] is not None:
            continue

        prev_end = next(
            (sentences[k]["end"]   for k in range(i - 1, -1, -1) if sentences[k]["end"]   is not None),
            0.0,
        )
        next_start = next(
            (sentences[k]["start"] for k in range(i + 1, n)       if sentences[k]["start"] is not None),
            duration,
        )

        # Collect all consecutive None lines in this same gap
        gap = [
            k for k in range(n)
            if sentences[k]["start"] is None
            and next(
                (sentences[m]["end"]   for m in range(k-1, -1, -1) if sentences[m]["end"]   is not None),
                0.0,
            ) == prev_end
            and next(
                (sentences[m]["start"] for m in range(k+1, n)       if sentences[m]["start"] is not None),
                duration,
            ) == next_start
        ]
        if i not in gap:
            gap = [i]

        pos   = gap.index(i)
        n_gap = len(gap)

        if prev_end >= next_start:
            step  = 2.0
            start = round(prev_end + pos * step, 3)
            end   = round(start + step, 3)
        else:
            step  = (next_start - prev_end) / n_gap
            start = round(prev_end + pos * step, 3)
            end   = round(min(start + step, next_start), 3)

        sentences[i]["start"] = start
        sentences[i]["end"]   = end

    # Monotonicity clamp — belt-and-suspenders guard against any LLM quirks
    cursor = 0.0
    for s in sentences:
        if s["start"] < cursor:
            dur            = max(s["end"] - s["start"], 0.0)
            s["start"]     = round(cursor, 3)
            s["end"]       = round(cursor + dur, 3)
            s["confidence"] = 0.0
            used_fallback   = True
        cursor = max(cursor, s["end"])

    return sentences, used_fallback


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