#!/usr/bin/env python3
"""
publish_daily.py - Daily TikTok pipeline for the Raspberry Pi.

  1. git pull                       (Claude leaves guiones/YYYY-MM-DD.json in the repo)
  2. make_video.py                  -> docs/videos/YYYY-MM-DD.mp4
  3. git commit + push              (GitHub Pages gives the video a public URL)
  4. wait until the URL is live
  5. POST to the Make webhook       -> Make creates a TikTok draft in SocialBee

Usage:
  python3 publish_daily.py                 # today's script
  python3 publish_daily.py --date 2026-10-21
  python3 publish_daily.py --dry-run       # everything except git push and Make

Needs in config.json:
  "make_webhook_url": "https://hook.us1.make.com/...",
  "pages_base_url":   "https://jesuscabrerareveles.github.io/tiktok-publisher/"
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
PY = sys.executable


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def run(cmd):
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=HERE, check=True)


def build_caption(sc):
    text = (sc.get("caption") or "").strip()
    seen, tags = set(), []
    for t in sc.get("hashtags", []):
        t = "".join(ch for ch in t.strip().lstrip("#") if ch.isalnum() or ch == "_")
        if t and t.lower() not in seen:
            seen.add(t.lower())
            tags.append("#" + t)
    return (text + ("\n\n" if text and tags else "") + " ".join(tags)).strip()[:2200]


def wait_live(url, minutes=15):
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return True
        except urllib.error.URLError:
            pass
        log("  video not live yet, waiting 30 s...")
        time.sleep(30)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    base = cfg.get("pages_base_url", "").rstrip("/") + "/"
    hook = cfg.get("make_webhook_url", "")
    if not args.dry_run and (not hook or not base.startswith("http")):
        sys.exit("config.json needs make_webhook_url and pages_base_url")

    run(["git", "pull", "--ff-only", "--quiet"])

    script = os.path.join(HERE, "guiones", f"{args.date}.json")
    if not os.path.exists(script):
        sys.exit(f"No script for {args.date} ({script}). Nothing to do.")
    with open(script, encoding="utf-8") as f:
        sc = json.load(f)

    rel_video = f"docs/videos/{args.date}.mp4"
    video = os.path.join(HERE, rel_video)
    os.makedirs(os.path.dirname(video), exist_ok=True)
    run([PY, "make_video.py", script, "-o", video])

    if args.dry_run:
        log(f"Dry run done. Video: {video}")
        log("Caption:\n" + build_caption(sc))
        return

    run(["git", "add", rel_video])
    run(["git", "commit", "--quiet", "-m", f"Video {args.date}"])
    run(["git", "push", "--quiet"])

    url = base + f"videos/{args.date}.mp4"
    log(f"Waiting for {url}")
    if not wait_live(url):
        sys.exit("The video never went live on GitHub Pages. Check the Pages build.")

    payload = {
        "date": args.date,
        "caption": build_caption(sc),
        "video_url": url,
        "lang": sc.get("lang", "en"),
    }
    req = urllib.request.Request(
        hook, data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        log(f"Make answered HTTP {r.status}: {r.read().decode(errors='replace')[:200]}")
    log("Done. The draft should appear in SocialBee in a moment.")


if __name__ == "__main__":
    main()
