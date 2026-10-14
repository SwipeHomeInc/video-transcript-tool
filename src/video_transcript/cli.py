"""Command-line entry point: `video-transcript <url>`."""
from __future__ import annotations

import argparse
import sys
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
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    from .download import download_audio
    from .transcriber import transcribe

    print(f"[1/2] Fetching audio from {args.url} ...", file=sys.stderr, flush=True)
    audio_path, _info = download_audio(args.url, args.output_dir, quiet=args.quiet)
    print(f"      Audio: {audio_path}", file=sys.stderr, flush=True)

    print(f"[2/2] Transcribing with Whisper ({args.model}) ...",
          file=sys.stderr, flush=True)
    segments_iter, language, prob = transcribe(
        audio_path, model_size=args.model, language=args.language, device=args.device,
    )
    print(f"      Language: {language} (p={prob:.2f})", file=sys.stderr, flush=True)

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

    print("\nDone. Wrote:", file=sys.stderr)
    for path in written:
        print(f"  {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
