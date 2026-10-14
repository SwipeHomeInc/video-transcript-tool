"""Transcript output formats. Pure functions, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class Segment:
    start: float  # seconds
    end: float  # seconds
    text: str


def _timestamp(seconds: float, sep: str) -> str:
    # Round to whole milliseconds first so 1.9996s becomes 00:00:02,000
    # instead of an invalid 00:00:01,1000.
    total_ms = max(0, round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def srt_timestamp(seconds: float) -> str:
    return _timestamp(seconds, ",")


def vtt_timestamp(seconds: float) -> str:
    return _timestamp(seconds, ".")


def to_txt(segments: Iterable[Segment]) -> str:
    return "".join(f"{seg.text}\n" for seg in segments)


def to_srt(segments: Iterable[Segment]) -> str:
    return "".join(
        f"{i}\n{srt_timestamp(seg.start)} --> {srt_timestamp(seg.end)}\n{seg.text}\n\n"
        for i, seg in enumerate(segments, 1)
    )


def to_vtt(segments: Iterable[Segment]) -> str:
    cues = "".join(
        f"{vtt_timestamp(seg.start)} --> {vtt_timestamp(seg.end)}\n{seg.text}\n\n"
        for seg in segments
    )
    return "WEBVTT\n\n" + cues


FORMATTERS: dict[str, Callable[[Iterable[Segment]], str]] = {
    "txt": to_txt,
    "srt": to_srt,
    "vtt": to_vtt,
}
