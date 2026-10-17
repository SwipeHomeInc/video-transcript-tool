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
    # Checked before the login rule: YouTube's bot check says "Sign in to
    # confirm you're not a bot", but the video itself is usually public.
    if "not a bot" in m:
        return ("The site is blocking this network as a bot. This happens a lot on "
                "cloud servers and VPNs, even for public videos. Try from your home "
                "internet, or re-run with --cookies-from-browser chrome "
                "(or firefox, safari, edge, ...).")
    if "http error 429" in m or "too many requests" in m:
        return ("The site is rate-limiting this network (too many requests). Wait a "
                "few minutes and try again, or try from a different network.")
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


def _base_opts(verbose: bool, cookies_from_browser: Optional[str]) -> dict:
    opts = {
        "format": "bestaudio/best",
        # Posts with several videos come back as a playlist; take the first.
        "playlist_items": "1",
        "quiet": not verbose,
        "no_warnings": not verbose,
        "noprogress": not verbose,
    }
    if not verbose:
        opts["logger"] = _SilentLogger()
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def resolve_video(
    url: str,
    verbose: bool = False,
    cookies_from_browser: Optional[str] = None,
) -> tuple[dict, str]:
    """Look the video up without downloading it. Return (info, file stem).

    The stem names every file for this video, so callers can check for an
    existing transcript before paying for a download and transcription.
    Raises DownloadFailed with a readable explanation on failure.
    """
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_base_opts(verbose, cookies_from_browser)) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailed(explain_error(str(e))) from e
    if info.get("_type") == "playlist":
        entries = list(info.get("entries") or [])
        if not entries:
            raise DownloadFailed(explain_error("No video formats found"))
        info = entries[0]
    return info, cache_name(info.get("extractor_key") or "video", str(info["id"]))


def download_audio(
    info: dict,
    stem: str,
    work_dir: Path,
    verbose: bool = False,
    on_progress: Optional[ProgressFn] = None,
    cookies_from_browser: Optional[str] = None,
) -> Path:
    """Download the audio for a video from resolve_video(). Return its path.

    Skips the download if the audio is already in work_dir. yt-dlp's own
    logging is shown only when verbose; otherwise progress is reported
    through on_progress.
    """
    import yt_dlp

    work_dir.mkdir(parents=True, exist_ok=True)
    audio_path = work_dir / f"{stem}.{AUDIO_EXT}"
    if audio_path.exists():
        return audio_path

    def hook(d: dict) -> None:
        if on_progress and d.get("status") in ("downloading", "finished"):
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            on_progress(int(d.get("downloaded_bytes") or 0), int(total) if total else None)

    opts = _base_opts(verbose, cookies_from_browser)
    opts.update({
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": AUDIO_EXT},
        ],
        "outtmpl": str(work_dir / f"{stem}.%(ext)s"),
    })
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadFailed(explain_error(str(e))) from e

    if not audio_path.exists():
        raise RuntimeError(f"yt-dlp finished but {audio_path} was not created")
    return audio_path
