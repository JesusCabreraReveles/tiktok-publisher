#!/usr/bin/env python3
"""
make_video.py - Turns a short script (JSON) into a vertical TikTok video.

Free and local: Kokoro voice (runs on CPU, Raspberry Pi 5 OK) + Pillow + ffmpeg.

Usage:
    python3 make_video.py script.json -o out.mp4
    python3 make_video.py script.json --still preview.png   # one frame, no voice (quick look)

Script format (JSON):
{
  "lang": "en",                 # "en" or "es"
  "voice": "am_michael",        # optional; defaults per language
  "tag": "AI · TUESDAY",        # small label at the top
  "brand": "geminislabs.com",   # small text at the bottom
  "style": "ai",                # optional; see THEMES. Normally left out (see below)
  "slides": [
    {"screen": "Big headline on screen", "say": "What the voice says."},
    ...
  ]
}

Look of each video (v1.1):
  - Color palette by theme. Picked from the file name, so the daily task needs no changes:
        YYYY-MM-DD.json        -> weekday (mon leadership, tue ai, wed engineering,
                                  thu founders, fri trends; sat/sun -> trends)
        YYYY-MM-DD-book.json   -> book
        YYYY-MM-DD-promo.json  -> fri geminis, sat nexus, sun clash
    "style" in the script overrides it.
  - Background pattern (grid, dots, stripes, waves, rings, network) rotates by date, so two
    days in a row never look the same and the same weekday changes from week to week.
  - The background pans slowly during the video so it never looks like a still image.
"""
import argparse
import datetime as dt
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- settings ----------
W, H = 1080, 1920
FPS = 30
GAP = 0.35            # silence between slides (seconds)
WORDS_PER_CAPTION = 4
DEFAULT_VOICE = {"en": "am_michael", "es": "em_alex"}
KOKORO_LANG = {"en": "en-us", "es": "es"}
PAN = 220             # how many pixels the background drifts over the whole video

WHITE = (255, 255, 255)
MUTED = (170, 176, 200)
DARK = (14, 14, 22)

# TikTok covers the right edge and the bottom with its own buttons/caption.
SAFE_LEFT, SAFE_RIGHT = 90, W - 170
SAFE_TOP = 230

# ---------- themes ----------
# top/bottom: background gradient. accent: tag pill + glow. accent2: headline bar + progress.
# highlight: color of the spoken captions (on a black box).
THEMES = {
    "leadership":  dict(top=(8, 18, 40),  bottom=(18, 38, 78),  accent=(226, 164, 52),
                        accent2=(255, 214, 120), highlight=(255, 214, 120)),
    "ai":          dict(top=(11, 16, 32), bottom=(24, 18, 58),  accent=(124, 92, 255),
                        accent2=(0, 214, 182),   highlight=(255, 230, 90)),
    "engineering": dict(top=(5, 22, 20),  bottom=(8, 46, 40),   accent=(0, 168, 120),
                        accent2=(190, 240, 80),  highlight=(190, 240, 80)),
    "founders":    dict(top=(30, 12, 8),  bottom=(66, 24, 14),  accent=(255, 106, 58),
                        accent2=(255, 190, 80),  highlight=(255, 222, 130)),
    "trends":      dict(top=(24, 8, 30),  bottom=(54, 12, 52),  accent=(236, 64, 156),
                        accent2=(90, 200, 255),  highlight=(120, 222, 255)),
    "book":        dict(top=(6, 22, 32),  bottom=(12, 44, 62),  accent=(0, 160, 214),
                        accent2=(255, 196, 86),  highlight=(255, 218, 120)),
    "geminis":     dict(top=(10, 12, 36), bottom=(16, 34, 72),  accent=(56, 120, 255),
                        accent2=(0, 224, 255),   highlight=(140, 236, 255)),
    "nexus":       dict(top=(10, 10, 14), bottom=(28, 30, 40),  accent=(0, 190, 255),
                        accent2=(160, 255, 120), highlight=(170, 255, 140)),
    "clash":       dict(top=(26, 4, 8),   bottom=(62, 8, 18),   accent=(226, 36, 60),
                        accent2=(255, 196, 50),  highlight=(255, 214, 90)),
}
WEEKDAY_THEME = ["leadership", "ai", "engineering", "founders", "trends", "trends", "trends"]
PROMO_THEME = {4: "geminis", 5: "nexus", 6: "clash"}   # fri, sat, sun
PATTERNS = ["grid", "dots", "stripes", "waves", "rings", "network"]


