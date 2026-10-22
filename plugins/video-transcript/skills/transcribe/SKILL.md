---
name: transcribe
description: Transcribe a video from a link (X/Twitter, YouTube, Vimeo, or any page yt-dlp supports) into a word-for-word .txt and timestamped .srt, then summarize it or answer questions about it. Use when the user pastes a video URL and wants the transcript, the text, subtitles, a summary, key points, or quotes from the video.
when_to_use: Triggers include "transcribe this", "get me the transcript", "what does this video say", "summarize this video", "pull the quotes from this", or a bare x.com / twitter.com / youtube.com link to a video post.
argument-hint: <video-url> [--fast] [--model base|small|medium]
allowed-tools: Bash(video-transcript *) Bash(command -v *) Bash(ls *) Read
---

# Transcribe a video

Turn a video link into a transcript with the `video-transcript` command-line
tool (https://github.com/SwipeHomeInc/video-transcript-tool). It downloads the
audio with yt-dlp and transcribes it on this machine with Whisper. Nothing is
uploaded and no API key is needed.

Arguments: $ARGUMENTS

## 1. Make sure the tool is installed

Run `command -v video-transcript`. If it prints a path, go to step 2.

If it's missing, tell the user it isn't installed and ask before installing:

1. ffmpeg must be on PATH (`command -v ffmpeg`). If missing, give the user the
   command for their OS and let them run it: `brew install ffmpeg` (macOS),
   `winget install ffmpeg` (Windows), `sudo apt install ffmpeg` (Debian/Ubuntu).
2. Install the tool with pipx:
   `pipx install git+https://github.com/SwipeHomeInc/video-transcript-tool`
   If pipx is missing: `python3 -m pip install --user pipx && python3 -m pipx ensurepath`,
   then use `python3 -m pipx install ...` for this session.
3. Confirm with `video-transcript --version`.

The first transcription also downloads the Whisper model (about 500 MB for
`small`). Mention that once so a slow first run doesn't look stuck.

## 2. Run it

```
video-transcript "<url>" -o transcripts -q
```

- Always quote the URL. Strip tracking parameters only if the link fails.
- `-o transcripts` keeps output in one folder; files are named after the video,
  so many videos can share it. The tool creates the folder itself, so don't
  run `mkdir` or `cd` first (that only adds a permission prompt).
- `-q` stops the transcript scrolling past in the tool output; you'll read the
  file instead.
- Add `--fast` only if the user asks for speed. It's about 2x faster on CPU but
  can occasionally skip a phrase. Pass `--model base` for a rough, quicker
  draft, or `--model medium` when accuracy matters more than time.
- Add `-l <code>` (e.g. `-l es`) if the user says what language is spoken.

**Long videos:** transcription runs at roughly 2-3x realtime on a 4-core CPU
with no GPU and the default settings, so the wait is roughly a third to half
the video's length (a 71-minute video took about 31 minutes, a 2-hour one
about 41). It depends on the machine; a GPU is much faster.

Long runs outlast a foreground command's time limit, and a restart loses all
the progress. So decide before the first run:

- If you know the video is over about 10 minutes (the user said so, or the
  post shows the length), run the command in the background from the start
  if your environment supports it. Tell the user the rough wait.
- If you don't know the length, run it in the background anyway; it costs
  nothing for a short video. Once the tool prints `<length> of audio`, give
  the user the rough wait.
- Continue when it finishes. Don't restart a run that's still going.

## 3. Handle failures

The tool prints one line starting with `✗` that explains the problem. Act on it:

- **No video found at that link**: the post has no video attached (only a link
  preview or images). Tell the user; don't retry.
- **Needs a logged-in account**: ask which browser they're logged in with, then
  re-run with `--cookies-from-browser <chrome|firefox|safari|edge>`.
- **Doesn't exist**: the post was deleted or the link has a typo.
- **Download failed** for another reason: re-run once with `-v` to see the full
  log. If X or YouTube changed something, `pipx upgrade video-transcript` often
  fixes it.

## 4. Deliver the result

The tool prints the paths it wrote under `✓ Done in ...`: a `.txt` (plain
text) and an `.srt` (timestamped subtitles), both named after the video ID.

If it prints `✓ Already transcribed` instead, that video was done before:
the paths listed are the existing transcripts, so read those. Only re-run
with `--force` if the user asks to redo it (say, with `--model medium` for
better accuracy).

1. Tell the user where the files are.
2. Read the `.txt` and give a short summary: what the video covers and its main
   points. Offer to pull out specific quotes, timestamps (from the `.srt`), or
   answer questions about it.
3. Don't paste the whole transcript into the chat unless the user asks for it.
   Long transcripts flood the conversation, and the file is already on their
   machine. When quoting, keep quotes short and cite the timestamp.
4. Whisper often mishears names, products, and jargon. When summarizing, flag
   any names that look misheard instead of silently "correcting" them.
5. The account that posted the video isn't necessarily who's talking in it.
   People often post clips of other people's talks. Name a speaker only if
   the transcript or the post says who it is; otherwise say who posted it and
   that the speaker isn't named. Don't credit the poster as the speaker.

The video belongs to whoever made it. Transcribing for personal notes,
research, or accessibility is the intended use; remind the user of that if
they want to republish a full transcript.
