# video-transcript

Word-for-word transcripts from any video URL: X, YouTube, Vimeo, and anything
else [yt-dlp](https://github.com/yt-dlp/yt-dlp) can download.

X has no transcript button. This downloads the video's audio and transcribes
it on your own machine with Whisper
([faster-whisper](https://github.com/SYSTRAN/faster-whisper)). You don't need
an API key or a subscription, and nothing gets uploaded.

## Install

Needs Python 3.10+ and [ffmpeg](https://ffmpeg.org/download.html) on your PATH
(`brew install ffmpeg`, `sudo apt install ffmpeg`, or `winget install ffmpeg`).

```bash
pipx install git+https://github.com/<owner>/video-transcript-tool
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
- Some X videos need a logged-in account to download. yt-dlp's X support also
  breaks now and then when X changes things. If downloads fail, update yt-dlp
  with `pipx upgrade video-transcript` or `pip install -U yt-dlp`.
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