def pick_look(script_path, sc):
    """Return (theme_name, pattern_name, seed) from the file name and the script."""
    name = os.path.basename(script_path)
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:-([a-z]+))?\.json$", name)
    date = None
    if m:
        try:
            date = dt.date.fromisoformat(m.group(1))
        except ValueError:
            date = None
    kind = m.group(2) if m else None

    theme = sc.get("style")
    if theme not in THEMES:
        if date is None:
            theme = "ai"
        elif kind == "book":
            theme = "book"
        elif kind == "promo":
            theme = PROMO_THEME.get(date.weekday(), "geminis")
        else:
            theme = WEEKDAY_THEME[date.weekday()]

    if date is None:
        seed = sum(map(ord, name))
        pattern = PATTERNS[seed % len(PATTERNS)]
    else:
        seed = date.toordinal()
        # book/promo videos are shifted so they never share the daily video's pattern
        shift = {"book": 3, "promo": 2}.get(kind, 0)
        pattern = PATTERNS[(seed + shift) % len(PATTERNS)]
        seed = seed * 10 + shift
    return theme, pattern, seed


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
    import soundfile as sf
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
        widest = max((draw.textlength(ln, font=f) for ln in lines), default=0)
        # a single long word (e.g. "¿Microservicios") can't wrap: shrink until it fits too
        if len(lines) * lh <= max_h and widest <= max_w:
            return f, lines, lh
    f = ImageFont.truetype(FONT_BLACK, 60)
    return f, wrap(draw, text, f, max_w), 68


def ink_for(color):
    """White or dark text, whichever reads better on `color`."""
    r, g, b = color
    return DARK if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else WHITE


def draw_pattern(layer, pattern, color, rng):
    """Draw a subtle pattern on an RGBA layer (same size as the background)."""
    d = ImageDraw.Draw(layer)
    w, h = layer.size
    soft = color + (34,)
    strong = color + (64,)
    if pattern == "grid":
        step = 96
        for i, x in enumerate(range(0, w, step)):
            d.line((x, 0, x, h), fill=strong if i % 4 == 0 else soft, width=2)
        for i, y in enumerate(range(0, h, step)):
            d.line((0, y, w, y), fill=strong if i % 4 == 0 else soft, width=2)
    elif pattern == "dots":
        step = 64
        for y in range(0, h, step):
            off = step // 2 if (y // step) % 2 else 0
            for x in range(-step, w, step):
                r = 5
                d.ellipse((x + off - r, y - r, x + off + r, y + r), fill=strong)
    elif pattern == "stripes":
        step = 110
        for x in range(-h, w, step):
            d.line((x, h, x + h, 0), fill=color + (20,), width=22)
    elif pattern == "waves":
        amp, step = rng.randint(28, 48), 120
        phase = rng.random() * math.tau
        for i, y0 in enumerate(range(-step, h + step, step)):
            pts = [(x, y0 + amp * math.sin(x / 140 + phase + i * 0.6)) for x in range(0, w + 20, 20)]
            d.line(pts, fill=strong if i % 3 == 0 else soft, width=3)
    elif pattern == "rings":
        cx = rng.choice([-0.1, 0.15, 0.85, 1.1]) * w
        cy = rng.choice([0.2, 0.55, 0.85]) * h
        for i, r in enumerate(range(80, int(max(w, h) * 1.6), 70)):
            d.ellipse((cx - r, cy - r, cx + r, cy + r),
                      outline=color + ((95,) if i % 3 == 0 else (50,)), width=3)
    elif pattern == "network":
        pts = [(rng.uniform(0, w), rng.uniform(0, h)) for _ in range(70)]
        for i, (x1, y1) in enumerate(pts):
            near = sorted(pts, key=lambda p: (p[0] - x1) ** 2 + (p[1] - y1) ** 2)[1:3]
            for x2, y2 in near:
                d.line((x1, y1, x2, y2), fill=color + (55,), width=2)
        for x, y in pts:
            r = rng.choice([5, 7, 10])
            d.ellipse((x - r, y - r, x + r, y + r), fill=color + (100,))


