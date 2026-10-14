from video_transcript.formats import Segment, srt_timestamp, to_srt, to_txt, to_vtt, vtt_timestamp


def test_timestamp_basic():
    assert srt_timestamp(0) == "00:00:00,000"
    assert srt_timestamp(3725.5) == "01:02:05,500"
    assert vtt_timestamp(3725.5) == "01:02:05.500"


def test_timestamp_rounds_up_into_next_second():
    # Old code produced "00:00:01,1000" here, which players reject.
    assert srt_timestamp(1.9996) == "00:00:02,000"
    assert srt_timestamp(59.9999) == "00:01:00,000"


def test_timestamp_never_negative():
    assert srt_timestamp(-0.01) == "00:00:00,000"


SEGS = [Segment(0.0, 1.5, "Hello there."), Segment(1.5, 3.0, "Café ☕ 日本語")]


def test_txt():
    assert to_txt(SEGS) == "Hello there.\nCafé ☕ 日本語\n"


def test_srt():
    assert to_srt(SEGS) == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\nCafé ☕ 日本語\n\n"
    )


def test_vtt():
    assert to_vtt(SEGS).startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello there.\n\n")


def test_empty():
    assert to_txt([]) == ""
    assert to_srt([]) == ""
    assert to_vtt([]) == "WEBVTT\n\n"
