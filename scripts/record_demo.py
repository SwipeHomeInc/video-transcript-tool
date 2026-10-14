"""Run video-transcript for real and record its output with timestamps.

Usage: python scripts/record_demo.py <recording.json> -- <video-transcript args...>

Runs the tool inside a pseudo-terminal so it behaves exactly as it does for a
user (progress bar included). The recording feeds scripts/render_demo.py,
which turns it into docs/demo.gif.
"""
import json
import os
import pty
import subprocess
import sys
import time


def main() -> None:
    out_path = sys.argv[1]
    args = sys.argv[sys.argv.index("--") + 1:]
    env = dict(os.environ, PYTHONUNBUFFERED="1", COLUMNS="90", LINES="40", TERM="xterm-256color")
    master, slave = pty.openpty()
    start = time.monotonic()
    proc = subprocess.Popen(
        [sys.executable, "-m", "video_transcript", *args],
        stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True,
    )
    os.close(slave)
    chunks = []
    while True:
        try:
            data = os.read(master, 4096)
        except OSError:  # EIO once the child closes the terminal
            break
        if not data:
            break
        chunks.append({"t": round(time.monotonic() - start, 3), "data": data.decode("utf-8", "replace")})
    code = proc.wait()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"args": args, "exit": code, "chunks": chunks}, f, indent=1)
    print(f"exit={code} chunks={len(chunks)} duration={time.monotonic() - start:.1f}s")


if __name__ == "__main__":
    main()
