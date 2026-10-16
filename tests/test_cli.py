import argparse

import pytest

from video_transcript.cli import build_parser, parse_formats
from video_transcript.download import cache_name


def test_parse_formats():
    assert parse_formats("txt, SRT,vtt") == ["txt", "srt", "vtt"]
    with pytest.raises(argparse.ArgumentTypeError):
        parse_formats("txt,docx")
    with pytest.raises(argparse.ArgumentTypeError):
        parse_formats(",")


def test_defaults():
    args = build_parser().parse_args(["https://x.com/a/status/1"])
    assert args.model == "small"
    assert args.formats == ["txt", "srt"]
    assert str(args.output_dir) == "out"


def test_cache_name_is_per_video():
    assert cache_name("Twitter", "2102050467505430555") == "twitter-2102050467505430555"
    assert cache_name("Youtube", "abc") != cache_name("Youtube", "abd")
    assert cache_name("Generic", "a/b:c") == "generic-a_b_c"


def test_cache_name_is_capped():
    stem = cache_name("Generic", "jsc2026m000070-Artemis_II_Receive_Special_Message_" * 3)
    assert len(stem) <= 64
    assert not stem.endswith(("_", "-", "."))


def test_formatting_helpers():
    from video_transcript.cli import _fmt_bytes, _fmt_duration

    assert _fmt_duration(58.4) == "0:58"
    assert _fmt_duration(3725) == "1:02:05"
    assert _fmt_bytes(512) == "512 B"
    assert _fmt_bytes(2.37 * 1024 * 1024) == "2.4 MB"


def test_verbose_flag():
    assert build_parser().parse_args(["u", "-v"]).verbose is True


def test_explain_error():
    from video_transcript.download import explain_error

    assert "No video found" in explain_error(
        "ERROR: [twitter] 123: No video formats found!; please report this issue")
    assert "logged-in" in explain_error("ERROR: [twitter] 1: NSFW tweet requires authentication")
    assert "isn't supported" in explain_error("ERROR: Unsupported URL: https://example.com")
    assert "doesn't exist" in explain_error("ERROR: Unable to download webpage: HTTP Error 404")
    other = explain_error("ERROR: something new broke")
    assert other.startswith("Download failed: something new broke")
    assert "pipx upgrade" in other


def test_cookies_flag():
    args = build_parser().parse_args(["u", "--cookies-from-browser", "firefox"])
    assert args.cookies_from_browser == "firefox"


def test_batch_size_flag():
    assert build_parser().parse_args(["u"]).batch_size == 1
    assert build_parser().parse_args(["u", "-b", "16"]).batch_size == 16
    assert build_parser().parse_args(["u", "--fast"]).batch_size == 8


def test_explain_error_bot_check_is_not_reported_as_login():
    from video_transcript.download import explain_error

    # Exact wording yt-dlp gave for a public YouTube video from a cloud server.
    msg = ("ERROR: [youtube] _itA4tuohl0: Sign in to confirm you’re not a bot. "
           "Use --cookies-from-browser or --cookies for the authentication.")
    out = explain_error(msg)
    assert "blocking this network as a bot" in out
    assert "needs a logged-in account" not in out


def test_explain_error_rate_limit():
    from video_transcript.download import explain_error

    out = explain_error("ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests")
    assert "rate-limiting" in out
