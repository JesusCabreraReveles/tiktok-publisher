#!/usr/bin/env python3
"""
make_video.py - Turns a short script (JSON) into a vertical TikTok video.

Free and local: Kokoro voice (runs on CPU, Raspberry Pi 5 OK) + Pillow + ffmpeg.

Usage:
    python3 make_video.py script.json -o out.mp4

Script format (JSON):
{
  "lang": "en",                 # "en" or "es"
  "voice": "am_michael",        # optional; defaults per language
  "tag": "AI · TUESDAY",        # small label at the top
  "brand": "geminislabs.com",   # small text at the bottom
  "slides": [
    {"screen": "Big headline on screen", "say": "What the voice says."},
    ...
  ]
}
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- settings ----------
W, H = 1080, 1920
FPS = 30
GAP = 0.35            # silence between slides (seconds)
WORDS_PER_CAPTION = 4
DEFAULT_VOICE = {"en": "am_michael", "es": "em_alex"}
KOKORO_LANG = {"en": "en-us", "es": "es"}

# Colors
BG_TOP = (11, 16, 32)
BG_BOTTOM = (24, 18, 58)
ACCENT = (124, 92, 255)
ACCENT_2 = (0, 214, 182)
WHITE = (255, 255, 255)
MUTED = (170, 176, 200)

# TikTok covers the right edge and the bottom with its own buttons/caption.
SAFE_LEFT, SAFE_RIGHT = 90, W - 170
SAFE_TOP = 230


def find_font(names):
    dirs = [
        os.path.join(HERE, "fonts"),
        "/usr/share/fonts/opentype/inter",
        "/usr/share/fonts/truetype/inter",
        "/usr/share/fonts/truetype/dejavu",
    ]
    for n in names:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    sys.exit(f"Font not found: {names}. Install fonts-inter or put the .otf in ./fonts")


FONT_BLACK = find_font(["Inter-Black.otf", "Inter-Black.ttf", "DejaVuSans-Bold.ttf"])
FONT_BOLD = find_font(["Inter-Bold.otf", "Inter-Bold.ttf", "DejaVuSans-Bold.ttf"])
FONT_SEMI = find_font(["Inter-SemiBold.otf", "Inter-SemiBold.ttf", "DejaVuSans.ttf"])


# ---------- voice ----------
def tts(slides, lang, voice, workdir):
    from kokoro_onnx import Kokoro

    model = os.environ.get("KOKORO_MODEL", os.path.join(HERE, "voices", "kokoro-v1.0.int8.onnx"))
    voices = os.environ.get("KOKORO_VOICES", os.path.join(HERE, "voices", "voices-v1.0.bin"))
    k = Kokoro(model, voices)
    out = []
    for i, s in enumerate(slides):
        audio, sr = k.create(s["say"], voice=voice, speed=1.05, lang=KOKORO_LANG[lang])
        path = os.path.join(workdir, f"a{i:02d}.wav")
        sf.write(path, audio, sr)
        out.append((path, len(audio) / sr, audio, sr))
        print(f"  voice {i + 1}/{len(slides)}: {len(audio) / sr:.1f}s")
    return out


# ---------- captions ----------
def caption_chunks(text, duration):
    """Split spoken text into short chunks; time each by its share of letters."""
    words = text.split()
    chunks, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= WORDS_PER_CAPTION or re.search(r"[.,!?;:]$", w):
            chunks.append(" ".join(cur))
            cur = []
    if cur:
        chunks.append(" ".join(cur))
    weights = [max(len(c), 1) for c in chunks]
    total = sum(weights)
    return [(c, duration * w / total) for c, w in zip(chunks, weights)]


# ---------- drawing ----------
def wrap(draw, text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fit_headline(draw, text, max_w, max_h):
    for size in range(124, 60, -4):
        f = ImageFont.truetype(FONT_BLACK, size)
        lines = wrap(draw, text, f, max_w)
        lh = int(size * 1.12)
        if len(lines) * lh <= max_h:
            return f, lines, lh
    f = ImageFont.truetype(FONT_BLACK, 60)
    return f, wrap(draw, text, f, max_w), 68


def background():
    grad = np.linspace(0, 1, H)[:, None]
    top, bot = np.array(BG_TOP), np.array(BG_BOTTOM)
    arr = (top * (1 - grad) + bot * grad)[:, None, :].repeat(W, axis=1)
    img = Image.fromarray(arr.astype("uint8"), "RGB")
    # soft glow circle
    glow = Image.new("L", (W, H), 0)
    gd = ImageDraw.Draw(glow)
    gd.ellipse((W - 700, -300, W + 300, 700), fill=70)
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img = Image.composite(Image.new("RGB", (W, H), ACCENT), img, glow)
    return img


def draw_frame(base, tag, brand, headline, caption, idx, total, progress):
    img = base.copy()
    d = ImageDraw.Draw(img)

    # tag pill
    ft = ImageFont.truetype(FONT_BOLD, 34)
    tw = d.textlength(tag, font=ft)
    d.rounded_rectangle((SAFE_LEFT, SAFE_TOP, SAFE_LEFT + tw + 56, SAFE_TOP + 70), radius=35, fill=ACCENT)
    d.text((SAFE_LEFT + 28, SAFE_TOP + 15), tag, font=ft, fill=WHITE)

    # slide counter
    fc = ImageFont.truetype(FONT_SEMI, 34)
    cnt = f"{idx + 1}/{total}"
    d.text((SAFE_RIGHT - d.textlength(cnt, font=fc), SAFE_TOP + 16), cnt, font=fc, fill=MUTED)

    # headline
    max_w = SAFE_RIGHT - SAFE_LEFT
    fh, lines, lh = fit_headline(d, headline, max_w, 620)
    y = 420
    d.rectangle((SAFE_LEFT, y + 6, SAFE_LEFT + 12, y + lh * len(lines) - 14), fill=ACCENT_2)
    for ln in lines:
        d.text((SAFE_LEFT + 44, y), ln, font=fh, fill=WHITE)
        y += lh

    # caption (what is being said right now)
    if caption:
        fcap = ImageFont.truetype(FONT_BLACK, 66)
        cap_lines = wrap(d, caption, fcap, max_w - 40)
        cy = 1190
        for ln in cap_lines:
            lw = d.textlength(ln, font=fcap)
            x = SAFE_LEFT + (max_w - lw) / 2
            d.rounded_rectangle((x - 22, cy - 8, x + lw + 22, cy + 82), radius=18, fill=(0, 0, 0))
            d.text((x, cy), ln, font=fcap, fill=(255, 230, 90))
            cy += 96

    # progress bar
    by = 1470
    d.rounded_rectangle((SAFE_LEFT, by, SAFE_RIGHT, by + 10), radius=5, fill=(60, 60, 90))
    d.rounded_rectangle((SAFE_LEFT, by, SAFE_LEFT + int((SAFE_RIGHT - SAFE_LEFT) * progress), by + 10),
                        radius=5, fill=ACCENT_2)

    # brand
    fb = ImageFont.truetype(FONT_SEMI, 34)
    d.text((SAFE_LEFT, by + 34), brand, font=fb, fill=MUTED)
    return img


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out", default="out.mp4")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not installed")

    with open(args.script, encoding="utf-8") as f:
        sc = json.load(f)
    lang = sc.get("lang", "en")
    voice = sc.get("voice") or DEFAULT_VOICE[lang]
    slides = sc["slides"]
    tag = sc.get("tag", "")
    brand = sc.get("brand", "")

    work = tempfile.mkdtemp(prefix="tkv_")
    try:
        print("1) Generating voice...")
        audios = tts(slides, lang, voice, work)

        # Join audio with gaps
        sr = audios[0][3]
        gap = np.zeros(int(GAP * sr), dtype=np.float32)
        parts = []
        for _, _, a, _ in audios:
            parts += [a.astype(np.float32), gap]
        full = np.concatenate(parts)
        audio_path = os.path.join(work, "voice.wav")
        sf.write(audio_path, full, sr)
        total_dur = len(full) / sr

        print("2) Drawing frames...")
        base = background()
        concat_lines, t = [], 0.0
        n = 0
        for i, (s, (_, dur, _, _)) in enumerate(zip(slides, audios)):
            chunks = caption_chunks(s["say"], dur) + [("", GAP)]
            for cap, cdur in chunks:
                t += cdur
                img = draw_frame(base, tag, brand, s["screen"], cap, i, len(slides), t / total_dur)
                p = os.path.join(work, f"f{n:04d}.png")
                img.save(p)
                concat_lines += [f"file '{p}'", f"duration {cdur:.3f}"]
                n += 1
        concat_lines.append(f"file '{p}'")  # ffmpeg concat needs the last frame repeated
        lst = os.path.join(work, "frames.txt")
        with open(lst, "w") as f:
            f.write("\n".join(concat_lines))

        print("3) Encoding video...")
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", lst,
            "-i", audio_path,
            "-vf", f"fps={FPS},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-shortest", "-movflags", "+faststart",
            args.out,
        ]
        subprocess.run(cmd, check=True)
        print(f"Done: {args.out} ({total_dur:.1f}s)")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
