#!/usr/bin/env python3
"""
publish_daily.py - Daily TikTok pipeline for the Raspberry Pi.

  1. git pull                       (Claude leaves guiones/YYYY-MM-DD.json, and on Wednesdays
                                     also guiones/YYYY-MM-DD-book.json, in the repo)
  2. make_video.py                  -> docs/videos/<script>-<hash>.mp4  (one per script)
  3. git commit + push              (GitHub Pages gives each video a public URL)
  4. wait until the URLs are live
  5. POST to the Make webhook       -> Make creates a draft in SocialBee for each video

Usage:
  python3 publish_daily.py                 # today's scripts
  python3 publish_daily.py --date 2026-10-21
  python3 publish_daily.py --dry-run       # generate videos only (no push, no Make)
  python3 publish_daily.py --force         # regenerate videos even if they exist
  python3 publish_daily.py --resend        # send to Make again even if already sent

Safe to re-run (cron can run it twice as a retry):
  - the video name includes a hash of its script, so an edited script makes a new video;
  - an existing video is reused; nothing is committed twice;
  - a script already sent to Make is skipped (marker in logs/sent/).

Needs in config.json:
  "make_webhook_url": "https://hook.us1.make.com/...",
  "pages_base_url":   "https://jesuscabrerareveles.github.io/tiktok-publisher/"
Optional:
  "tiktok_privacy":   "PUBLIC_TO_EVERYONE"   (sent to Make as "privacy")
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
SENT_DIR = os.path.join(HERE, "logs", "sent")
PY = sys.executable


def log(msg):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}", flush=True)


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


def find_scripts(date):
    pats = [os.path.join(HERE, "guiones", f"{date}.json"),
            os.path.join(HERE, "guiones", f"{date}-*.json")]
    found = []
    for p in pats:
        found += sorted(glob.glob(p))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="regenerate videos even if they exist")
    ap.add_argument("--resend", action="store_true", help="send to Make even if already sent")
    args = ap.parse_args()

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    base = cfg.get("pages_base_url", "").rstrip("/") + "/"
    hook = cfg.get("make_webhook_url", "")
    if not args.dry_run and (not hook or not base.startswith("http")):
        sys.exit("config.json needs make_webhook_url and pages_base_url")

    run(["git", "pull", "--ff-only", "--quiet"])

    scripts = find_scripts(args.date)
    if not scripts:
        sys.exit(f"No scripts for {args.date} in guiones/. Nothing to do.")

    jobs = []
    for script in scripts:
        with open(script, "rb") as f:
            raw = f.read()
        sc = json.loads(raw)
        stem = os.path.splitext(os.path.basename(script))[0]
        name = f"{stem}-{hashlib.sha1(raw).hexdigest()[:8]}"
        rel_video = f"docs/videos/{name}.mp4"
        video = os.path.join(HERE, rel_video)
        os.makedirs(os.path.dirname(video), exist_ok=True)
        if os.path.exists(video) and not args.force:
            log(f"Video already exists, reusing it: {rel_video}")
        else:
            run([PY, "make_video.py", script, "-o", video])
        jobs.append({"script": script, "sc": sc, "name": name, "rel_video": rel_video})

    if args.dry_run:
        for j in jobs:
            log(f"Dry run: {j['rel_video']}\nCaption:\n{build_caption(j['sc'])}")
        return

    run(["git", "add"] + [j["rel_video"] for j in jobs])
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=HERE).returncode != 0
    if staged:
        run(["git", "commit", "--quiet", "-m", f"Videos {args.date}"])
    else:
        log("Nothing new to commit (videos already committed).")
    run(["git", "push", "--quiet"])

    os.makedirs(SENT_DIR, exist_ok=True)
    failures = 0
    for j in jobs:
        marker = os.path.join(SENT_DIR, j["name"])
        if os.path.exists(marker) and not args.resend:
            log(f"Already sent to Make, skipping (use --resend to force): {j['name']}")
            continue
        url = base + j["rel_video"][len("docs/"):]
        log(f"Waiting for {url}")
        if not wait_live(url):
            log("ERROR: the video never went live on GitHub Pages. Check the Pages build.")
            failures += 1
            continue
        payload = {
            "date": args.date,
            "caption": build_caption(j["sc"]),
            "video_url": url,
            "lang": j["sc"].get("lang", "en"),
            # SocialBee requires a TikTok privacy mode; kept for when its Make module supports it.
            "privacy": cfg.get("tiktok_privacy", "PUBLIC_TO_EVERYONE"),
        }
        req = urllib.request.Request(
            hook, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                log(f"Make answered HTTP {r.status}: {r.read().decode(errors='replace')[:200]}")
            with open(marker, "w") as f:
                f.write(dt.datetime.now().isoformat())
        except urllib.error.URLError as e:
            log(f"ERROR sending to Make: {e}")
            failures += 1

    if failures:
        sys.exit(f"{failures} video(s) failed. Re-run later; sent ones are skipped.")
    log("Done. The drafts should appear in SocialBee (category TikTok IA) in a moment.")


if __name__ == "__main__":
    main()
