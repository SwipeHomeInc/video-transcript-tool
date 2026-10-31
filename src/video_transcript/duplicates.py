"""Catch a video that was already transcribed under a different ID.

A re-upload by another account gets a new video ID, so the per-ID skip check
misses it. The output folder keeps a small index (INDEX_NAME) with each
transcript's duration, caption and opening text, and a new link is compared
against it before anything is downloaded.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable, Optional

from .cli import _fmt_duration
from .formats import Segment

INDEX_NAME = ".index.json"
INDEX_VERSION = 1

# Re-uploads trim or pad intros and outros: the real pair this was built for
# differs by 96s on a 2:08 video (1.3%). 3% covers trims like that on long
# videos, where a wasted run costs the most; the 30s floor keeps short clips
# from counting as "close" to every other short clip.
DURATION_TOLERANCE = 0.03
MIN_DURATION_TOLERANCE = 30.0

# Captions are compared after normalizing (case, punctuation, links).
TITLE_MATCH = 0.8
TITLE_COMPARE_CHARS = 500
# A caption this short ("Wow") says too little to decide on its own.
MIN_CAPTION_CHARS = 30
MIN_CAPTION_WORDS = 5
# A shorter caption at least this share of the longer one's length is
# compared as a prefix, like one that ends in "..." (a cut-off title).
PREFIX_SHARE = 0.8
# Sites where the description is the post itself. Elsewhere (YouTube, ...)
# descriptions often share a channel's sponsor/subscribe text, so the title
# is compared instead.
DESCRIPTION_IS_CAPTION = {"twitter"}

# The index keeps the first OPENING_SECONDS of each transcript; the check
# transcribes the first CLIP_SECONDS of the new video. The stored opening is
# longer so a re-upload that starts up to 30s earlier or later still lines up.
OPENING_SECONDS = 120.0
CLIP_SECONDS = 90.0
# Share of word triples in common (of the shorter text). Unrelated speech
# shares almost none; two Whisper runs over the same audio share most.
OPENING_MATCH = 0.5
# A channel's stock intro is a dozen or so words; an opening needs well
# past that before it can decide anything.
MIN_OPENING_TRIPLES = 40
# The clip is transcribed with a small, fast model whatever --model says:
# on the real pair, base took 9s and matched 96%; small took 22s for 95%.
OPENING_MODEL = "base"

_URL = re.compile(r"https?://\S+")
_SRT_TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{3})")


@dataclass(frozen=True)
class Match:
    stem: str
    entry: dict
    reason: str

    def transcript_path(self, output_dir: Path) -> Path:
        return output_dir / self.entry.get("transcript", f"{self.stem}.txt")


def normalize(text: Optional[str]) -> str:
    """Lowercase words only: no links, punctuation or extra spaces."""
    if not text:
        return ""
    words = re.findall(r"[a-z0-9]+", _URL.sub(" ", text.lower()))
    return " ".join(words)


def caption(info: dict) -> Optional[str]:
    """What the video is called: on X the post's text, elsewhere the title.

    X titles are 'uploader - ' plus the start of the post, so the
    description (the whole post) is used there. Other sites' descriptions
    are left out because a channel reuses the same boilerplate on every video.
    """
    if str(info.get("extractor_key") or "").lower() in DESCRIPTION_IS_CAPTION:
        desc = (info.get("description") or "").strip()
        if desc:
            return desc
    title = (info.get("title") or "").strip()
    # Direct file links have no real title, just the filename (== the ID).
    if not title or title == str(info.get("id")):
        return None
    uploader = info.get("uploader")
    if uploader and title.startswith(f"{uploader} - "):
        title = title[len(uploader) + 3:]
    return title or None


def title_similarity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    """0..1 similarity of two captions, or None if they can't decide.

    None when either is missing or the shorter one is too short to mean
    anything. Titles are often cut short ("...Te..."), so when the shorter
    one looks cut off, or is most of the longer one's length, only as much
    of the longer one is compared; otherwise the whole captions are.
    """
    if not a or not b:
        return None
    short, long_ = sorted((a, b), key=lambda t: len(normalize(t)))
    ns, nl = normalize(short), normalize(long_)
    if len(ns) < MIN_CAPTION_CHARS and len(ns.split()) < MIN_CAPTION_WORDS:
        return None
    cut_off = short.rstrip().endswith(("...", "\u2026"))
    if cut_off or len(ns) >= PREFIX_SHARE * len(nl):
        nl = nl[:len(ns)]
    return SequenceMatcher(
        None, ns[:TITLE_COMPARE_CHARS], nl[:TITLE_COMPARE_CHARS], autojunk=False,
    ).ratio()


def durations_close(a: Optional[float], b: Optional[float]) -> bool:
    if not a or not b:
        return False
    return abs(a - b) <= max(DURATION_TOLERANCE * max(a, b), MIN_DURATION_TOLERANCE)


def _triples(text: str) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def opening_similarity(a: Optional[str], b: Optional[str]) -> Optional[float]:
    """0..1 share of word triples the two openings have in common.

    Measured against the shorter text, so a clip that covers only part of the
    stored opening can still match fully. None when either has too little
    speech to judge (music intros, silence).
    """
    ta, tb = _triples(a or ""), _triples(b or "")
    if min(len(ta), len(tb)) < MIN_OPENING_TRIPLES:
        return None
    return len(ta & tb) / min(len(ta), len(tb))


def opening_text(segments: Iterable[Segment], seconds: float = OPENING_SECONDS) -> str:
    return " ".join(s.text for s in segments if s.start < seconds).strip()


def parse_srt(text: str) -> list[Segment]:
    segments = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        for i, line in enumerate(lines):
            m = _SRT_TIME.search(line)
            if m:
                v = [int(x) for x in m.groups()]
                start = v[0] * 3600 + v[1] * 60 + v[2] + v[3] / 1000
                end = v[4] * 3600 + v[5] * 60 + v[6] + v[7] / 1000
                segments.append(Segment(start, end, " ".join(lines[i + 1:]).strip()))
                break
    return segments


def _audio_seconds(path: Path) -> Optional[float]:
    from .transcriber import audio_duration

    try:
        return audio_duration(path)
    except (RuntimeError, ValueError):
        return None


def entry_from_srt(srt_path: Path) -> Optional[dict]:
    """Index entry for a transcript made before the index existed.

    Duration comes from the cached audio if it's still there, otherwise from
    the last subtitle. The URL and caption aren't known.
    """
    try:
        segments = parse_srt(srt_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if not segments:
        return None
    stem = srt_path.stem
    audio = srt_path.with_suffix(".m4a")
    duration = _audio_seconds(audio) if audio.exists() else None
    txt = srt_path.with_suffix(".txt")
    return {
        "url": None,
        "extractor": stem.split("-", 1)[0] if "-" in stem else None,
        "video_id": stem.split("-", 1)[1] if "-" in stem else None,
        "title": None,
        "duration": duration or segments[-1].end,
        "opening": opening_text(segments),
        "transcript": txt.name if txt.exists() else srt_path.name,
        "transcribed_at": date.fromtimestamp(srt_path.stat().st_mtime).isoformat(),
    }


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    videos = data.get("videos") if isinstance(data, dict) else None
    if not isinstance(videos, dict):
        return {}
    # Skip entries a hand edit or another tool left in a shape we can't use.
    return {
        stem: entry for stem, entry in videos.items()
        if isinstance(entry, dict) and _is_seconds(entry.get("duration"))
    }


def _is_seconds(value) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def save_index(output_dir: Path, videos: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / INDEX_NAME
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"version": INDEX_VERSION, "videos": videos}, indent=1,
                              ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def load_index(output_dir: Path) -> dict:
    """The folder's index as {stem: entry}.

    Any .srt in the folder that isn't indexed yet (older runs, or the first
    time the index is needed) is added from the file and the index is saved.
    """
    if not output_dir.is_dir():
        return {}
    videos = _read(output_dir / INDEX_NAME)
    added = False
    for srt in sorted(output_dir.glob("*.srt")):
        if srt.stem not in videos:
            entry = entry_from_srt(srt)
            if entry:
                videos[srt.stem] = entry
                added = True
    if added:
        save_index(output_dir, videos)
    return videos


def record(
    output_dir: Path,
    stem: str,
    info: dict,
    url: str,
    duration: Optional[float],
    segments: list[Segment],
    transcript: str,
) -> None:
    """Add or replace this video's entry after a successful run."""
    videos = _read(output_dir / INDEX_NAME)
    videos[stem] = {
        "url": url,
        "extractor": info.get("extractor_key"),
        "video_id": str(info.get("id")) if info.get("id") is not None else None,
        "title": caption(info),
        "duration": info.get("duration") or duration,
        "opening": opening_text(segments),
        "transcript": transcript,
        "transcribed_at": date.today().isoformat(),
    }
    save_index(output_dir, videos)


