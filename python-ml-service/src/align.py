"""
align.py — LyraSync
Three-stage local ML alignment pipeline:
  1. Demucs     — vocal source separation
  2. faster-whisper — ASR transcription (base.en)
  3. wav2vec2   — CTC forced alignment → precise word timestamps

If wav2vec2 alignment fails, falls back to faster-whisper segment
timestamps (less precise but always usable).

Usage:
    from align import align_track, AlignmentResult

    def on_progress(stage: str, pct: int):
        print(f"[{pct}%] {stage}")

    result = align_track(
        wav_path   = "/tmp/audio.wav",
        lyrics     = "I've been on my own for long enough...",
        on_progress = on_progress,
    )

    for word in result.words:
        print(word["word"], word["start"], word["end"])
"""

import os
import gc
import logging
import re
import tempfile
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import torch
import torchaudio

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

WHISPER_MODEL_SIZE = "base.en"
WAV2VEC2_MODEL_ID  = "facebook/wav2vec2-base-960h"
TARGET_SR          = 16_000   # Hz — wav2vec2 + whisper both expect 16 kHz
DEMUCS_MODEL       = "htdemucs"

# Alignment confidence threshold — words below this are flagged as low-confidence
MIN_CONFIDENCE = 0.4


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class WordTimestamp:
    word:       str
    start:      float   # seconds
    end:        float   # seconds
    confidence: float   # 0.0 – 1.0
    fallback:   bool    # True if sourced from whisper, not wav2vec2

    def to_dict(self) -> dict:
        return {
            "word":       self.word,
            "start":      round(self.start, 3),
            "end":        round(self.end,   3),
            "confidence": round(self.confidence, 3),
            "fallback":   self.fallback,
        }


@dataclass
class AlignmentResult:
    words:            list[WordTimestamp]
    used_fallback:    bool   # True if wav2vec2 failed and whisper timestamps were used
    whisper_language: str
    duration_sec:     float

    def to_dict(self) -> dict:
        return {
            "words":            [w.to_dict() for w in self.words],
            "used_fallback":    self.used_fallback,
            "whisper_language": self.whisper_language,
            "duration_sec":     round(self.duration_sec, 3),
        }


# ── Progress helper ───────────────────────────────────────────────────────────

ProgressCallback = Callable[[str, int], None]   # (stage_label, pct_0_to_100)

def _noop(stage: str, pct: int) -> None:
    pass

def _progress(cb: ProgressCallback, stage: str, pct: int) -> None:
    logger.info(f"[{pct:3d}%] {stage}")
    cb(stage, pct)


# ── Stage 1: Demucs vocal separation ─────────────────────────────────────────

def _separate_vocals(
    wav_path:    str,
    out_dir:     str,
    on_progress: ProgressCallback,
) -> str:
    """
    Run Demucs htdemucs on wav_path. Returns the path to the isolated
    vocals WAV file written under out_dir.

    Demucs writes:  out_dir/htdemucs/<stem>/{vocals,drums,bass,other}.wav
    We return the vocals.wav path.
    """
    _progress(on_progress, "Separating vocals (Demucs)…", 5)

    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    model = get_model(DEMUCS_MODEL)
    model.eval()

    # Load audio — torchaudio handles WAV natively
    waveform, sr = torchaudio.load(wav_path)

    # Resample to model's expected sample rate if needed (Demucs uses 44100)
    if sr != model.samplerate:
        resampler = torchaudio.transforms.Resample(sr, model.samplerate)
        waveform  = resampler(waveform)

    # Demucs expects shape (1, channels, samples)
    waveform = waveform.unsqueeze(0)

    _progress(on_progress, "Separating vocals (Demucs)…", 15)

    with torch.no_grad():
        sources = apply_model(model, waveform, device="cpu", progress=False)

    # sources shape: (1, num_sources, channels, samples)
    # source order: drums, bass, other, vocals  (for htdemucs)
    source_names = model.sources
    vocals_idx   = source_names.index("vocals")
    vocals       = sources[0, vocals_idx]   # (channels, samples)

    # Write vocals to temp WAV at 16 kHz mono for downstream stages
    vocals_mono = vocals.mean(dim=0, keepdim=True)   # stereo → mono
    if model.samplerate != TARGET_SR:
        resampler   = torchaudio.transforms.Resample(model.samplerate, TARGET_SR)
        vocals_mono = resampler(vocals_mono)

    vocals_path = os.path.join(out_dir, "vocals.wav")
    torchaudio.save(vocals_path, vocals_mono, TARGET_SR)

    # Free model memory before loading whisper
    del model, sources, waveform, vocals, vocals_mono
    gc.collect()

    _progress(on_progress, "Vocal separation complete", 30)
    logger.info(f"Vocals written to: {vocals_path}")
    return vocals_path


