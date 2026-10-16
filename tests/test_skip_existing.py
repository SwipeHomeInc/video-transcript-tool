"""The CLI skips work when a video's transcripts already exist."""
import pytest

import video_transcript.download as download
import video_transcript.transcriber as transcriber
from video_transcript.cli import main
from video_transcript.formats import Segment

INFO = {"id": "123", "extractor_key": "Twitter", "title": "A talk"}
STEM = "twitter-123"


@pytest.fixture
def fake_pipeline(monkeypatch):
    calls = {"download": 0, "transcribe": 0}

    def fake_resolve(url, verbose=False, cookies_from_browser=None):
        return INFO, STEM

    def fake_download(info, stem, work_dir, **kwargs):
        calls["download"] += 1
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / f"{stem}.m4a"
        path.write_bytes(b"audio")
        return path

    def fake_transcribe(audio_path, **kwargs):
        calls["transcribe"] += 1
        return iter([Segment(0.0, 1.0, "Hello.")]), "en", 0.99, 1.0

    monkeypatch.setattr(download, "resolve_video", fake_resolve)
    monkeypatch.setattr(download, "download_audio", fake_download)
    monkeypatch.setattr(transcriber, "transcribe", fake_transcribe)
    return calls


def test_first_run_transcribes(tmp_path, fake_pipeline):
    assert main(["https://x.com/a/status/1", "-o", str(tmp_path), "-q"]) == 0
    assert fake_pipeline == {"download": 1, "transcribe": 1}
    assert (tmp_path / f"{STEM}.txt").read_text(encoding="utf-8") == "Hello.\n"
    assert (tmp_path / f"{STEM}.srt").exists()


def test_existing_transcripts_are_reused(tmp_path, fake_pipeline, capsys):
    (tmp_path / f"{STEM}.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / f"{STEM}.srt").write_text("old\n", encoding="utf-8")

    assert main(["https://x.com/a/status/1", "-o", str(tmp_path), "-q"]) == 0
    assert fake_pipeline == {"download": 0, "transcribe": 0}
    assert (tmp_path / f"{STEM}.txt").read_text(encoding="utf-8") == "old\n"
    assert "Already transcribed" in capsys.readouterr().err


def test_missing_format_still_transcribes(tmp_path, fake_pipeline):
    # Only the .txt exists, but .srt was asked for too.
    (tmp_path / f"{STEM}.txt").write_text("old\n", encoding="utf-8")
    assert main(["https://x.com/a/status/1", "-o", str(tmp_path), "-q"]) == 0
    assert fake_pipeline["transcribe"] == 1


def test_force_redoes_it(tmp_path, fake_pipeline):
    (tmp_path / f"{STEM}.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / f"{STEM}.srt").write_text("old\n", encoding="utf-8")

    assert main(["https://x.com/a/status/1", "-o", str(tmp_path), "-q", "--force"]) == 0
    assert fake_pipeline["transcribe"] == 1
    assert (tmp_path / f"{STEM}.txt").read_text(encoding="utf-8") == "Hello.\n"
