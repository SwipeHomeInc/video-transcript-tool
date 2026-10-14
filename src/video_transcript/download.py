"""Download a video's audio track with yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path

AUDIO_EXT = "m4a"


def cache_name(extractor: str, video_id: str) -> str:
    """Filename stem unique to one video, e.g. 'twitter-2102050467505430555'.

    Keying the cached audio on the video ID (not a fixed 'audio.m4a') means a
    reused output folder never transcribes the wrong video.
    """
    raw = f"{extractor}-{video_id}".lower()
    return re.sub(r"[^a-z0-9._-]+", "_", raw)


def download_audio(url: str, work_dir: Path, quiet: bool = False) -> tuple[Path, dict]:
    """Return (audio_path, info). Skips the download if the audio is cached."""
    import yt_dlp

    work_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        # Posts with several videos come back as a playlist; take the first.
        "playlist_items": "1",
        "quiet": quiet,
        "no_warnings": quiet,
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
