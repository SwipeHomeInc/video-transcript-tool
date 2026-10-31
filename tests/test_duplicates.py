"""The duplicate check: a re-upload under a new video ID is caught before a full run."""
import json

import pytest

import video_transcript.download as download
import video_transcript.duplicates as dup
import video_transcript.transcriber as transcriber
from video_transcript.cli import main
from video_transcript.formats import Segment, to_srt

# A channel's stock intro, said at the start of every video (14 words).
INTRO = "Hey everyone, welcome back to the channel, and thanks so much for being here today. "
OPENING = INTRO + (
    "Today we are going to rebuild the kitchen cabinets from scratch, starting "
    "with the frame, then the doors, and finally the hardware. Grab a tape "
    "measure and a pencil before we begin. The first thing to check is whether "
    "the old boxes are square, because if they are not, nothing you hang on "
    "them will ever line up, no matter how careful you are with the doors."
)
# The same speech as another Whisper run might write it.
OPENING_RERUN = (
    "hey everyone welcome back to the channel and thanks so much for being here "
    "today today we're going to rebuild the kitchen cabinets from scratch "
    "starting with the frame then the doors and finally the hardware grab a "
    "tape measure and a pencil before we begin the first thing to check is "
    "whether the old boxes are square because if they're not nothing you hang "
    "on them will ever line up no matter how careful you are with the doors"
)
OTHER_SPEECH = INTRO + (
    "In this episode we talk about interest rates, what the central bank did "
    "last month, and how that changes the math on refinancing a mortgage this "
    "year. We will walk through two real examples, one with a fixed rate and "
    "one with an adjustable rate, and look at the closing costs on each."
)

NEW_INFO = {
    "id": "999", "extractor_key": "Twitter", "duration": 7746.0,
    "title": "someone - Rebuilding kitchen cabinets from scratch, the whole...",
    "uploader": "someone",
    "description": "Rebuilding kitchen cabinets from scratch, the whole process "
                   "in one video https://t.co/abc",
}
NEW_STEM = "twitter-999"


def write_old_transcript(folder, stem="twitter-111", end=7650.0, opening=OPENING):
    segments = [Segment(0.0, 20.0, opening), Segment(130.0, 140.0, "Later on."),
                Segment(end - 5, end, "See you next time.")]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{stem}.srt").write_text(to_srt(segments), encoding="utf-8")
    (folder / f"{stem}.txt").write_text("text\n", encoding="utf-8")
    return segments


# Index -------------------------------------------------------------------

def test_index_is_built_from_existing_srt_files(tmp_path):
    write_old_transcript(tmp_path)
    videos = dup.load_index(tmp_path)

    entry = videos["twitter-111"]
    assert entry["duration"] == 7650.0  # last cue; no cached audio
    assert entry["opening"] == OPENING  # cues starting after 2 minutes left out
    assert entry["transcript"] == "twitter-111.txt"
    assert entry["title"] is None and entry["url"] is None
    assert entry["video_id"] == "111"
    saved = json.loads((tmp_path / dup.INDEX_NAME).read_text(encoding="utf-8"))
    assert saved["videos"]["twitter-111"] == entry


def test_index_prefers_cached_audio_length(tmp_path, monkeypatch):
    write_old_transcript(tmp_path)
    (tmp_path / "twitter-111.m4a").write_bytes(b"audio")
    monkeypatch.setattr(transcriber, "audio_duration", lambda path: 7651.5)
    assert dup.load_index(tmp_path)["twitter-111"]["duration"] == 7651.5


def test_record_then_read(tmp_path):
    segments = [Segment(0.0, 5.0, "Hello there."), Segment(200.0, 205.0, "Bye.")]
    dup.record(tmp_path, NEW_STEM, NEW_INFO, "https://x.com/a/status/1", 7745.0,
               segments, "twitter-999.txt")
    entry = dup.load_index(tmp_path)[NEW_STEM]
    assert entry["url"] == "https://x.com/a/status/1"
    assert entry["extractor"] == "Twitter"
    assert entry["video_id"] == "999"
    assert entry["duration"] == 7746.0  # the metadata's length wins
    assert entry["title"].startswith("Rebuilding kitchen cabinets")
    assert entry["opening"] == "Hello there."