# ── Stage 2: faster-whisper transcription ────────────────────────────────────

def _transcribe(
    vocals_path: str,
    on_progress: ProgressCallback,
) -> tuple[list[dict], str]:
    """
    Transcribe vocals_path with faster-whisper (base.en).

    Returns:
        segments  — list of { text, start, end, words: [{word, start, end, probability}] }
        language  — detected language code (e.g. "en")
    """
    _progress(on_progress, "Transcribing (faster-whisper)…", 35)

    from faster_whisper import WhisperModel

    model = WhisperModel(
        WHISPER_MODEL_SIZE,
        device          = "cpu",
        compute_type    = "int8",   # INT8 for CPU — fastest without quality loss
        download_root   = _model_dir("faster-whisper"),
    )

    segments_iter, info = model.transcribe(
        vocals_path,
        language          = "en",
        word_timestamps   = True,    # needed for fallback timestamps
        vad_filter        = True,    # skip silence — speeds up + reduces hallucinations
        vad_parameters    = {"min_silence_duration_ms": 500},
    )

    segments = []
    for seg in segments_iter:
        word_list = []
        if seg.words:
            for w in seg.words:
                word_list.append({
                    "word":        w.word.strip(),
                    "start":       w.start,
                    "end":         w.end,
                    "probability": w.probability,
                })
        segments.append({
            "text":  seg.text.strip(),
            "start": seg.start,
            "end":   seg.end,
            "words": word_list,
        })

    del model
    gc.collect()

    _progress(on_progress, "Transcription complete", 55)
    logger.info(f"Transcribed {len(segments)} segments, language={info.language}")
    return segments, info.language


# ── Stage 3: wav2vec2 forced alignment ───────────────────────────────────────

def _forced_align(
    vocals_path: str,
    lyrics:      str,
    segments:    list[dict],
    on_progress: ProgressCallback,
) -> tuple[list[WordTimestamp], bool]:
    """
    Run wav2vec2 CTC forced alignment.

    Uses the whisper transcript (not raw lyrics) as the reference text —
    this gives better alignment than using raw lyrics directly, since
    whisper has already cleaned up contractions, spacing, etc.

    Falls back to whisper word-level timestamps if alignment fails.

    Returns:
        (word_timestamps, used_fallback)
    """
    _progress(on_progress, "Aligning with wav2vec2…", 60)

    try:
        from transformers import Wav2Vec2Processor, Wav2Vec2ForCTC

        # Load audio
        waveform, sr = torchaudio.load(vocals_path)
        if sr != TARGET_SR:
            waveform = torchaudio.transforms.Resample(sr, TARGET_SR)(waveform)
        waveform = waveform.mean(dim=0)   # ensure mono, shape (samples,)

        audio_duration = waveform.shape[0] / TARGET_SR

        # Load model
        model_path = _model_dir("wav2vec2")
        processor  = Wav2Vec2Processor.from_pretrained(
            WAV2VEC2_MODEL_ID, cache_dir=model_path
        )
        model = Wav2Vec2ForCTC.from_pretrained(
            WAV2VEC2_MODEL_ID, cache_dir=model_path
        )
        model.eval()

        _progress(on_progress, "Aligning with wav2vec2…", 68)

        # Build flat word list from whisper segments
        whisper_words = []
        for seg in segments:
            for w in seg["words"]:
                if w["word"]:
                    whisper_words.append(w)

        if not whisper_words:
            raise ValueError("No words from whisper transcription")

        # Run wav2vec2 in chunks to avoid OOM on long tracks
        results = _align_chunks(waveform, whisper_words, processor, model, audio_duration)

        del model, processor, waveform
        gc.collect()

        _progress(on_progress, "Alignment complete", 88)
        return results, False

    except Exception as e:
        logger.warning(f"wav2vec2 alignment failed: {e}. Using whisper fallback.")
        _progress(on_progress, "Using whisper timestamps (fallback)…", 88)
        return _whisper_fallback(segments), True


