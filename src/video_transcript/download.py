"""Download a video's audio track with yt-dlp."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

AUDIO_EXT = "m4a"
MAX_STEM = 64

# Called with (bytes_downloaded, total_bytes or None).
ProgressFn = Callable[[int, Optional[int]], None]


class _SilentLogger:
    """Swallows yt-dlp's own messages; we report errors ourselves."""

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


class DownloadFailed(Exception):
    """A download failed for a reason we can explain to the user."""


def explain_error(message: str) -> str:
    """Turn a yt-dlp error message into advice a user can act on."""
    m = message.lower()
    if "no video formats found" in m or "no video could be found" in m:
        return ("No video found at that link. Make sure the post itself has a "
                "video attached (a link preview or image won't work).")
    if "unsupported url" in m:
        return "That site isn't supported. Use a link to a post or page with a video on it."
    if any(k in m for k in ("login", "log in", "sign in", "authenticat", "nsfw",
                            "age-restricted", "private", "protected")):
        return ("That video needs a logged-in account. Log in to the site in your "
                "browser, then re-run with --cookies-from-browser chrome "
                "(or firefox, safari, edge, ...).")
    if "http error 404" in m or "does not exist" in m:
        return "That post or video doesn't exist (deleted, or a typo in the link)."
    detail = re.sub(r"^error:\s*", "", message.strip(), flags=re.I)
    return (f"Download failed: {detail}\n"
            "Re-run with -v for details. If the site changed recently, updating "
            "yt-dlp often fixes it: pipx upgrade video-transcript")


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
    cookies_from_browser: Optional[str] = None,
) -> tuple[Path, dict]:
    """Return (audio_path, info). Skips the download if the audio is cached.

    yt-dlp's own logging is shown only when verbose; otherwise progress is
    reported through on_progress. Raises DownloadFailed with a readable
    explanation when yt-dlp can't get the video.
    """
    import yt_dlp

    try:
        return _download(url, work_dir, verbose, on_progress, cookies_from_browser, yt_dlp)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailed(explain_error(str(e))) from e


def _download(url, work_dir, verbose, on_progress, cookies_from_browser, yt_dlp):
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
    if not verbose:
        opts["logger"] = _SilentLogger()
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            entries = list(info.get("entries") or [])
            if not entries:
                raise DownloadFailed(explain_error("No video formats found"))
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