def test_unreadable_index_is_rebuilt(tmp_path):
    write_old_transcript(tmp_path)
    (tmp_path / dup.INDEX_NAME).write_text("{not json", encoding="utf-8")
    assert "twitter-111" in dup.load_index(tmp_path)


def test_parse_srt_round_trip():
    segments = [Segment(1.5, 2.25, "One."), Segment(3661.0, 3662.0, "Two lines\nhere.")]
    assert dup.parse_srt(to_srt(segments)) == [
        Segment(1.5, 2.25, "One."), Segment(3661.0, 3662.0, "Two lines here."),
    ]


# Matching rules ------------------------------------------------------------

def test_duration_tolerance():
    assert dup.durations_close(7650.4, 7746.0)  # the real pair: 96s apart
    assert dup.durations_close(7650.0, 7650.0 * 1.029)
    assert not dup.durations_close(7650.0, 7650.0 * 1.04)
    assert dup.durations_close(600.0, 629.0)  # 30s floor on short videos
    assert not dup.durations_close(600.0, 640.0)
    assert not dup.durations_close(None, 600.0)


def test_caption_strips_uploader_and_ignores_filenames():
    assert dup.caption({"title": "rose - Big talk", "uploader": "rose"}) == "Big talk"
    assert dup.caption({"title": "clip", "id": "clip"}) is None
    tweet = {"extractor_key": "Twitter", "title": "x", "description": "Full text"}
    assert dup.caption(tweet) == "Full text"


def test_caption_ignores_descriptions_off_x():
    # YouTube descriptions often start with the same sponsor/subscribe text.
    video = {"extractor_key": "Youtube", "title": "Fixing a leaky faucet",
             "description": "Thanks to our sponsor! Subscribe for more."}
    assert dup.caption(video) == "Fixing a leaky faucet"
    assert dup.caption({**video, "title": ""}) is None


def test_title_similarity():
    a = "This lecture covers agents, harnesses and loops https://t.co/1"
    b = "this lecture covers AGENTS harnesses & loops... https://t.co/2"
    assert dup.title_similarity(a, b) >= dup.TITLE_MATCH
    assert dup.title_similarity(a, "Quarterly earnings call for the third quarter") < 0.5
    assert dup.title_similarity(a, None) is None
    # A title cut short still matches the full caption it came from.
    assert dup.title_similarity("This lecture covers agents, harn...", a) >= dup.TITLE_MATCH


def test_short_captions_decide_nothing():
    assert dup.title_similarity("Wow", "Wow look at this dog") is None
    assert dup.title_similarity("Wow!!", "wow") is None
    # Five words is enough to judge.
    assert dup.title_similarity("Big news about the house", "Big news about the house") == 1.0


def test_caption_prefix_only_counts_when_cut_off():
    long_caption = ("This lecture covers agents, harnesses and loops, and then spends "
                    "an hour on evaluation, cost and how to ship it to real users")
    whole = "This lecture covers agents, harnesses and loops"
    # A complete caption that only shares a start with a longer one isn't a match...
    assert dup.title_similarity(whole, long_caption) < dup.TITLE_MATCH
    # ...but the same words cut off with "..." or "\u2026" are.
    assert dup.title_similarity(whole + "...", long_caption) >= dup.TITLE_MATCH
    assert dup.title_similarity(whole + "\u2026", long_caption) >= dup.TITLE_MATCH


def test_short_caption_goes_to_the_opening_check():
    info = {**NEW_INFO, "description": "Wow look at this dog"}
    videos = {"twitter-111": {"duration": 7650.0, "title": "Wow", "opening": OPENING}}
    match, candidates = dup.check_metadata(info, NEW_STEM, videos)
    assert match is None and candidates == ["twitter-111"]


def test_youtube_boilerplate_is_not_a_match():
    boilerplate = ("This video is sponsored by Acme. Use code HOME for 10% off. "
                   "Subscribe and hit the bell for a new video every week!")
    old = {"id": "a", "extractor_key": "Youtube", "duration": 600.0,
           "title": "Fixing a leaky faucet in ten minutes", "description": boilerplate}
    new = {**old, "id": "b", "title": "Painting a front door the right way"}
    videos = {"youtube-a": {"duration": 600.0, "title": dup.caption(old), "opening": OPENING}}
    match, candidates = dup.check_metadata(new, "youtube-b", videos)
    assert match is None and candidates == ["youtube-a"]