def _align_chunks(
    waveform:      torch.Tensor,
    whisper_words: list[dict],
    processor,
    model,
    audio_duration: float,
    chunk_sec:      float = 30.0,
) -> list[WordTimestamp]:
    """
    Align in 30-second chunks with 1-second overlap to handle long tracks
    without OOM errors on CPU.
    """
    results: list[WordTimestamp] = []
    chunk_samples  = int(chunk_sec * TARGET_SR)
    overlap_samples = TARGET_SR   # 1 second overlap

    total_samples = waveform.shape[0]
    chunk_start   = 0

    while chunk_start < total_samples:
        chunk_end   = min(chunk_start + chunk_samples, total_samples)
        chunk_audio = waveform[chunk_start:chunk_end]

        time_offset = chunk_start / TARGET_SR
        time_end    = chunk_end   / TARGET_SR

        # Filter whisper words that fall within this chunk (with buffer)
        chunk_words = [
            w for w in whisper_words
            if w["start"] >= time_offset - 0.5 and w["end"] <= time_end + 0.5
        ]

        if not chunk_words:
            chunk_start += chunk_samples - overlap_samples
            continue

        # Tokenise audio
        inputs = processor(
            chunk_audio.numpy(),
            sampling_rate = TARGET_SR,
            return_tensors = "pt",
        )

        with torch.no_grad():
            logits = model(**inputs).logits   # (1, time_steps, vocab)

        # CTC alignment per word
        chunk_results = _ctc_align(
            logits      = logits[0],
            words       = chunk_words,
            processor   = processor,
            time_offset = time_offset,
            chunk_dur   = (chunk_end - chunk_start) / TARGET_SR,
        )

        # Deduplicate words already aligned in a previous chunk's overlap
        seen_starts = {r.start for r in results}
        for r in chunk_results:
            if r.start not in seen_starts:
                results.append(r)

        chunk_start += chunk_samples - overlap_samples

    return sorted(results, key=lambda w: w.start)


def _ctc_align(
    logits:      torch.Tensor,
    words:       list[dict],
    processor,
    time_offset: float,
    chunk_dur:   float,
) -> list[WordTimestamp]:
    """
    Map logit frames → word timestamps using greedy CTC decode then
    character-level matching to find word boundaries.
    """
    # Greedy decode: argmax over vocab at each time step
    predicted_ids = torch.argmax(logits, dim=-1)
    vocab         = processor.tokenizer.convert_ids_to_tokens(
        range(len(processor.tokenizer))
    )

    # Build (frame_index, char) sequence, collapsing CTC blanks and repeats
    blank_id    = processor.tokenizer.pad_token_id
    prev_id     = None
    char_frames = []   # [(frame_idx, char)]

    for frame_idx, token_id in enumerate(predicted_ids.tolist()):
        if token_id == blank_id:
            prev_id = None
            continue
        if token_id == prev_id:
            continue
        char = vocab[token_id].replace("▁", " ").replace("|", " ").upper()
        char_frames.append((frame_idx, char))
        prev_id = token_id

    if not char_frames:
        return _whisper_words_to_timestamps(words, time_offset)

    total_frames = logits.shape[0]
    frames_per_sec = total_frames / chunk_dur

    results = []
    decoded_text = "".join(c for _, c in char_frames).strip()

    for w in words:
        word_clean = re.sub(r"[^A-Z\s]", "", w["word"].upper()).strip()
        if not word_clean:
            continue

        # Find word in decoded text
        match = re.search(re.escape(word_clean), decoded_text)
        if match:
            # Map char position → frame index → time
            char_pos_start = match.start()
            char_pos_end   = match.end() - 1

            # Walk char_frames to find matching frame indices
            frame_start = _char_pos_to_frame(char_frames, char_pos_start)
            frame_end   = _char_pos_to_frame(char_frames, char_pos_end)

            t_start = time_offset + (frame_start / frames_per_sec)
            t_end   = time_offset + ((frame_end + 1) / frames_per_sec)

            results.append(WordTimestamp(
                word       = w["word"].strip(),
                start      = round(t_start, 3),
                end        = round(t_end,   3),
                confidence = round(w["probability"], 3),
                fallback   = False,
            ))
        else:
            # Word not found in CTC decode — use whisper timestamp
            results.append(WordTimestamp(
                word       = w["word"].strip(),
                start      = round(w["start"], 3),
                end        = round(w["end"],   3),
                confidence = round(w["probability"] * 0.5, 3),
                fallback   = True,
            ))

    return results