def background(theme, pattern, seed):
    """Background bigger than the frame (by PAN) so ffmpeg can pan across it."""
    t = THEMES[theme]
    bw, bh = W + PAN, H + PAN
    rng = random.Random(seed)
    grad = np.linspace(0, 1, bh)[:, None]
    top, bot = np.array(t["top"]), np.array(t["bottom"])
    arr = (top * (1 - grad) + bot * grad)[:, None, :].repeat(bw, axis=1)
    img = Image.fromarray(arr.astype("uint8"), "RGB")

    # pattern (blurred a touch so it stays in the back)
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw_pattern(layer, pattern, t["accent2"], rng)
    layer = layer.filter(ImageFilter.GaussianBlur(1.2))
    img = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")

    # soft glow in a corner that changes from day to day
    glow = Image.new("L", (bw, bh), 0)
    gd = ImageDraw.Draw(glow)
    corners = [(bw - 700, -300), (-300, -300), (bw - 700, bh - 700), (-300, bh - 800)]
    gx, gy = corners[rng.randrange(len(corners))]
    gd.ellipse((gx, gy, gx + 1000, gy + 1000), fill=80)
    glow = glow.filter(ImageFilter.GaussianBlur(180))
    img = Image.composite(Image.new("RGB", (bw, bh), t["accent"]), img, glow)

    # darken the middle where the text sits, so any pattern stays readable
    shade = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(shade).rectangle((0, int(bh * 0.18), bw, int(bh * 0.82)), fill=70)
    shade = shade.filter(ImageFilter.GaussianBlur(160))
    img = Image.composite(Image.new("RGB", (bw, bh), (0, 0, 0)), img, shade)
    return img


def draw_frame(theme, tag, brand, headline, caption, idx, total, progress):
    """Transparent layer with all the text; it goes on top of the moving background."""
    t = THEMES[theme]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # tag pill
    ft = ImageFont.truetype(FONT_BOLD, 34)
    tw = d.textlength(tag, font=ft)
    d.rounded_rectangle((SAFE_LEFT, SAFE_TOP, SAFE_LEFT + tw + 56, SAFE_TOP + 70), radius=35, fill=t["accent"])
    d.text((SAFE_LEFT + 28, SAFE_TOP + 15), tag, font=ft, fill=ink_for(t["accent"]))

    # slide counter
    fc = ImageFont.truetype(FONT_SEMI, 34)
    cnt = f"{idx + 1}/{total}"
    d.text((SAFE_RIGHT - d.textlength(cnt, font=fc), SAFE_TOP + 16), cnt, font=fc, fill=MUTED)

    # headline
    max_w = SAFE_RIGHT - SAFE_LEFT
    fh, lines, lh = fit_headline(d, headline, max_w - 44, 620)  # text starts 44 px in
    y = 420
    d.rectangle((SAFE_LEFT, y + 6, SAFE_LEFT + 12, y + lh * len(lines) - 14), fill=t["accent2"])
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
            d.rounded_rectangle((x - 22, cy - 8, x + lw + 22, cy + 82), radius=18, fill=(0, 0, 0, 255))
            d.text((x, cy), ln, font=fcap, fill=t["highlight"])
            cy += 96

    # progress bar
    by = 1470
    d.rounded_rectangle((SAFE_LEFT, by, SAFE_RIGHT, by + 10), radius=5, fill=(255, 255, 255, 50))
    d.rounded_rectangle((SAFE_LEFT, by, SAFE_LEFT + int((SAFE_RIGHT - SAFE_LEFT) * progress), by + 10),
                        radius=5, fill=t["accent2"])

    # brand
    fb = ImageFont.truetype(FONT_SEMI, 34)
    d.text((SAFE_LEFT, by + 34), brand, font=fb, fill=MUTED)
    return img