def test_opening_similarity():
    assert dup.opening_similarity(OPENING_RERUN, OPENING) >= dup.OPENING_MATCH
    assert dup.opening_similarity(OTHER_SPEECH, OPENING) < 0.3
    assert dup.opening_similarity("too short to judge", OPENING) is None
    # A clip that starts partway into the stored opening still matches.
    later = OPENING.split(" ", 8)[-1]
    assert dup.opening_similarity(later, OPENING) >= dup.OPENING_MATCH


def test_shared_intro_is_not_a_match():
    # Two different videos from one channel open with the same 14 words.
    assert dup.opening_similarity(INTRO, OPENING) is None  # too little to judge
    assert dup.opening_similarity(OTHER_SPEECH, OPENING) < dup.OPENING_MATCH


def test_metadata_check_matches_on_length_and_caption():
    videos = {"twitter-111": {"duration": 7650.0, "title": NEW_INFO["description"],
                              "opening": OPENING}}
    match, candidates = dup.check_metadata(NEW_INFO, NEW_STEM, videos)
    assert match.stem == "twitter-111" and candidates == []


def test_metadata_check_leaves_untitled_for_check_two():
    videos = {
        "twitter-111": {"duration": 7650.0, "title": None, "opening": OPENING},
        "twitter-222": {"duration": 300.0, "title": None, "opening": OPENING},
        NEW_STEM: {"duration": 7746.0, "title": None, "opening": OPENING},
    }
    match, candidates = dup.check_metadata(NEW_INFO, NEW_STEM, videos)
    assert match is None
    assert candidates == ["twitter-111"]  # not the wrong length, not itself


# The CLI ------------------------------------------------------------------

@pytest.fixture
def pipeline(monkeypatch):
    calls = {"download": 0, "transcribe": 0, "opening_download": 0, "opening": 0}
    state = {"info": NEW_INFO, "clip_text": OPENING_RERUN}

    def fake_resolve(url, verbose=False, cookies_from_browser=None):
        return state["info"], NEW_STEM

    def fake_download(info, stem, work_dir, **kwargs):
        calls["download"] += 1
        work_dir.mkdir(parents=True, exist_ok=True)
        path = work_dir / f"{stem}.m4a"
        path.write_bytes(b"audio")
        return path

    def fake_download_opening(info, work_dir, seconds, **kwargs):
        calls["opening_download"] += 1
        path = work_dir / "opening.mp4"
        path.write_bytes(b"clip")
        return path

    def fake_transcribe_opening(path, seconds, **kwargs):
        calls["opening"] += 1
        return state["clip_text"]

    def fake_transcribe(audio_path, **kwargs):
        calls["transcribe"] += 1
        return iter([Segment(0.0, 1.0, "Hello.")]), "en", 0.99, 7745.0

    monkeypatch.setattr(download, "resolve_video", fake_resolve)
    monkeypatch.setattr(download, "download_audio", fake_download)
    monkeypatch.setattr(download, "download_opening", fake_download_opening)
    monkeypatch.setattr(transcriber, "transcribe_opening", fake_transcribe_opening)
    monkeypatch.setattr(transcriber, "transcribe", fake_transcribe)
    return calls, state


def run(tmp_path, *extra):
    return main(["https://x.com/b/status/2", "-o", str(tmp_path), "-q", *extra])


def test_opening_match_stops_before_download(tmp_path, pipeline, capsys):
    calls, state = pipeline
    state["info"] = {**NEW_INFO, "description": "", "title": ""}  # no caption
    write_old_transcript(tmp_path)

    assert run(tmp_path) == 0
    assert calls == {"download": 0, "transcribe": 0, "opening_download": 1, "opening": 1}
    err = capsys.readouterr().err
    assert "Likely already transcribed as twitter-111.txt" in err
    assert "--force" in err
    assert not (tmp_path / f"{NEW_STEM}.txt").exists()


