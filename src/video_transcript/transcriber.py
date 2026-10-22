"""Speech-to-text with faster-whisper (runs locally, no API key)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Optional

from .formats import Segment

if TYPE_CHECKING:
    import numpy as np

SAMPLE_RATE = 16_000  # what Whisper expects
# Batching (> 1) is about 2x faster on CPU but occasionally drops a phrase,
# so it's opt-in; the default keeps Whisper's slower, more careful pass.
DEFAULT_BATCH_SIZE = 1

# Whisper's own language detection only listens to the first 30 seconds, so
# an intro, music or a bad first clip decides the language for the whole
# file. We listen to several spots spread across the audio instead.
LANGUAGE_SAMPLES = 5
SAMPLE_SECONDS = 60
MIN_SPEECH_SECONDS = 2
# Below this, the CLI tells the user to pass -l.
LOW_LANGUAGE_CONFIDENCE = 0.6


def sanitize_proxy_env() -> None:
    # httpx (used by huggingface_hub to download Whisper models) crashes
    # parsing bracketed IPv6 entries like [::1] in NO_PROXY/no_proxy
    # ("Invalid port: ':1]'"). Drop those entries and keep the rest.
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val:
            os.environ[var] = ",".join(p for p in val.split(",") if "[" not in p)


def _run_ffmpeg_tool(cmd: list[str], path: Path) -> bytes:
    try:
        return subprocess.run(cmd, capture_output=True, check=True).stdout
    except FileNotFoundError:
        raise RuntimeError(f"{cmd[0]} not found; install ffmpeg and make sure it's on your PATH")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"{cmd[0]} could not decode {path}: {e.stderr.decode(errors='replace')}")


def load_audio(
    path: Path,
    sample_rate: int = SAMPLE_RATE,
    start: Optional[float] = None,
    length: Optional[float] = None,
) -> "np.ndarray":
    """Decode any audio/video file to mono float32 PCM with ffmpeg.

    start and length (seconds) decode just one clip instead of the whole file.

    We decode ourselves instead of letting faster-whisper do it: its decoder
    calls av.open(..., metadata_errors=...), which PyAV 13+ removed, and older
    PyAV has no wheels for current Python. ffmpeg is already required by
    yt-dlp, so this adds no dependency.
    """
    import numpy as np

    trim = []
    if start is not None:
        trim += ["-ss", str(start)]
    if length is not None:
        trim += ["-t", str(length)]
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", *trim, "-i", str(path),
        "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "-",
    ]
    out = _run_ffmpeg_tool(cmd, path)
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def audio_duration(path: Path) -> float:
    """Length of an audio/video file in seconds, from ffprobe (ships with ffmpeg)."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
    ]
    return float(_run_ffmpeg_tool(cmd, path).decode().strip())


def sample_starts(
    duration: float, samples: int = LANGUAGE_SAMPLES, window: float = SAMPLE_SECONDS,
) -> list[float]:
    """Start times (seconds) of the clips used to detect the language.

    The clips sit in the middle of equal slices of the audio, so the very
    start and end (intros, outros) count no more than any other spot.
    """
    if duration <= window:
        return [0.0]
    samples = max(1, min(samples, int(duration // window)))
    slice_len = duration / samples
    return [
        min(max(0.0, slice_len * (i + 0.5) - window / 2), duration - window)
        for i in range(samples)
    ]


def pick_language(
    distributions: list[list[tuple[str, float]]],
) -> tuple[str, float]:
    """Combine per-clip language probabilities into (language, confidence).

    Each clip gives a probability for every language. The winner has the
    highest average across clips, and that average is the confidence, so a
    language that wins only some clips gets a low score.
    """
    totals: dict[str, float] = {}
    for dist in distributions:
        for lang, prob in dist:
            totals[lang] = totals.get(lang, 0.0) + prob
    language = max(totals, key=totals.__getitem__)
    return language, totals[language] / len(distributions)


def detect_language(model, audio_path: Path) -> Optional[tuple[str, float]]:
    """Detect the spoken language from clips across the whole audio.

    Returns (language, confidence), or None if no clip had enough speech
    or the length is unknown.
    Each clip is decoded on its own, before the full audio is loaded, so
    detection adds almost nothing to peak memory (a 4-hour video already
    needs over 12 GB).
    """
    import numpy as np
    from faster_whisper.vad import collect_chunks, get_speech_timestamps

    try:
        duration = audio_duration(audio_path)
    except ValueError:  # ffprobe printed no usable duration
        return None
    distributions = []
    for start in sample_starts(duration):
        clip = load_audio(audio_path, start=start, length=SAMPLE_SECONDS)
        speech = get_speech_timestamps(clip)
        if sum(c["end"] - c["start"] for c in speech) < MIN_SPEECH_SECONDS * SAMPLE_RATE:
            continue
        chunks, _ = collect_chunks(clip, speech)
        _, _, probs = model.detect_language(audio=np.concatenate(chunks))
        distributions.append(probs)
    return pick_language(distributions) if distributions else None


def transcribe(
    audio_path: Path,
    model_size: str = "small",
    language: Optional[str] = None,
    device: str = "auto",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[Iterator[Segment], str, float, float]:
    """Return (segments, language, language_probability, audio_seconds).

    Without a language, it's detected from several clips across the audio
    (see detect_language) and language_probability is that confidence.

    Segments are yielded lazily as Whisper produces them. batch_size > 1
    transcribes several speech chunks at once (about 2x faster on CPU, but it
    can occasionally skip a phrase); 1 runs them one after another, the way
    Whisper does by default.
    """
    sanitize_proxy_env()
    # Hide huggingface_hub's "unauthenticated requests" nag; models are public.
    from huggingface_hub.utils import logging as hf_logging
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    hf_logging.set_verbosity_error()

    # "auto" picks the fastest type the device supports (int8 on most CPUs,
    # float16 on NVIDIA GPUs).
    model = WhisperModel(model_size, device=device, compute_type="auto")
    detected = None
    if language is None and model.model.is_multilingual:
        detected = detect_language(model, audio_path)
        if detected:
            language = detected[0]
    # The audio goes in inline and the options as plain keywords (not
    # **options), so faster-whisper holds the only reference to the full
    # audio and frees it once it has cut out the silence. On a 4-hour video
    # that takes about 1 GB off the memory peak.
    # vad_filter skips silence and music; Whisper tends to invent text there.
    if batch_size > 1:
        # Batched mode skips timestamp prediction by default, which would
        # make each .srt cue a ~30s chunk. Keep sentence-level timing.
        raw_segments, info = BatchedInferencePipeline(model).transcribe(
            load_audio(audio_path), beam_size=5, language=language, vad_filter=True,
            batch_size=batch_size, without_timestamps=False,
        )
    else:
        raw_segments, info = model.transcribe(
            load_audio(audio_path), beam_size=5, language=language, vad_filter=True,
        )
    segments = (
        Segment(start=s.start, end=s.end, text=s.text.strip()) for s in raw_segments
    )
    if detected:
        return segments, detected[0], detected[1], info.duration
    return segments, info.language, info.language_probability, info.duration
