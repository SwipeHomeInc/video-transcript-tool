"""Language detection listens across the whole audio, and warns when unsure."""
import numpy as np
import pytest

import video_transcript.download as download
import video_transcript.transcriber as transcriber
from video_transcript.cli import language_warning, main
from video_transcript.formats import Segment
from video_transcript.transcriber import (
    SAMPLE_RATE, SAMPLE_SECONDS, detect_language, pick_language, sample_starts,
)


def test_short_audio_is_one_sample():
    assert sample_starts(20) == [0.0]
    assert sample_starts(SAMPLE_SECONDS) == [0.0]


def test_samples_spread_across_long_audio():
    duration = 3 * 3600 + 46 * 60 + 21  # the 3:46:21 talk
    starts = sample_starts(duration)
    assert len(starts) == 5
    assert starts == sorted(starts)
    assert starts[0] > 60  # not the intro
    assert starts[-1] + SAMPLE_SECONDS < duration - 60  # not the outro
    assert all(0 <= s <= duration - SAMPLE_SECONDS for s in starts)


def test_fewer_samples_when_audio_is_short():
    starts = sample_starts(150)
    assert len(starts) == 2
    assert all(0 <= s <= 150 - SAMPLE_SECONDS for s in starts)


def test_majority_beats_a_confident_bad_first_clip():
    # The real failure: the first clip sounded Welsh (83%), the rest was English.
    clips = [[("cy", 0.83), ("en", 0.10)]] + [[("en", 0.97), ("cy", 0.01)]] * 4
    language, confidence = pick_language(clips)
    assert language == "en"
    assert confidence == pytest.approx((0.10 + 0.97 * 4) / 5)


def test_split_vote_has_low_confidence():
    clips = [[("en", 0.9), ("es", 0.1)], [("es", 0.9), ("en", 0.1)]]
    _, confidence = pick_language(clips)
    assert confidence == pytest.approx(0.5)
    assert language_warning(None, "en", confidence) is not None


class FakeModel:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def detect_language(self, audio):
        self.calls += 1
        return None, None, self.answers.pop(0)


@pytest.fixture
def fake_audio(monkeypatch):
    """A 10-minute file whose clips are decoded without ffmpeg."""
    loaded = []

    def fake_load(path, start=None, length=None):
        loaded.append((start, length))
        return np.zeros(int(length * SAMPLE_RATE), dtype=np.float32)

    monkeypatch.setattr(transcriber, "audio_duration", lambda path: 600.0)
    monkeypatch.setattr(transcriber, "load_audio", fake_load)
    return loaded


def test_detect_language_decodes_only_clips(monkeypatch, fake_audio):
    import faster_whisper.vad as vad

    monkeypatch.setattr(vad, "get_speech_timestamps",
                        lambda clip: [{"start": 0, "end": 10 * SAMPLE_RATE}])
    clip_count = len(sample_starts(600))
    model = FakeModel([[("en", 0.9)]] * clip_count)
    assert detect_language(model, "a.m4a") == ("en", pytest.approx(0.9))
    assert fake_audio == [(s, SAMPLE_SECONDS) for s in sample_starts(600)]


def test_detect_language_skips_clips_without_speech(monkeypatch, fake_audio):
    import faster_whisper.vad as vad

    clip_count = len(sample_starts(600))
    calls = iter(range(clip_count))

    def fake_vad(clip):
        # Only the first clip is silent.
        return [] if next(calls) == 0 else [{"start": 0, "end": 10 * SAMPLE_RATE}]

    monkeypatch.setattr(vad, "get_speech_timestamps", fake_vad)
    model = FakeModel([[("en", 0.9)]] * (clip_count - 1))
    assert detect_language(model, "a.m4a") == ("en", pytest.approx(0.9))
    assert model.calls == clip_count - 1


def test_detect_language_with_no_speech_at_all(monkeypatch, fake_audio):
    import faster_whisper.vad as vad

    monkeypatch.setattr(vad, "get_speech_timestamps", lambda clip: [])
    assert detect_language(FakeModel([]), "a.m4a") is None


def test_detect_language_without_a_duration(monkeypatch):
    def no_duration(path):
        return float("N/A")

    monkeypatch.setattr(transcriber, "audio_duration", no_duration)
    assert detect_language(FakeModel([]), "a.m4a") is None


def test_no_warning_when_confident_or_language_given():
    assert language_warning(None, "en", 0.95) is None
    assert language_warning("en", "en", 0.2) is None
    message = language_warning(None, "cy", 0.4)
    assert "-l" in message and "cy" in message


@pytest.mark.parametrize("prob, warned", [(0.3, True), (0.9, False)])
def test_cli_prints_warning(tmp_path, monkeypatch, capsys, prob, warned):
    monkeypatch.setattr(download, "resolve_video",
                        lambda url, **kw: ({"id": "1", "extractor_key": "Twitter"}, "twitter-1"))

    def fake_download(info, stem, work_dir, **kw):
        work_dir.mkdir(parents=True, exist_ok=True)
        return work_dir / f"{stem}.m4a"

    monkeypatch.setattr(download, "download_audio", fake_download)
    monkeypatch.setattr(transcriber, "transcribe",
                        lambda path, **kw: (iter([Segment(0, 1, "Hi.")]), "cy", prob, 1.0))
    assert main(["https://x.com/a/status/1", "-o", str(tmp_path), "-q"]) == 0
    assert ("rerun with -l" in capsys.readouterr().err) is warned
