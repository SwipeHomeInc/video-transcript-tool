import shutil
import subprocess

import pytest

from video_transcript.transcriber import (
    SAMPLE_RATE, audio_duration, load_audio, sanitize_proxy_env,
)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_load_audio_decodes_to_16k_mono(tmp_path):
    path = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-ac", "2", "-ar", "44100", str(path)],
        check=True,
    )
    audio = load_audio(path)
    assert audio.dtype.name == "float32"
    assert abs(len(audio) - 2 * SAMPLE_RATE) < SAMPLE_RATE * 0.1
    assert 0 < abs(audio).max() <= 1.0


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_load_audio_clip_and_duration(tmp_path):
    path = tmp_path / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
         str(path)],
        check=True,
    )
    assert abs(audio_duration(path) - 10) < 0.2
    clip = load_audio(path, start=4, length=3)
    assert abs(len(clip) - 3 * SAMPLE_RATE) < SAMPLE_RATE * 0.1


def test_load_audio_bad_file(tmp_path):
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio")
    with pytest.raises(RuntimeError):
        load_audio(bad)


def test_sanitize_proxy_env(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,[::1],127.0.0.1")
    sanitize_proxy_env()
    import os
    assert os.environ["NO_PROXY"] == "localhost,127.0.0.1"
