"""Download a video's audio track with yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

AUDIO_EXT = "m4a"
MAX_STEM = 64

# Called with (bytes_downloaded, total_bytes or None).
ProgressFn = Callable[[int, Optional[int]], None]


def cache_name(extractor: str, video_id: str) -> str:
    """Filename stem unique to one video, e.g. 'twitter-2102050467505430555'.

    Keying the cached audio on the video ID (not a fixed 'audio.m4a') means a
    reused output folder never transcribes the wrong video. Long IDs (direct
    file links use the whole filename) are cut to keep paths readable.
    """
    raw = f"{extractor}-{video_id}".lower()
    return re.sub(r"[^a-z0-9._-]+", "_", raw)[:MAX_STEM].rstrip("._-")


def download_audio(
    url: str,
    work_dir: Path,
    verbose: bool = False,
    on_progress: Optional[ProgressFn] = None,
) -> tuple[Path, dict]:
    """Return (audio_path, info). Skips the download if the audio is cached.

    yt-dlp's own logging is shown only when verbose; otherwise progress is
    reported through on_progress.
    """
    import yt_dlp

    def hook(d: dict) -> None:
        if on_progress and d.get("status") in ("downloading", "finished"):
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            on_progress(int(d.get("downloaded_bytes") or 0), int(total) if total else None)

    work_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        # Posts with several videos come back as a playlist; take the first.
        "playlist_items": "1",
        "quiet": not verbose,
        "no_warnings": not verbose,
        "noprogress": not verbose,
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_EXT},
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            entries = list(info.get("entries") or [])
            if not entries:
                raise RuntimeError(f"No video found at {url}")
            info = entries[0]

        stem = cache_name(info.get("extractor_key") or "video", str(info["id"]))
        audio_path = work_dir / f"{stem}.{AUDIO_EXT}"
        if audio_path.exists():
            return audio_path, info

    opts["outtmpl"] = str(work_dir / f"{stem}.%(ext)s")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.process_ie_result(info, download=True)

    if not audio_path.exists():
        raise RuntimeError(f"yt-dlp finished but {audio_path} was not created")
    return audio_path, info
