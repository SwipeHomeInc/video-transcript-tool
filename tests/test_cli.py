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