def check_metadata(
    info: dict, stem: str, videos: dict,
) -> tuple[Optional[Match], list[str]]:
    """Check 1, from metadata alone.

    Returns (match, candidates). A match needs a close duration and a
    similar caption. Candidates are the other close-duration videos with an
    opening on file, for check 2.
    """
    duration = info.get("duration")
    new_caption = caption(info)
    best: Optional[Match] = None
    best_score = 0.0
    candidates = []
    for other_stem, entry in videos.items():
        if other_stem == stem or not durations_close(duration, entry.get("duration")):
            continue
        score = title_similarity(new_caption, entry.get("title"))
        if score is not None and score >= TITLE_MATCH and score > best_score:
            best_score = score
            best = Match(other_stem, entry, (
                f"same length ({_fmt(duration)} vs {_fmt(entry['duration'])}) and "
                f"caption {score:.0%} similar"))
        elif entry.get("opening"):
            candidates.append(other_stem)
    return best, ([] if best else candidates)


def check_opening(
    clip_text: str, duration: Optional[float], candidates: list[str], videos: dict,
) -> Optional[Match]:
    """Check 2: compare the new video's opening with the candidates'."""
    best: Optional[Match] = None
    best_score = 0.0
    for other_stem in candidates:
        entry = videos[other_stem]
        score = opening_similarity(clip_text, entry.get("opening"))
        if score is not None and score >= OPENING_MATCH and score > best_score:
            best_score = score
            best = Match(other_stem, entry, (
                f"same length ({_fmt(duration)} vs {_fmt(entry['duration'])}) and "
                f"the opening matches ({score:.0%} of phrases in common)"))
    return best



def _fmt(seconds: Optional[float]) -> str:
    return _fmt_duration(seconds) if seconds else "?"
