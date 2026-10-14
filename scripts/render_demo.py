"""Render a recording from scripts/record_demo.py into docs/demo.gif.

Usage:
    python scripts/render_demo.py <recording.json> <command> <out.gif>
        [--after-cmd CMD --after-output FILE]

<command> is the command line shown being typed. The tool's output is replayed
exactly as recorded (colors included) on its real timeline; only waits longer
than MAX_WAIT are shortened. Needs Pillow (pip install -e '.[demo]').
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

COLS, ROWS = 106, 28
SCALE = 2  # render at 2x so it stays sharp on high-DPI screens
FONT_SIZE = 15 * SCALE
LINE_H = int(FONT_SIZE * 1.45)
PAD = 22 * SCALE
BAR_H = 34 * SCALE
MAX_WAIT = 1.4  # seconds; longer real waits are trimmed to this
TYPE_DELAY = 0.045

BG = (13, 17, 23)
BAR = (22, 27, 34)
FG = (230, 237, 243)
DIM = (125, 133, 144)
SGR_COLORS = {"32": (63, 185, 80), "36": (86, 212, 221), "90": DIM}
PROMPT = (63, 185, 80)
BLOCKS = {"\u2588", "\u2591"}
BAR_EMPTY = (48, 54, 61)
DOTS = [(255, 95, 87), (254, 188, 46), (40, 200, 64)]

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
FONT = ImageFont.truetype(str(FONT_DIR / "DejaVuSansMono.ttf"), FONT_SIZE)
FONT_BOLD = ImageFont.truetype(str(FONT_DIR / "DejaVuSansMono-Bold.ttf"), FONT_SIZE)
CELL_W = FONT.getlength("M")
WIDTH = int(PAD * 2 + CELL_W * COLS)
HEIGHT = int(BAR_H + PAD * 2 + LINE_H * ROWS)


class Term:
    """Just enough of a terminal: SGR colors, \\r, \\n, erase-line, wrapping."""

    def __init__(self) -> None:
        self.lines: list[list[tuple[str, tuple]]] = [[]]
        self.col = 0
        self.style = (FG, False)  # (color, bold)
        self.cursor_visible = True

    def _put(self, ch: str) -> None:
        if self.col >= COLS:
            self.lines.append([])
            self.col = 0
        line = self.lines[-1]
        while len(line) < self.col:
            line.append((" ", (FG, False)))
        if self.col < len(line):
            line[self.col] = (ch, self.style)
        else:
            line.append((ch, self.style))
        self.col += 1

    def _sgr(self, params: str) -> None:
        color, bold = self.style
        for p in (params or "0").split(";"):
            if p == "0":
                color, bold = FG, False
            elif p == "1":
                bold = True
            elif p == "2":
                color = DIM
            elif p in SGR_COLORS:
                color = SGR_COLORS[p]
        self.style = (color, bold)

    def write(self, data: str, style: tuple | None = None) -> None:
        if style:
            self.style = style
        for m in re.finditer(r"\x1b\[([0-9;]*)([A-Za-z])|(\r\n|\n)|(\r)|(.)", data, re.S):
            if m.group(2) == "m":
                self._sgr(m.group(1))
            elif m.group(2) == "K":
                del self.lines[-1][self.col:]
            elif m.group(3):
                self.lines.append([])
                self.col = 0
            elif m.group(4):
                self.col = 0
            elif m.group(5) and m.group(5).isprintable():
                self._put(m.group(5))
        if style:
            self.style = (FG, False)

    def render(self, cursor: bool) -> Image.Image:
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, WIDTH, BAR_H], fill=BAR)
        for i, c in enumerate(DOTS):
            cx, cy, r = PAD + i * 20 * SCALE, BAR_H // 2, 6 * SCALE
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=c)
        title = "video-transcript"
        d.text(((WIDTH - FONT.getlength(title) * 0.8) / 2, BAR_H / 2), title,
               font=FONT.font_variant(size=int(FONT_SIZE * 0.8)), fill=DIM, anchor="lm")

        visible = self.lines[-ROWS:]
        top = BAR_H + PAD
        for row, line in enumerate(visible):
            y = top + row * LINE_H
            for col, (ch, (color, bold)) in enumerate(line):
                x = PAD + col * CELL_W
                if ch in BLOCKS:
                    # Draw bar blocks as shapes: glyphs leave seams between cells.
                    d.rectangle([x, y + 3 * SCALE, x + CELL_W, y + FONT_SIZE + 2 * SCALE],
                                fill=color if ch == "\u2588" else BAR_EMPTY)
                elif ch != " ":
                    d.text((x, y), ch, font=FONT_BOLD if bold else FONT, fill=color)
        if cursor:
            row = len(visible) - 1
            x = PAD + min(self.col, COLS - 1) * CELL_W
            y = top + row * LINE_H
            d.rectangle([x, y + 2 * SCALE, x + CELL_W - SCALE, y + FONT_SIZE + 4 * SCALE], fill=FG)
        return img


class Movie:
    def __init__(self) -> None:
        self.term = Term()
        self.frames: list[Image.Image] = []
        self.durations: list[int] = []

    def snap(self, seconds: float, cursor: bool = True) -> None:
        ms = max(20, int(round(seconds * 1000 / 10)) * 10)
        self.frames.append(self.term.render(cursor))
        self.durations.append(ms)

    def idle(self, seconds: float) -> None:
        # Blink the cursor during pauses so the GIF never looks frozen.
        while seconds > 0:
            step = min(0.5, seconds)
            self.snap(step, cursor=len(self.frames) % 2 == 0)
            seconds -= step

    def prompt(self) -> None:
        self.term.write("$ ", (PROMPT, True))

    def type(self, text: str, paste_from: int | None = None) -> None:
        for i, ch in enumerate(text):
            if paste_from is not None and i >= paste_from:
                self.term.write(text[i:])
                self.snap(0.5)
                break
            self.term.write(ch)
            self.snap(TYPE_DELAY)
        self.term.write("\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("recording")
    ap.add_argument("command")
    ap.add_argument("out")
    ap.add_argument("--after-cmd")
    ap.add_argument("--after-output")
    args = ap.parse_args()

    chunks = json.loads(Path(args.recording).read_text(encoding="utf-8"))["chunks"]
    mv = Movie()
    mv.prompt()
    mv.idle(0.8)
    # Type the program name, "paste" the long URL.
    url_at = args.command.find("http")
    mv.type(args.command, paste_from=url_at if url_at > 0 else None)

    prev_t = 0.0
    for i, chunk in enumerate(chunks):
        gap = chunk["t"] - prev_t
        if mv.frames and gap > 0:
            # Credit the wait to the frame on screen before this chunk.
            wait = min(gap, MAX_WAIT)
            if wait > 0.6:
                mv.durations[-1] = 20
                mv.idle(wait)
            else:
                mv.durations[-1] = max(mv.durations[-1], int(wait * 1000) or 20)
        mv.term.write(chunk["data"])
        mv.snap(0.03)
        prev_t = chunk["t"]

    if args.after_cmd:
        mv.idle(1.6)
        mv.prompt()
        mv.type(args.after_cmd)
        mv.term.write(Path(args.after_output).read_text(encoding="utf-8").rstrip("\n") + "\n")
        mv.snap(0.1)
    mv.prompt()
    mv.idle(5.0)

    # One shared palette keeps colors stable between frames and the file small.
    # Sample frames from the whole run so no color (e.g. the progress bar,
    # long scrolled away by the end) is missing from the palette.
    sample = mv.frames[:: max(1, len(mv.frames) // 8)] + [mv.frames[-1]]
    sheet = Image.new("RGB", (WIDTH, HEIGHT * len(sample)))
    for i, f in enumerate(sample):
        sheet.paste(f, (0, HEIGHT * i))
    palette = sheet.quantize(colors=128, method=Image.Quantize.MEDIANCUT)
    frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in mv.frames]
    frames[0].save(args.out, save_all=True, append_images=frames[1:],
                   duration=mv.durations, loop=0, optimize=True, disposal=1)
    total = sum(mv.durations) / 1000
    print(f"{args.out}: {len(frames)} frames, {total:.1f}s, {WIDTH}x{HEIGHT}, "
          f"{Path(args.out).stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
