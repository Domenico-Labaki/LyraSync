"""
align.py — LyraSync
Two-stage local ML alignment pipeline:
  1. Demucs         — vocal source separation (htdemucs)
  2. faster-whisper — ASR transcription with word-level timestamps
  3. Two-pass matcher:
       Pass 1 — assign each lyric line to its best Whisper segment
                using monotone DP on token-overlap scores.
       Pass 2 — within each assigned segment, run Needleman-Wunsch
                token alignment against that segment's word list to snap
                line boundaries to real word timestamps rather than
                dividing segment time evenly.

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
import soundfile as sf

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

WHISPER_MODEL_SIZE = "base.en"
DEMUCS_MODEL       = "htdemucs"
TARGET_SR          = 16_000   # Hz — whisper expects 16 kHz

# Minimum token-overlap ratio for Pass 1 segment assignment (0–1).
# Kept deliberately low — NW in Pass 2 handles precision; this just needs
# to point each line at the right segment window.
ASSIGN_THRESHOLD = 0.25

# Base segment window used when computing the adaptive window per alignment run.
# The actual window is scaled up when Whisper produces far fewer segments than
# lyric lines (heavy merging), so lines aren't silently dropped just because
# Whisper packed two song sections into one segment.
SEGMENT_WINDOW_BASE = 3

# NW scoring weights (Pass 2)
NW_MATCH    =  2    # reward for a matching token pair
NW_MISMATCH = -1    # penalty for a substituted token pair
NW_GAP      = -1    # penalty for inserting a gap (skipped token on either side)


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

    # Free Demucs from memory before loading Whisper
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

    Returns a list of segments, each with word-level timestamps:
      [
        {
          "text":  "taking a deep breath I feel fine",
          "start": 8.98,
          "end":   20.31,
          "words": [
            { "word": "taking", "start": 8.98,  "end": 9.54,  "probability": 0.92 },
            ...
          ]
        },
        ...
      ]

    VAD tuning notes:
      - min_silence_duration_ms=100: catches the short inter-phrase gaps
        common in sung music (vs 400ms which merges entire sections).
      - threshold=0.35: lower than the default 0.5 so quieter vocal
        pauses still register as silence boundaries.
      - condition_on_previous_text=False: prevents Whisper from using
        prior segment text as a prompt, which otherwise causes it to
        hallucinate continuation across chorus repeats.
      - word_timestamps=True: required for Pass 2 NW alignment; each
        segment now carries a .words list with per-word start/end times.
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
        word_timestamps            = True,    # enables Pass 2 NW alignment
        vad_filter                 = True,
        vad_parameters             = {
            "min_silence_duration_ms": 100,   # catches short sung pauses
            "threshold":               0.35,  # more sensitive to quiet gaps
        },
        condition_on_previous_text = False,   # prevents context bleeding across repeats
    )

    segments = []
    for seg in segments_iter:
        text = seg.text.strip()
        if not text:
            continue

        # Normalise word objects to plain dicts and clamp timestamps within
        # the segment's own boundaries to guard against Whisper jitter.
        words = []
        for w in (seg.words or []):
            word_text = w.word.strip()
            if not word_text:
                continue
            words.append({
                "word":        word_text,
                "start":       round(max(w.start, seg.start), 3),
                "end":         round(min(w.end,   seg.end),   3),
                "probability": round(w.probability, 3),
            })

        segments.append({
            "text":  text,
            "start": round(seg.start, 3),
            "end":   round(seg.end,   3),
            "words": words,
        })

    del model
    gc.collect()

    _progress(on_progress, "Transcription complete", 60)
    logger.info(f"Whisper returned {len(segments)} segments")
    logger.info("=== Whisper segments ===")
    for s in segments:
        logger.info(f"  [{s['start']:.2f} → {s['end']:.2f}] {s['text']}")
    logger.info(f"=== End ({len(segments)} segments) ===")
    return segments


# ── Shared text helpers ───────────────────────────────────────────────────────

def _normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, return token list."""
    return re.sub(r"[^a-z0-9\s]", "", text.lower()).split()