def _char_pos_to_frame(char_frames: list[tuple[int, str]], char_pos: int) -> int:
    """Return the frame index for a given character position in the decoded sequence."""
    # char_frames is a flat list of (frame, char) — char_pos indexes into
    # the joined string, so we need to account for multi-char tokens
    current_pos = 0
    for frame_idx, char in char_frames:
        current_pos += len(char)
        if current_pos > char_pos:
            return frame_idx
    return char_frames[-1][0] if char_frames else 0


def _whisper_words_to_timestamps(words: list[dict], time_offset: float) -> list[WordTimestamp]:
    """Convert raw whisper word dicts to WordTimestamp objects (fallback)."""
    return [
        WordTimestamp(
            word       = w["word"].strip(),
            start      = round(w["start"] + time_offset, 3),
            end        = round(w["end"]   + time_offset, 3),
            confidence = round(w["probability"], 3),
            fallback   = True,
        )
        for w in words if w["word"].strip()
    ]


def _whisper_fallback(segments: list[dict]) -> list[WordTimestamp]:
    """Build word timestamps from whisper word-level data (full fallback)."""
    results = []
    for seg in segments:
        for w in seg["words"]:
            if w["word"].strip():
                results.append(WordTimestamp(
                    word       = w["word"].strip(),
                    start      = round(w["start"], 3),
                    end        = round(w["end"],   3),
                    confidence = round(w["probability"], 3),
                    fallback   = True,
                ))
    return results


# ── Path helpers ─────────────────────────────────────────────────────────────

def _model_dir(name: str) -> str:
    """Return the platform-appropriate model cache directory for a given model."""
    import platform
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


# ── Public API ────────────────────────────────────────────────────────────────

def align_track(
    wav_path:    str,
    lyrics:      str,
    on_progress: Optional[ProgressCallback] = None,
) -> AlignmentResult:
    """
    Run the full three-stage alignment pipeline on a 16 kHz mono WAV file.

    Args:
        wav_path:     Path to a 16 kHz mono WAV (from youtube_downloader.py).
        lyrics:       Plain-text lyrics string provided by Electron.
        on_progress:  Optional callback(stage: str, pct: int) for progress reporting.

    Returns:
        AlignmentResult with word-level timestamps.

    Raises:
        FileNotFoundError: If wav_path does not exist.
        RuntimeError:      If all stages fail with no usable output.
    """
    if not os.path.exists(wav_path):
        raise FileNotFoundError(f"WAV file not found: {wav_path}")

    cb = on_progress or _noop

    # Get audio duration for result metadata
    info         = torchaudio.info(wav_path)
    duration_sec = info.num_frames / info.sample_rate

    _progress(cb, "Starting alignment pipeline…", 0)

    with tempfile.TemporaryDirectory(prefix="lyrasync_align_") as tmp_dir:

        # Stage 1 — Demucs vocal separation
        vocals_path = _separate_vocals(wav_path, tmp_dir, cb)

        # Stage 2 — faster-whisper transcription
        segments, language = _transcribe(vocals_path, cb)

        if not segments:
            raise RuntimeError("Transcription returned no segments — cannot align.")

        # Stage 3 — wav2vec2 forced alignment (with whisper fallback)
        words, used_fallback = _forced_align(vocals_path, lyrics, segments, cb)

    if not words:
        raise RuntimeError("Alignment produced no word timestamps.")

    _progress(cb, "Done", 100)

    result = AlignmentResult(
        words            = words,
        used_fallback    = used_fallback,
        whisper_language = language,
        duration_sec     = duration_sec,
    )

    logger.info(
        f"Alignment complete: {len(words)} words, "
        f"fallback={used_fallback}, duration={duration_sec:.1f}s"
    )
    return result


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if len(sys.argv) < 3:
        print("Usage: python align.py <path_to_wav> <path_to_lyrics_txt>")
        sys.exit(1)

    wav   = sys.argv[1]
    lyrics_file = sys.argv[2]

    with open(lyrics_file, "r", encoding="utf-8") as f:
        lyrics_text = f.read()

    def progress(stage, pct):
        print(f"  [{pct:3d}%] {stage}")

    print(f"Aligning: {wav}")
    result = align_track(wav_path=wav, lyrics=lyrics_text, on_progress=progress)

    print(f"\nResult: {len(result.words)} words | fallback={result.used_fallback}")
    print(json.dumps(result.to_dict(), indent=2)[:2000], "...")