def pan_expr(seed, dur):
    """ffmpeg crop x/y expressions: slow drift in one of four diagonal directions."""
    sx, sy = [(1, 1), (-1, 1), (1, -1), (-1, -1)][seed % 4]
    k = f"min(t/{dur:.3f},1)"
    x = f"{PAN}*{k}" if sx > 0 else f"{PAN}*(1-{k})"
    y = f"{PAN}*{k}" if sy > 0 else f"{PAN}*(1-{k})"
    return x, y


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("-o", "--out", default="out.mp4")
    ap.add_argument("--still", help="write one PNG of the first slide (no voice, no video)")
    args = ap.parse_args()

    with open(args.script, encoding="utf-8") as f:
        sc = json.load(f)
    lang = sc.get("lang", "en")
    voice = sc.get("voice") or DEFAULT_VOICE[lang]
    slides = sc["slides"]
    tag = sc.get("tag", "")
    brand = sc.get("brand", "")
    theme, pattern, seed = pick_look(args.script, sc)
    print(f"Look: theme={theme} pattern={pattern}")

    if args.still:
        bg = background(theme, pattern, seed)
        cx, cy = PAN // 2, PAN // 2
        frame = bg.crop((cx, cy, cx + W, cy + H)).convert("RGBA")
        cap = caption_chunks(slides[0]["say"], 1)[0][0]
        frame.alpha_composite(draw_frame(theme, tag, brand, slides[0]["screen"], cap, 0, len(slides), 0.2))
        frame.convert("RGB").save(args.still)
        print(f"Done: {args.still}")
        return

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not installed")
    import soundfile as sf

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
        bg_path = os.path.join(work, "bg.png")
        background(theme, pattern, seed).save(bg_path)
        concat_lines, t = [], 0.0
        n = 0
        for i, (s, (_, dur, _, _)) in enumerate(zip(slides, audios)):
            chunks = caption_chunks(s["say"], dur) + [("", GAP)]
            for cap, cdur in chunks:
                t += cdur
                img = draw_frame(theme, tag, brand, s["screen"], cap, i, len(slides), t / total_dur)
                p = os.path.join(work, f"f{n:04d}.png")
                img.save(p)
                concat_lines += [f"file '{p}'", f"duration {cdur:.3f}"]
                n += 1
        concat_lines.append(f"file '{p}'")  # ffmpeg concat needs the last frame repeated
        lst = os.path.join(work, "frames.txt")
        with open(lst, "w") as f:
            f.write("\n".join(concat_lines))

        print("3) Encoding video...")
        px, py = pan_expr(seed, total_dur)
        filt = (
            f"[0:v]crop={W}:{H}:x='{px}':y='{py}'[bg];"
            f"[1:v]fps={FPS},format=rgba[fg];"
            f"[bg][fg]overlay=0:0:shortest=1,format=yuv420p[v]"
        )
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-loop", "1", "-framerate", str(FPS), "-i", bg_path,
            "-f", "concat", "-safe", "0", "-i", lst,
            "-i", audio_path,
            "-filter_complex", filt,
            "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "160k",
            "-t", f"{total_dur:.3f}", "-shortest", "-movflags", "+faststart",
            args.out,
        ]
        subprocess.run(cmd, check=True)
        print(f"Done: {args.out} ({total_dur:.1f}s, {theme}/{pattern})")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
