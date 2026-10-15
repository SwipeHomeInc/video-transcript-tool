# video-transcript

Word-for-word transcripts from any video URL: X, YouTube, Vimeo, and anything
else [yt-dlp](https://github.com/yt-dlp/yt-dlp) can download.

X has no transcript button. This downloads the video's audio and transcribes
it on your own machine with Whisper
([faster-whisper](https://github.com/SYSTRAN/faster-whisper)). You don't need
an API key or a subscription, and nothing gets uploaded.

<p align="center">
  <img src="docs/demo.gif" width="860"
       alt="Terminal demo: video-transcript turns a 58-second NASA clip into a transcript plus .txt and .srt files in 16 seconds">
</p>
<p align="center"><sub>A real, unedited run on a 4-core machine with no GPU (long waits trimmed to
1.4s). The clip is NASA's public-domain
<a href="https://images.nasa.gov/details/jsc2026m000070-Artemis_II_Receive_Special_Message_from_Apollo_16_Astronaut_Charlie_Duke">message from Apollo 16 astronaut Charlie Duke to the Artemis II crew</a>.</sub></p>

## Install

Needs Python 3.10+ and [ffmpeg](https://ffmpeg.org/download.html) on your PATH
(`brew install ffmpeg`, `sudo apt install ffmpeg`, or `winget install ffmpeg`).

```bash
pipx install git+https://github.com/SwipeHomeInc/video-transcript-tool
```

Or from a clone:

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

## Usage

```bash
video-transcript "https://x.com/poteto/status/2102050467505430555"
```

The transcript prints as it's produced. When it's done, `out/` contains:

- `twitter-<video id>.txt`: plain text
- `twitter-<video id>.srt`: timestamped subtitles
- `twitter-<video id>.m4a`: the audio, kept so a re-run (say, with a bigger
  model) skips the download

Files are named after the video's ID, so you can transcribe many videos into
the same folder. On X the video ID is not the same as the post ID in the URL.

### Options

| Flag | Default | What it does |
|---|---|---|
| `-o, --output-dir` | `out` | Where files go |
| `-m, --model` | `small` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`. Bigger models are more accurate but slower. |
| `-f, --format` | `txt,srt` | Any of `txt,srt,vtt` |
| `-l, --language` | auto | Spoken language code, e.g. `en`. Set it if auto-detect guesses wrong. |
| `--device` | `auto` | `cpu` or `cuda`. `auto` uses an NVIDIA GPU if there is one. |
| `-q, --quiet` | off | Don't print the transcript while it runs |
| `-v, --verbose` | off | Show yt-dlp's full download log (useful when a download fails) |
| `--cookies-from-browser` | off | Use your logged-in session from `chrome`, `firefox`, `safari`, `edge`, ... for videos that need an account |

Colors turn off automatically when output isn't a terminal, or when
[`NO_COLOR`](https://no-color.org) is set.

`python -m video_transcript ...` works too.

## Speed

Whisper is much faster on a GPU. Rough times for a 38-minute talk with `small`:

| Machine | Time |
|---|---|
| 2–4 core cloud VM, no GPU | 8–15 min |
| Modern 8-core laptop | 3–6 min |
| NVIDIA GPU | 1–2 min |

`base` is about 2–3× faster than `small` but makes more mistakes.

## Notes

- Whisper sometimes mishears names (it heard "Potato" for "poteto"). Skim the
  output for proper nouns.
- Silence and music are skipped (voice-activity filter), which stops Whisper
  from inventing text during long pauses.
- Some X videos need a logged-in account. Log in to X in your browser, then
  add `--cookies-from-browser chrome` (or your browser's name).
- The link has to point at a post with a video attached. A post that only
  links somewhere, or has just images, gets a "No video found" message.
- yt-dlp's X support breaks now and then when X changes things. If downloads
  that used to work start failing, update with `pipx upgrade video-transcript`
  or `pip install -U yt-dlp`.
- Audio is decoded with ffmpeg rather than PyAV. faster-whisper 1.2.1's
  built-in decoder calls `av.open(..., metadata_errors=...)`, which PyAV 13+
  removed.
- If `NO_PROXY` contains IPv6 entries like `[::1]`, they're removed at startup
  because httpx (used to download Whisper models) can't parse them.
- Respect the rights of whoever made the video and the platform's terms.

## Development

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest
```

To regenerate `docs/demo.gif` from a real run:

```bash
.venv/bin/pip install -e '.[demo]'
.venv/bin/python scripts/record_demo.py rec.json -- <url>
head -n 7 out/*.srt > srt.txt
.venv/bin/python scripts/render_demo.py rec.json "video-transcript <url>" docs/demo.gif \
    --after-cmd "head -n 7 out/*.srt" --after-output srt.txt
```

## License

MIT. See [LICENSE](LICENSE).
