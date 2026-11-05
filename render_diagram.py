#!/usr/bin/env python3
"""
render_diagram.py - Turns an animated diagram (one self-contained HTML file) into an MP4
for LinkedIn. Plan v3: Claude writes the HTML, the Raspberry Pi renders it.

How it works: Chromium (through Playwright) opens the page, pauses every CSS / SVG
animation, and takes a screenshot frame by frame, setting each animation to the exact
time of that frame. ffmpeg joins the frames. Because the time is set by hand, the video
is always smooth, even if the Pi is slow.

Usage:
  python3 render_diagram.py linkedin/2026-11-11.html -o out.mp4
  python3 render_diagram.py linkedin/2026-11-11.html --still preview.png --at 9
  python3 render_diagram.py page.html -o out.mp4 --fps 30 --duration 15

Settings come from the HTML (the command line overrides them):
  <meta name="duration" content="15">     seconds
  <meta name="size" content="1080x1350">  width x height in pixels (4:5 by default)

Rules for the HTML:
  - Everything inside the file (no web fonts, no images from the internet).
  - Animate with CSS animations/transitions or SVG <animate> (SMIL). No JavaScript timers:
    they are not paused, so they would not match the frames.

Chromium: uses the one installed by Playwright ("playwright install chromium"). If that
fails (for example on Raspberry Pi OS), it falls back to the system one
(sudo apt install chromium), or to the path given with --chromium.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

SYSTEM_CHROMIUM = ["/usr/bin/chromium", "/usr/bin/chromium-browser"]

SEEK_JS = """
async (t) => {
  const ms = t * 1000;
  for (const a of document.getAnimations()) { a.pause(); a.currentTime = ms; }
  for (const svg of document.querySelectorAll('svg')) {
    if (svg.pauseAnimations) { svg.pauseAnimations(); svg.setCurrentTime(t); }
  }
  // let the browser paint the new state before the screenshot
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
}
"""


def meta(html, name):
    m = re.search(r'<meta\s+name="%s"\s+content="([^"]+)"' % name, html)
    return m.group(1) if m else None


def launch(p, chromium_path):
    paths = [chromium_path] if chromium_path else [None] + SYSTEM_CHROMIUM
    last = None
    for path in paths:
        if path and not os.path.exists(path):
            continue
        try:
            return p.chromium.launch(executable_path=path) if path else p.chromium.launch()
        except Exception as e:  # browser missing or not runnable here
            last = e
    sys.exit(f"Could not start Chromium. Run 'playwright install chromium' or "
             f"'sudo apt install chromium'.\nLast error: {last}")


def main():
    ap = argparse.ArgumentParser(description="Animated HTML diagram -> MP4")
    ap.add_argument("html")
    ap.add_argument("-o", "--output", help="MP4 file to write")
    ap.add_argument("--still", help="write a single PNG instead of a video")
    ap.add_argument("--at", type=float, default=None, help="second for --still (default: last)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--size", default=None, help="WIDTHxHEIGHT, e.g. 1080x1350")
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--chromium", default=None, help="path to a Chromium binary")
    args = ap.parse_args()

    if not args.output and not args.still:
        sys.exit("Give -o out.mp4 or --still out.png")
    if args.output and not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is not installed")

    path = os.path.abspath(args.html)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    duration = args.duration or float(meta(html, "duration") or 12)
    w, h = (int(x) for x in (args.size or meta(html, "size") or "1080x1350").split("x"))
    frames = int(round(duration * args.fps))

    with sync_playwright() as p:
        browser = launch(p, args.chromium)
        page = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        page.goto("file://" + path)
        page.evaluate("document.fonts.ready")
        page.evaluate(SEEK_JS, 0)

        if args.still:
            t = duration - 1 / args.fps if args.at is None else args.at
            page.evaluate(SEEK_JS, t)
            page.screenshot(path=args.still)
            print(f"Still at {t:.2f}s -> {args.still}")
            browser.close()
            return

        out = os.path.abspath(args.output)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        ff = subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "image2pipe", "-framerate", str(args.fps), "-c:v", "png", "-i", "-",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", str(args.crf),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
            stdin=subprocess.PIPE)
        start = time.time()
        try:
            for i in range(frames):
                page.evaluate(SEEK_JS, i / args.fps)
                ff.stdin.write(page.screenshot(type="png"))
                if i % (args.fps * 3) == 0:
                    print(f"  frame {i}/{frames}", flush=True)
        finally:
            ff.stdin.close()
            code = ff.wait()
            browser.close()
        if code != 0:
            sys.exit(f"ffmpeg failed (exit {code})")
        mb = os.path.getsize(out) / 1e6
        print(f"Done: {out} ({frames} frames, {duration:.1f}s, {w}x{h}, {mb:.1f} MB, "
              f"{time.time() - start:.0f}s to render)")


if __name__ == "__main__":
    main()
