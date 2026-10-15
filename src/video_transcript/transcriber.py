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
DEFAULT_BATCH_SIZE = 8


def sanitize_proxy_env() -> None:
    # httpx (used by huggingface_hub to download Whisper models) crashes
    # parsing bracketed IPv6 entries like [::1] in NO_PROXY/no_proxy
    # ("Invalid port: ':1]'"). Drop those entries and keep the rest.
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val:
            os.environ[var] = ",".join(p for p in val.split(",") if "[" not in p)


def load_audio(path: Path, sample_rate: int = SAMPLE_RATE) -> "np.ndarray":
    """Decode any audio/video file to mono float32 PCM with ffmpeg.

    We decode ourselves instead of letting faster-whisper do it: its decoder
    calls av.open(..., metadata_errors=...), which PyAV 13+ removed, and older
    PyAV has no wheels for current Python. ffmpeg is already required by
    yt-dlp, so this adds no dependency.
    """
    import numpy as np

    cmd = [
        "ffmpeg", "-nostdin", "-v", "error", "-i", str(path),
        "-f", "s16le", "-ac", "1", "-ar", str(sample_rate), "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True).stdout
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found; install it and make sure it's on your PATH")
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg could not decode {path}: {e.stderr.decode(errors='replace')}")
    return np.frombuffer(out, np.int16).astype(np.float32) / 32768.0


def transcribe(
    audio_path: Path,
    model_size: str = "small",
    language: Optional[str] = None,
    device: str = "auto",
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[Iterator[Segment], str, float, float]:
    """Return (segments, language, language_probability, audio_seconds).

    Segments are yielded lazily as Whisper produces them. batch_size > 1
    transcribes several speech chunks at once (much faster); 1 runs them one
    after another, the way Whisper does by default.
    """
    sanitize_proxy_env()
    # Hide huggingface_hub's "unauthenticated requests" nag; models are public.
    from huggingface_hub.utils import logging as hf_logging
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    hf_logging.set_verbosity_error()

    # "auto" picks the fastest type the device supports (int8 on most CPUs,
    # float16 on NVIDIA GPUs).
    model = WhisperModel(model_size, device=device, compute_type="auto")
    options = dict(
        beam_size=5,
        language=language,
        # Skip silence and music; Whisper tends to invent text there.
        vad_filter=True,
    )
    if batch_size > 1:
        # Batched mode skips timestamp prediction by default, which would
        # make each .srt cue a ~30s chunk. Keep sentence-level timing.
        raw_segments, info = BatchedInferencePipeline(model).transcribe(
            load_audio(audio_path), batch_size=batch_size, without_timestamps=False, **options,
        )
    else:
        raw_segments, info = model.transcribe(load_audio(audio_path), **options)
    segments = (
        Segment(start=s.start, end=s.end, text=s.text.strip()) for s in raw_segments
    )
    return segments, info.language, info.language_probability, info.duration