def _token_overlap(a: str, b: str) -> float:
    """
    Jaccard-like token overlap between two strings, sized against the
    larger token set.  Used in Pass 1 for coarse segment assignment.

    Returns 0.0–1.0.
    """
    ta = set(_normalize(a))
    tb = set(_normalize(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


# ── Pass 1: assign each lyric line to a Whisper segment ──────────────────────

def _assign_lines_to_segments(
    lyric_lines:    list[str],
    segments:       list[dict],
    sorted_targets: list[int],
    window:         int,
) -> list[Optional[int]]:
    """
    Assign each lyric line to the index of its best matching Whisper segment,
    or None if no segment clears ASSIGN_THRESHOLD.

    Two-step process that separates two distinct concerns:

    Step A — strict monotone DP (k < j):
        Each line maps to a segment strictly later than its predecessor.
        This is the classical LCS-style alignment and guarantees that
        the assignment sequence is non-decreasing in segment index, which
        means the output timestamps are always forward in time.
        Repeated lyric phrases (chorus) are handled correctly because the
        DP consumes one segment per "slot" — each chorus occurrence is
        routed to its own matching segment in order.

    Step B — same-segment sharing pass:
        After the DP, any lyric line that was left UNMATCHED (None) and
        whose immediate neighbours are both assigned to the *same* segment
        is pulled into that segment if its score there clears the threshold.
        This handles the case where Whisper merged an entire stanza into one
        long segment — multiple lines that the strict DP couldn't fit into
        separate segments can share the segment and are later subdivided by
        the NW pass in Pass 2.

    Why strict k < j (not k ≤ j):
        Allowing k ≤ j means "line i can go to segment j even if line i-1
        was already assigned to segment j".  In isolation that sounds like
        it enables sharing, but it also destroys the ordering guarantee:
        line 31 (near the end of the song) can freely jump back to segment 3
        (first chorus, ~43s) because the DP has no way to know that line 30
        was just assigned to a segment at ~149s.  The traceback records which
        column won, but not which *time* that column represents relative to
        the overall path.  Strict k < j prevents this entirely.

    SKIP_PENALTY (> 1.0, the max single-line score) ensures the DP never
    deliberately defers a matchable line to a later segment.

    Returns a list of length n_lines, each element a segment index or None.
    """
    n_lines = len(lyric_lines)
    n_segs  = len(segments)

    # Build score matrix up front
    scores = [
        [_token_overlap(lyric_lines[i], segments[j]["text"]) for j in range(n_segs)]
        for i in range(n_lines)
    ]

    NEG_INF       = float("-inf")
    SKIP_PENALTY  = 1.5           # > max possible score gain from deferring
    UNMATCHED     = n_segs        # virtual "no assignment" column
    NCOLS         = n_segs + 1

    dp   = [[NEG_INF] * NCOLS for _ in range(n_lines)]
    back = [[None]    * NCOLS for _ in range(n_lines)]

    # ── Step A base row (line 0) ──────────────────────────────────────────
    dp[0][UNMATCHED] = -SKIP_PENALTY
    for j in range(n_segs):
        sc = scores[0][j]
        if sc >= ASSIGN_THRESHOLD and abs(j - sorted_targets[0]) <= window:
            dp[0][j] = sc

    # ── Step A fill ───────────────────────────────────────────────────────
    for i in range(1, n_lines):
        # Option A — skip line i (inherit best from any prior state)
        best_prev_val, best_prev_col = NEG_INF, UNMATCHED
        for k in range(NCOLS):
            if dp[i - 1][k] > best_prev_val:
                best_prev_val = dp[i - 1][k]
                best_prev_col = k

        if best_prev_val > NEG_INF:
            dp[i][UNMATCHED]   = best_prev_val - SKIP_PENALTY
            back[i][UNMATCHED] = best_prev_col

        # Option B — assign line i to segment j.
        # STRICT k < j: predecessor must come from a strictly earlier
        # segment column, or from UNMATCHED (no segment yet consumed).
        # This is the invariant that prevents backwards time jumps.
        for j in range(n_segs):
            sc = scores[i][j]
            if sc < ASSIGN_THRESHOLD:
                continue
            # Reject segments outside this line's allowed window.
            # sorted_targets[i] is the pre-sort target segment; the adaptive
            # window allows minor VAD jitter without permitting cross-section jumps.
            if abs(j - sorted_targets[i]) > window:
                continue

            bv, bc = NEG_INF, None

            # From UNMATCHED (no positional constraint)
            if dp[i - 1][UNMATCHED] > bv:
                bv, bc = dp[i - 1][UNMATCHED], UNMATCHED

            # From any matched column k strictly before j
            for k in range(j):
                if dp[i - 1][k] > bv:
                    bv, bc = dp[i - 1][k], k

            if bv > NEG_INF:
                candidate = bv + sc
                if candidate > dp[i][j]:
                    dp[i][j]   = candidate
                    back[i][j] = bc

    # ── Step A traceback ──────────────────────────────────────────────────
    assignments: list[Optional[int]] = [None] * n_lines

    best_final, cur_col = NEG_INF, UNMATCHED
    for k in range(NCOLS):
        if dp[n_lines - 1][k] > best_final:
            best_final = dp[n_lines - 1][k]
            cur_col    = k

    for i in range(n_lines - 1, -1, -1):
        assignments[i] = None if cur_col == UNMATCHED else cur_col
        prev = back[i][cur_col]
        if prev is None:
            break
        cur_col = prev

    # ── Step B: same-segment sharing pass ────────────────────────────────
    # Pull unmatched lines into a neighbouring segment when both surrounding
    # matched lines point to the same segment index (i.e. the unmatched line
    # sits inside a gap that a single long segment spans).
    for i in range(n_lines):
        if assignments[i] is not None:
            continue

        # Find nearest matched neighbours
        prev_seg = next((assignments[k] for k in range(i - 1, -1, -1) if assignments[k] is not None), None)
        next_seg = next((assignments[k] for k in range(i + 1,  n_lines) if assignments[k] is not None), None)

        # Share only when BOTH neighbours point to the same segment.
        # Do NOT pull toward a one-sided neighbour: tail/lead lines are
        # better handled by forward-only fallback interpolation.
        if (prev_seg is not None
                and prev_seg == next_seg
                and scores[i][prev_seg] >= ASSIGN_THRESHOLD):
            assignments[i] = prev_seg

    logger.info("=== Pass 1 assignments ===")
    for i, j in enumerate(assignments):
        seg_label = f"seg[{j}] {segments[j]['start']:.2f}→{segments[j]['end']:.2f}" if j is not None else "UNMATCHED"
        logger.info(f"  line[{i:2d}] → {seg_label}  | {lyric_lines[i]!r}")
    logger.info("=== End Pass 1 ===")

    return assignments


# ── Pass 2: NW token alignment within a segment window ───────────────────────

def _nw_align_tokens(
    lyric_tokens: list[str],
    word_tokens:  list[str],
) -> list[Optional[int]]:
    """
    Needleman-Wunsch global alignment between two token sequences.

    lyric_tokens — normalised tokens from a lyric line
    word_tokens  — normalised tokens from the Whisper word list

    Returns a list of length len(lyric_tokens), where each element is
    the index into word_tokens that the lyric token was aligned to, or
    None if the lyric token was aligned to a gap (no corresponding word).

    NW is O(m*n) in time and space.  For a single song the token counts
    are small (typically ≤ 20 per line vs ≤ 100 words in a segment),
    so this is negligible.
    """
    m = len(lyric_tokens)
    n = len(word_tokens)

    if m == 0 or n == 0:
        return [None] * m

    # Build DP table
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(1, m + 1):
        dp[i][0] = i * NW_GAP
    for j in range(1, n + 1):
        dp[0][j] = j * NW_GAP

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            match_score = NW_MATCH if lyric_tokens[i - 1] == word_tokens[j - 1] else NW_MISMATCH
            dp[i][j] = max(
                dp[i - 1][j - 1] + match_score,   # align
                dp[i - 1][j    ] + NW_GAP,         # lyric token gapped
                dp[i    ][j - 1] + NW_GAP,         # word  token gapped
            )

    # Traceback
    aligned_to: list[Optional[int]] = []
    i, j = m, n
    path: list[tuple[int, Optional[int]]] = []   # (lyric_idx, word_idx | None)

    while i > 0 or j > 0:
        if i == 0:
            j -= 1                          # consume remaining word tokens
            continue
        if j == 0:
            path.append((i - 1, None))      # lyric token with no word match
            i -= 1
            continue

        match_score = NW_MATCH if lyric_tokens[i - 1] == word_tokens[j - 1] else NW_MISMATCH

        if dp[i][j] == dp[i - 1][j - 1] + match_score:
            path.append((i - 1, j - 1))
            i -= 1; j -= 1
        elif dp[i][j] == dp[i - 1][j] + NW_GAP:
            path.append((i - 1, None))
            i -= 1
        else:
            j -= 1

    path.reverse()
    # path may contain each lyric index exactly once; reconstruct as list
    result: list[Optional[int]] = [None] * m
    for lyric_idx, word_idx in path:
        result[lyric_idx] = word_idx

    return result


def _timestamps_from_nw(
    lyric_lines_in_seg: list[str],
    words:              list[dict],
    seg_start:          float,
    seg_end:            float,
) -> list[tuple[float, float, float]]:
    """
    Given the lyric lines assigned to one segment and that segment's word
    list, use NW to find where each line's tokens fall in the word stream,
    then derive (start, end, confidence) for each line.

    Strategy:
      1. Flatten all lyric lines in this segment into a single token list,
         remembering the boundary indices between lines.
      2. Run NW against the segment's normalised word tokens.
      3. For each line, find the first and last word it was aligned to;
         use those words' timestamps as the line's start/end.
      4. Confidence = fraction of lyric tokens that got a word match
         (as opposed to a gap alignment).

    Falls back to even time-division if NW produces no alignments for a
    line (can happen when ASR hallucinated entirely different words).

    Returns a list of (start, end, confidence) tuples, one per input line.
    """
    # Flatten lyric tokens and record per-line boundaries
    all_lyric_tokens: list[str] = []
    line_boundaries:  list[tuple[int, int]] = []   # (token_start, token_end) inclusive

    for line in lyric_lines_in_seg:
        toks = _normalize(line)
        start_idx = len(all_lyric_tokens)
        all_lyric_tokens.extend(toks)
        end_idx = len(all_lyric_tokens) - 1
        line_boundaries.append((start_idx, end_idx))

    # Normalised word tokens from this segment
    word_tokens = [_normalize(w["word"])[0] if _normalize(w["word"]) else "" for w in words]

    # Run NW on the full concatenated token stream vs word stream
    alignment = _nw_align_tokens(all_lyric_tokens, word_tokens)

    results: list[tuple[float, float, float]] = []
    n_lines  = len(lyric_lines_in_seg)

    for line_idx, (tok_start, tok_end) in enumerate(line_boundaries):
        # Collect the word indices this line's tokens were aligned to
        matched_word_indices = [
            alignment[t]
            for t in range(tok_start, tok_end + 1)
            if alignment[t] is not None
        ]

        n_tokens  = max(tok_end - tok_start + 1, 1)
        n_matched = len(matched_word_indices)
        confidence = round(n_matched / n_tokens, 3)

        if matched_word_indices:
            # Use the earliest matched word's start and the latest's end
            first_word = words[min(matched_word_indices)]
            last_word  = words[max(matched_word_indices)]
            line_start = first_word["start"]
            line_end   = last_word["end"]
        else:
            # NW found no word for any token in this line — fall back to
            # even time-slice within the segment
            slice_dur  = (seg_end - seg_start) / n_lines
            line_start = round(seg_start + line_idx * slice_dur, 3)
            line_end   = round(line_start + slice_dur, 3)
            confidence = 0.0

        results.append((round(line_start, 3), round(line_end, 3), confidence))

    # Enforce monotonicity: a line's start must be ≥ the previous line's end.
    # NW alignment within a shared segment can occasionally produce small
    # overlaps when two lines match words that are very close together.
    for i in range(1, len(results)):
        prev_end  = results[i - 1][1]
        cur_start, cur_end, conf = results[i]
        if cur_start < prev_end:
            cur_start = prev_end
            cur_end   = max(cur_end, cur_start)
        results[i] = (cur_start, cur_end, conf)

    return results


# ── Stage 3: two-pass matching ────────────────────────────────────────────────

def _match_lines_to_segments(
    lyric_lines: list[str],
    segments:    list[dict],
    duration:    float,
) -> tuple[list[dict], bool]:
    """
    Assign a (start, end, confidence) timestamp to every lyric line.

    Pass 1 — _assign_lines_to_segments:
        Monotone DP scores every (line, segment) pair by token overlap,
        then finds the globally optimal monotone assignment.  The same
        segment index may be assigned to multiple consecutive lines
        (a Whisper segment that covers an entire chorus stanza), and
        repeated lyric lines (chorus repeats) are routed to different
        segment occurrences by the temporal progression of the DP.

    Pass 2 — _timestamps_from_nw:
        For each segment that has ≥1 assigned line, run Needleman-Wunsch
        on the concatenated lyric tokens vs the segment's Whisper word
        list.  This locates each line's token span within the word stream
        and reads off real word-level timestamps instead of dividing the
        segment duration evenly.

    Fallback:
        Lines left unassigned by Pass 1 (confidence below threshold, or
        no viable segment) are linearly interpolated between the nearest
        matched neighbours.  A synthetic 2-second step is used when the
        neighbours collapse to the same timestamp (degenerate gap).

    Returns (sentences, used_fallback).
    """
    n_lines = len(lyric_lines)
    n_segs  = len(segments)

    # ── Edge case: no segments ────────────────────────────────────────────
    if n_segs == 0:
        logger.warning("No Whisper segments — distributing lines evenly across duration")
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

    # ── Pre-sort lyrics into temporal order ──────────────────────────────
    # The DP assumes lyric lines arrive in song order.  Scraped lyrics are
    # often misordered (chorus block duplicated at the end, bridge out of
    # place, etc.).  We sort lines into temporal order before the DP, then
    # restore the original index order in the output.
    #
    # The naive approach — sort each line by its single highest-scoring
    # segment — breaks for repeated phrases like a chorus: every occurrence
    # of "Everything is getting better" scores identically on the first
    # matching segment, so they all sort to the same position and the DP
    # burns that segment on the first occurrence, leaving the rest unmatched.
    #
    # Instead we use occurrence-aware assignment:
    #   1. Build a list of candidate segments for each line (all segments
    #      that score >= ASSIGN_THRESHOLD), sorted by segment index.
    #   2. Group lines by their normalised text.  Within each group, assign
    #      the Nth line (in original lyric order) to the Nth candidate
    #      segment pool slot.  This maps the first chorus occurrence to the
    #      first matching segment, the second to the second, etc.
    #   3. Sort all lines by their assigned segment index.  Lines with no
    #      candidate (below threshold everywhere) sort to the end.
    raw_scores = [
        [_token_overlap(line, seg["text"]) for seg in segments]
        for line in lyric_lines
    ]

    # Candidate segments per line: indices where score >= threshold.
    candidates: list[list[int]] = [
        [j for j, s in enumerate(raw_scores[i]) if s >= ASSIGN_THRESHOLD]
        for i in range(n_lines)
    ]

    # ── Occurrence-aware target segment assignment ────────────────────────
    # Goal: sort lyric lines into temporal order so the DP sees them in song
    # sequence.  The challenge is repeated phrases — "What happened?" appears
    # three times but may only score above threshold on one Whisper segment.
    #
    # Strategy:
    #   1. Group lines by normalised text.  Within each group, distribute
    #      occurrences across matching segments in order (1st occurrence →
    #      1st candidate, 2nd → 2nd, etc.).
    #   2. For occurrences beyond the number of matching segments (the common
    #      case for short repeated phrases like "Hello, goodbye"), infer the
    #      target from lyric-order context: interpolate between the target
    #      segments of the nearest lines above and below that *do* have
    #      unique candidates.  This places excess occurrences at evenly spaced
    #      segment indices between their neighbours rather than all piling on
    #      the last known candidate.
    #   3. Lines with no candidates anywhere default to their lyric-order
    #      position fraction mapped onto the segment range.
    from collections import defaultdict

    norm_to_orig: dict[str, list[int]] = defaultdict(list)
    for i in range(n_lines):
        norm_to_orig[" ".join(_normalize(lyric_lines[i]))].append(i)

    target_seg: list[int] = [-1] * n_lines   # -1 = not yet assigned

    # Pass A: assign lines that have enough distinct candidates.
    # If a group has more occurrences than candidates, only assign the first
    # len(all_cands) occurrences — leave the rest at -1 so Pass B can
    # interpolate them between their neighbours instead of stacking them all
    # on the last candidate.  Stacking causes the DP to see multiple lines
    # targeting the same early segment while later sections go uncovered.
    for norm_text, group in norm_to_orig.items():
        all_cands = sorted({j for i in group for j in candidates[i]})
        if not all_cands:
            continue
        for rank, orig_idx in enumerate(group):
            if rank < len(all_cands):
                target_seg[orig_idx] = all_cands[rank]
            # else: leave at -1 → handled by Pass B interpolation

    # Pass B: fill -1 entries by interpolating between neighbouring anchors.
    # An "anchor" is any line with target_seg >= 0 after Pass A.
    # For a run of -1 lines between anchor_left (segment L) and anchor_right
    # (segment R), spread them evenly: pos k of m gap lines → round(L + (k+1)*(R-L)/(m+1))
    # Lines before the first anchor mirror the first anchor.
    # Lines after the last anchor mirror the last anchor.
    for i in range(n_lines):
        if target_seg[i] >= 0:
            continue
        # Find nearest anchors on each side
        left_seg  = next((target_seg[k] for k in range(i-1, -1, -1)      if target_seg[k] >= 0), None)
        right_seg = next((target_seg[k] for k in range(i+1,  n_lines)     if target_seg[k] >= 0), None)

        # Collect all -1 lines in this same gap
        gap = []
        for k in range(n_lines):
            if target_seg[k] >= 0:
                continue
            ls = next((target_seg[m] for m in range(k-1, -1, -1) if target_seg[m] >= 0), None)
            rs = next((target_seg[m] for m in range(k+1, n_lines)  if target_seg[m] >= 0), None)
            if ls == left_seg and rs == right_seg:
                gap.append(k)

        if i not in gap:
            gap = [i]

        pos = gap.index(i)
        m   = len(gap)

        if left_seg is None and right_seg is None:
            # No anchors at all — spread evenly across all segments
            target_seg[i] = round(pos * (n_segs - 1) / max(m - 1, 1)) if m > 1 else 0
        elif left_seg is None:
            target_seg[i] = max(0, right_seg - (m - pos))
        elif right_seg is None:
            target_seg[i] = min(n_segs - 1, left_seg + pos + 1)
        else:
            target_seg[i] = round(left_seg + (pos + 1) * (right_seg - left_seg) / (m + 1))

    # Sort line indices by target segment, breaking ties by original lyric
    # index to preserve relative order within a section.
    sorted_indices  = sorted(range(n_lines), key=lambda i: (target_seg[i], i))
    sorted_lines    = [lyric_lines[i] for i in sorted_indices]
    sorted_targets  = [target_seg[sorted_indices[pos]] for pos in range(n_lines)]
    restore = {pos: orig for pos, orig in enumerate(sorted_indices)}

    logger.info("=== Lyric pre-sort order ===")
    for pos, orig in enumerate(sorted_indices):
        logger.info(
            f"  pos[{pos:2d}] orig[{orig:2d}] target_seg={target_seg[orig]:2d}  "
            f"| {lyric_lines[orig]!r}"
        )
    logger.info("=== End pre-sort ===")

    # ── Pass 1: coarse assignment ─────────────────────────────────────────
    _progress_cb = _noop   # progress callback not threaded through here
    # Adaptive window: when Whisper merges aggressively (few segments relative
    # to lyric lines), a fixed window of 3 is too tight — lines fall through to
    # interpolation because their target segment is reachable but the DP won't
    # consider it.  Scale the window by the average lines-per-segment ratio so
    # that however densely or sparsely Whisper segmented the audio, each line
    # can always reach its neighbourhood of likely segments.
    #
    # Formula: max(BASE, ceil(n_lines / n_segs) + 1)
    # - 34 lines / 26 segs = 1.3 lines/seg  →  window = 3  (dense, keep tight)
    # - 40 lines /  8 segs = 5.0 lines/seg  →  window = 6  (sparse, open up)
    import math as _math
    adaptive_window = max(
        SEGMENT_WINDOW_BASE,
        _math.ceil(n_lines / n_segs) + 1,
    )
    logger.info(
        f"Adaptive window: {adaptive_window} "
        f"(n_lines={n_lines}, n_segs={n_segs}, base={SEGMENT_WINDOW_BASE})"
    )
    assignments_sorted = _assign_lines_to_segments(
        sorted_lines, segments, sorted_targets, adaptive_window
    )
    # Remap assignments back to original lyric indices
    assignments = [None] * n_lines
    for pos, orig in restore.items():
        assignments[orig] = assignments_sorted[pos]

    used_fallback = any(a is None for a in assignments)

    # ── Pass 2: NW timestamp refinement per segment ───────────────────────
    # Group lines by their assigned segment index
    seg_to_lines: dict[int, list[int]] = {}
    for line_idx, seg_idx in enumerate(assignments):
        if seg_idx is not None:
            seg_to_lines.setdefault(seg_idx, []).append(line_idx)

    # For each segment, compute NW-derived timestamps for all assigned lines
    # Key: line index → (start, end, confidence)
    timestamps: dict[int, tuple[float, float, float]] = {}

    for seg_idx, line_indices in seg_to_lines.items():
        seg    = segments[seg_idx]
        words  = seg.get("words", [])
        # Sort line_indices by their sorted (temporal) position so NW
        # receives lines in the order they appear in the song, not the
        # order they were originally typed in the lyrics file.
        line_indices = sorted(line_indices, key=lambda i: sorted_indices.index(i))
        lines  = [lyric_lines[i] for i in line_indices]

        if words:
            nw_results = _timestamps_from_nw(lines, words, seg["start"], seg["end"])
        else:
            # No word timestamps available (shouldn't happen with word_timestamps=True,
            # but guard anyway) — fall back to even division
            logger.warning(f"Segment {seg_idx} has no word timestamps; using even split")
            n = len(lines)
            slice_dur  = (seg["end"] - seg["start"]) / max(n, 1)
            nw_results = [
                (
                    round(seg["start"] + k * slice_dur, 3),
                    round(seg["start"] + (k + 1) * slice_dur, 3),
                    0.0,
                )
                for k in range(n)
            ]

        for line_idx, (start, end, conf) in zip(line_indices, nw_results):
            timestamps[line_idx] = (start, end, conf)

        logger.info(f"  seg[{seg_idx}] {seg['start']:.2f}→{seg['end']:.2f}: "
                    f"assigned {len(line_indices)} lines, NW complete")

    # ── Build output, interpolating unmatched lines ───────────────────────
    sentences: list[dict] = []

    for i, line in enumerate(lyric_lines):
        if i in timestamps:
            start, end, conf = timestamps[i]
        else:
            # Interpolate between the nearest matched neighbours
            prev_end = next(
                (timestamps[k][1] for k in range(i - 1, -1, -1) if k in timestamps),
                0.0,
            )
            next_start = next(
                (timestamps[k][0] for k in range(i + 1, n_lines) if k in timestamps),
                duration,
            )

            # Collect all consecutive unmatched lines in this gap
            gap_lines = [
                k for k in range(n_lines)
                if k not in timestamps
                and next(
                    (timestamps[m][1] for m in range(k - 1, -1, -1) if m in timestamps),
                    0.0,
                ) == prev_end
                and next(
                    (timestamps[m][0] for m in range(k + 1, n_lines) if m in timestamps),
                    duration,
                ) == next_start
            ]
            if i not in gap_lines:
                gap_lines = [i]

            pos   = gap_lines.index(i)
            n_gap = len(gap_lines)

            if prev_end >= next_start:
                # Degenerate gap — use a synthetic 2-second spacing
                step  = 2.0
                start = round(prev_end + pos * step, 3)
                end   = round(start + step, 3)
            else:
                step  = (next_start - prev_end) / n_gap
                start = round(prev_end + pos * step, 3)
                end   = round(min(start + step, next_start), 3)

            conf = 0.0

        sentences.append({
            "line":       line,
            "start":      start,
            "end":        end,
            "confidence": conf,
        })

    # ── Final monotonicity clamp ─────────────────────────────────────────
    # Regardless of what the DP, NW, or fallback produced, timestamps must
    # never go backwards.  Walk the sentences in order and clamp any start
    # that precedes the previous end forward to that end.  Duration is
    # preserved where possible; when a line's own end is also before the
    # cursor, collapse it to a zero-duration point at the cursor (visible
    # in confidence=0 lines — the karaoke display can treat these as
    # instant flashes rather than causing a rewind).
    cursor = 0.0
    for s in sentences:
        if s["start"] < cursor:
            original_dur = max(s["end"] - s["start"], 0.0)
            s["start"]  = round(cursor, 3)
            s["end"]    = round(cursor + original_dur, 3)
            s["confidence"] = min(s["confidence"], 0.0)
            used_fallback = True
        cursor = max(cursor, s["end"])

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
        lyrics:      Newline-separated lyric lines from Electron.
        on_progress: Optional callback(stage: str, pct: int).

    Returns:
        AlignmentResult — one sentence entry per lyric line.

    Raises:
        FileNotFoundError: If wav_path does not exist.
        ValueError:        If lyrics string contains no non-empty lines.
        RuntimeError:      If transcription returns nothing.
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