def test_caption_match_needs_no_audio(tmp_path, pipeline, capsys):
    calls, _ = pipeline
    dup.record(tmp_path, "twitter-111", {**NEW_INFO, "id": "111"},
               "https://x.com/a/status/1", None, [Segment(0, 5, OPENING)],
               "twitter-111.txt")

    assert run(tmp_path) == 0
    assert calls == {"download": 0, "transcribe": 0, "opening_download": 0, "opening": 0}
    err = capsys.readouterr().err
    assert "twitter-111.txt" in err and "https://x.com/a/status/1" in err


def test_different_opening_transcribes_normally(tmp_path, pipeline):
    calls, state = pipeline
    state["clip_text"] = OTHER_SPEECH
    write_old_transcript(tmp_path)

    assert run(tmp_path) == 0
    assert calls["opening"] == 1 and calls["transcribe"] == 1
    assert NEW_STEM in dup.load_index(tmp_path)


def test_failed_opening_download_does_not_block(tmp_path, pipeline, monkeypatch):
    calls, _ = pipeline

    def broken(*args, **kwargs):
        raise download.DownloadFailed("rate limited")

    monkeypatch.setattr(download, "download_opening", broken)
    write_old_transcript(tmp_path)
    assert run(tmp_path) == 0
    assert calls["transcribe"] == 1


def test_force_skips_the_check_and_updates_the_index(tmp_path, pipeline):
    calls, _ = pipeline
    write_old_transcript(tmp_path)

    assert run(tmp_path, "--force") == 0
    assert calls == {"download": 1, "transcribe": 1, "opening_download": 0, "opening": 0}
    videos = dup.load_index(tmp_path)
    assert videos[NEW_STEM]["url"] == "https://x.com/b/status/2"
    assert "twitter-111" in videos


def test_normal_run_skips_check_two_and_indexes(tmp_path, pipeline):
    calls, _ = pipeline
    write_old_transcript(tmp_path, end=300.0)  # nothing the same length

    assert run(tmp_path) == 0
    assert calls == {"download": 1, "transcribe": 1, "opening_download": 0, "opening": 0}
    entry = dup.load_index(tmp_path)[NEW_STEM]
    assert entry["opening"] == "Hello." and entry["transcript"] == f"{NEW_STEM}.txt"


def test_empty_folder_runs_normally(tmp_path, pipeline):
    calls, _ = pipeline
    assert run(tmp_path / "new") == 0
    assert calls["transcribe"] == 1
    assert NEW_STEM in dup.load_index(tmp_path / "new")


@pytest.mark.parametrize("videos", [
    {"x": "str"},
    {"x": None},
    {"x": {"duration": "abc"}},
    {"x": {"duration": 7650.0, "title": 5, "opening": OPENING}},
    {"x": {"duration": 7650.0, "title": None, "opening": ["not", "text"]}},
    ["not", "a", "dict"],
])
def test_bad_index_means_a_normal_run(tmp_path, pipeline, videos):
    calls, _ = pipeline
    (tmp_path / dup.INDEX_NAME).write_text(json.dumps({"videos": videos}), encoding="utf-8")

    assert run(tmp_path) == 0
    assert calls["transcribe"] == 1
    assert NEW_STEM in dup.load_index(tmp_path)


def test_read_drops_unusable_entries(tmp_path):
    good = {"duration": 60.0, "opening": "hi"}
    (tmp_path / dup.INDEX_NAME).write_text(json.dumps({"videos": {
        "a": "str", "b": None, "c": {"duration": "abc"}, "d": {"duration": True},
        "e": good, "f": {"duration": None},
    }}), encoding="utf-8")
    assert dup.load_index(tmp_path) == {"e": good, "f": {"duration": None}}


def test_index_write_error_only_warns(tmp_path, pipeline, monkeypatch, capsys):
    calls, _ = pipeline

    def broken(*args, **kwargs):
        raise PermissionError("read-only folder")

    monkeypatch.setattr(dup, "record", broken)
    assert run(tmp_path) == 0
    assert (tmp_path / f"{NEW_STEM}.txt").exists()
    err = capsys.readouterr().err
    assert "duplicate index wasn't updated" in err and "Traceback" not in err
