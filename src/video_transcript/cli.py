"""Command-line entry point: `video-transcript <url>`."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .formats import FORMATTERS


def parse_formats(value: str) -> list[str]:
    formats = [f.strip().lower() for f in value.split(",") if f.strip()]
    unknown = [f for f in formats if f not in FORMATTERS]
    if unknown or not formats:
        raise argparse.ArgumentTypeError(
            f"unknown format(s): {', '.join(unknown) or '(none)'}; "
            f"choose from {', '.join(FORMATTERS)}"
        )
    return formats


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="video-transcript",
        description="Word-for-word transcript of any video URL (X, YouTube, Vimeo, ...).",
    )
    p.add_argument("url", help="video URL (anything yt-dlp can download)")
    p.add_argument("-o", "--output-dir", type=Path, default=Path("out"),
                   help="where transcripts and cached audio go (default: out)")
    p.add_argument("-m", "--model", default="small",
                   help="Whisper model: tiny, base, small, medium, large-v3, turbo "
                        "(default: small)")
    p.add_argument("-f", "--format", type=parse_formats, default=["txt", "srt"],
                   dest="formats", metavar="FORMATS",
                   help="comma-separated: txt,srt,vtt (default: txt,srt)")
    p.add_argument("-l", "--language", default=None,
                   help="spoken language code, e.g. en (default: auto-detect)")
    p.add_argument("--device", default="auto", choices=["auto", "cpu", "cuda"],
                   help="where to run Whisper (default: auto)")
    p.add_argument("-q", "--quiet", action="store_true",
                   help="don't print the transcript as it's produced")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show yt-dlp's full download log")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="use your logged-in session from this browser (chrome, firefox, "
                        "safari, edge, ...) for videos that need an account")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _use_color() -> bool:
    # https://no-color.org
    return sys.stderr.isatty() and not os.environ.get("NO_COLOR")


def _style(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


class _Progress:
    """One-line download progress on stderr (redrawn in place on a terminal)."""

    WIDTH = 24

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self.tty = sys.stderr.isatty()
        self.shown = False

    def __call__(self, done: int, total: Optional[int]) -> None:
        if not self.enabled or not self.tty:
            return
        if total:
            frac = min(done / total, 1.0)
            filled = int(frac * self.WIDTH)
            bar = (_style("\u2588" * filled, "36", _use_color())
                   + _style("\u2591" * (self.WIDTH - filled), "2", _use_color()))
            line = f"  {bar} {frac:4.0%}  {_fmt_bytes(done)}"
        else:
            line = f"  {_fmt_bytes(done)}"
        sys.stderr.write("\r" + line + "\033[K")
        sys.stderr.flush()
        self.shown = True

    def finish(self) -> None:
        if self.shown:
            sys.stderr.write("\n")
            sys.stderr.flush()


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # Never crash on a transcript character the console encoding can't show
    # (e.g. Windows cp1252 when output is redirected).
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    from .download import DownloadFailed, download_audio
    from .transcriber import transcribe

    color = _use_color()

    def status(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    def step(msg: str) -> None:
        status(_style("\u25b8 ", "1;36", color) + _style(msg, "1", color))

    def detail(msg: str) -> None:
        status(_style(f"  {msg}", "2", color))

    started = time.monotonic()
    step("Fetching audio")
    progress = _Progress(enabled=not args.verbose)
    try:
        audio_path, info = download_audio(
            args.url, args.output_dir, verbose=args.verbose, on_progress=progress,
            cookies_from_browser=args.cookies_from_browser,
        )
    except DownloadFailed as e:
        progress.finish()
        status(_style("\u2717 ", "1;31", color) + str(e))
        return 1
    progress.finish()
    title = info.get("title")
    # Direct file links have no real title, just the filename (== the ID).
    if title and title != info.get("id"):
        detail(f'"{title}"')

    step(f"Transcribing with Whisper ({args.model})")
    segments_iter, language, prob, audio_seconds = transcribe(
        audio_path, model_size=args.model, language=args.language, device=args.device,
    )
    detail(f"{_fmt_duration(audio_seconds)} of audio \u00b7 language: {language} "
           f"({prob:.0%} sure)")
    status("")

    segments = []
    for seg in segments_iter:
        segments.append(seg)
        if not args.quiet:
            print(seg.text, flush=True)

    written = []
    for fmt in args.formats:
        path = audio_path.with_suffix(f".{fmt}")
        path.write_text(FORMATTERS[fmt](segments), encoding="utf-8")
        written.append(path)

    status("")
    status(_style("\u2713 ", "1;32", color)
           + _style(f"Done in {_fmt_duration(time.monotonic() - started)}", "1", color))
    for path in written:
        detail(str(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
