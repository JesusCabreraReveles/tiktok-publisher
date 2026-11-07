#!/usr/bin/env python3
"""
publish_daily.py - Daily TikTok pipeline for the Raspberry Pi.

  1. git pull                       (Claude leaves guiones/YYYY-MM-DD.json, and on Wednesdays
                                     also guiones/YYYY-MM-DD-book.json, in the repo)
  2. make_video.py                  -> docs/videos/<script>-<hash>.mp4  (one per script)
  3. git commit + push              (GitHub Pages gives each video a public URL)
  4. wait until the URLs are live
  5. POST to the Make webhook       -> Make creates a draft in SocialBee for each video

LinkedIn (plan v3): Claude also leaves linkedin/YYYY-MM-DD[-name].html (animated diagram)
plus linkedin/YYYY-MM-DD[-name].txt (the post). Each pair becomes
docs/videos/li-<name>-<hash>.mp4 (render_diagram.py) and goes to Make with the post text:
to "make_webhook_linkedin_url" if set, otherwise to the same "make_webhook_url" as TikTok
(that scenario already creates the draft on the LinkedIn profile). A LinkedIn problem never stops the
TikTok videos: that post is held, the others go out, and the run ends with an error.

Usage:
  python3 publish_daily.py                 # today's scripts
  python3 publish_daily.py --date 2026-10-21
  python3 publish_daily.py --dry-run       # generate videos only (no push, no Make)
  python3 publish_daily.py --force         # regenerate videos even if they exist
  python3 publish_daily.py --resend        # send to Make again even if already sent
  python3 publish_daily.py --allow-missing-cover   # publish a book video even without its cover

Raspberry Pi power: videos are rendered on 2 cores with low priority ("render_cores" in
config.json, default 2; 0 = all cores). Rendering on all 4 cores made the Pi reboot from
undervoltage during "Encoding video".

GitHub Pages: if a video is not live after 8 minutes (a deploy stuck "Queued" happens), an
empty commit is pushed to start a new Pages deploy, and it waits 10 more minutes. A cron
retry does the same, so a stuck deploy no longer blocks the drafts.

Safe to re-run (cron can run it twice as a retry):
  - the video name includes a hash of its script, so an edited script makes a new video;
  - an existing video is reused; nothing is committed twice;
  - a script already sent to Make is skipped (marker in logs/sent/).

Resource check: a script that asks for a "cover" (book videos) is NOT published if the
image is missing from the repo. The other videos of the day still go out, the run ends
with an error, and the 10:15 retry picks it up once the cover is uploaded.

Needs in config.json:
  "make_webhook_url": "https://hook.us1.make.com/...",
  "pages_base_url":   "https://jesuscabrerareveles.github.io/tiktok-publisher/"
Optional:
  "tiktok_privacy":   "PUBLIC_TO_EVERYONE"   (sent to Make as "privacy")
  "make_webhook_linkedin_url": "https://hook.us1.make.com/..."   (LinkedIn videos; default:
                                the TikTok webhook)
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import os
import re
import shutil
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


def run(cmd, env=None):
    log("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=HERE, check=True, env=env)


def render(cmd, cfg):
    """Run a render (make_video / render_diagram) on few cores and low priority, so the Pi
    draws less current (it rebooted from undervoltage when all 4 cores encoded)."""
    cores = int(cfg.get("render_cores", 2) or 0)
    env = dict(os.environ)
    if cores > 0:
        env["OMP_NUM_THREADS"] = str(cores)
        prefix = ["nice", "-n", "10"] if shutil.which("nice") else []
        if shutil.which("taskset"):
            prefix += ["taskset", "-c", ",".join(str(i) for i in range(cores))]
        cmd = prefix + cmd
    run(cmd, env=env)


def redeploy_pages(date):
    """Start a new GitHub Pages deploy with an empty commit (a deploy sometimes stays
    "Queued" for hours; a newer one goes through)."""
    log("Pages looks stuck: pushing an empty commit to start a new deploy.")
    run(["git", "pull", "--rebase", "--quiet"])
    run(["git", "commit", "--allow-empty", "--quiet", "-m", f"Re-deploy Pages ({date})"])
    run(["git", "push", "--quiet"])


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
        except (urllib.error.URLError, OSError) as e:
            # URLError = 404/DNS; OSError covers TimeoutError and dropped connections,
            # which happen when GitHub Pages is slow. Keep waiting instead of crashing.
            log(f"  ({type(e).__name__}: {e})")
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


def find_linkedin(date):
    pats = [os.path.join(HERE, "linkedin", f"{date}.html"),
            os.path.join(HERE, "linkedin", f"{date}-*.html")]
    found = []
    for p in pats:
        found += sorted(glob.glob(p))
    return found


def missing_images(html):
    """Local images (e.g. ../portadas/X.jpg) that the diagram uses but are not in the repo."""
    base = os.path.join(HERE, "linkedin")
    out = []
    for src in re.findall(r'(?:src|href)="([^"#:]+\.(?:jpg|jpeg|png|webp|svg))"', html):
        if not os.path.isfile(os.path.normpath(os.path.join(base, src))):
            out.append(src)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.date.today().isoformat())
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="regenerate videos even if they exist")
    ap.add_argument("--resend", action="store_true", help="send to Make even if already sent")
    ap.add_argument("--allow-missing-cover", action="store_true",
                    help="publish book videos even if their cover image is missing")
    args = ap.parse_args()

    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    base = cfg.get("pages_base_url", "").rstrip("/") + "/"
    hook = cfg.get("make_webhook_url", "")
    li_hook = cfg.get("make_webhook_linkedin_url") or hook
    if not args.dry_run and (not hook or not base.startswith("http")):
        sys.exit("config.json needs make_webhook_url and pages_base_url")

    run(["git", "pull", "--ff-only", "--quiet"])

    scripts = find_scripts(args.date)
    posts = find_linkedin(args.date)
    if not scripts and not posts:
        sys.exit(f"No scripts for {args.date} in guiones/ or linkedin/. Nothing to do.")

    jobs = []
    held = []
    for script in scripts:
        with open(script, "rb") as f:
            raw = f.read()
        sc = json.loads(raw)
        stem = os.path.splitext(os.path.basename(script))[0]
        cover = sc.get("cover")
        if cover and not os.path.isfile(os.path.join(HERE, cover)):
            if args.allow_missing_cover:
                log(f"WARNING: cover missing ({cover}), publishing {stem} without it as requested.")
            else:
                log(f"ERROR: {stem} needs {cover}, which is not in the repo. Not publishing this "
                    f"video. Upload the cover (or run with --allow-missing-cover).")
                held.append(stem)
                continue
        name = f"{stem}-{hashlib.sha1(raw).hexdigest()[:8]}"
        rel_video = f"docs/videos/{name}.mp4"
        video = os.path.join(HERE, rel_video)
        os.makedirs(os.path.dirname(video), exist_ok=True)
        if os.path.exists(video) and not args.force:
            log(f"Video already exists, reusing it: {rel_video}")
        else:
            render([PY, "make_video.py", script, "-o", video], cfg)
        jobs.append({"kind": "tiktok", "script": script, "sc": sc, "name": name,
                     "rel_video": rel_video})

    # LinkedIn: animated diagram + post text. Any problem holds only that post.
    for html_path in posts:
        stem = os.path.splitext(os.path.basename(html_path))[0]
        txt_path = os.path.splitext(html_path)[0] + ".txt"
        if not os.path.isfile(txt_path):
            log(f"ERROR: linkedin/{stem}.html has no linkedin/{stem}.txt (the post text). Held.")
            held.append(f"linkedin/{stem}")
            continue
        if not li_hook and not args.dry_run:
            log(f"ERROR: config.json has no Make webhook. linkedin/{stem} held.")
            held.append(f"linkedin/{stem}")
            continue
        with open(html_path, "rb") as f:
            raw_html = f.read()
        with open(txt_path, "rb") as f:
            raw_txt = f.read()
        lost = missing_images(raw_html.decode("utf-8", errors="replace"))
        if lost and not args.allow_missing_cover:
            log(f"ERROR: linkedin/{stem} uses images that are not in the repo: {', '.join(lost)}. "
                f"Held (upload them, or run with --allow-missing-cover).")
            held.append(f"linkedin/{stem}")
            continue
        text = raw_txt.decode("utf-8").strip()
        if not text:
            log(f"ERROR: linkedin/{stem}.txt is empty. Held.")
            held.append(f"linkedin/{stem}")
            continue
        name = f"li-{stem}-{hashlib.sha1(raw_html + raw_txt).hexdigest()[:8]}"
        rel_video = f"docs/videos/{name}.mp4"
        video = os.path.join(HERE, rel_video)
        os.makedirs(os.path.dirname(video), exist_ok=True)
        if os.path.exists(video) and not args.force:
            log(f"Video already exists, reusing it: {rel_video}")
        else:
            try:
                render([PY, "render_diagram.py", html_path, "-o", video], cfg)
            except subprocess.CalledProcessError as e:
                log(f"ERROR rendering linkedin/{stem}: {e}. Held.")
                if os.path.exists(video):
                    os.remove(video)
                held.append(f"linkedin/{stem}")
                continue
        jobs.append({"kind": "linkedin", "text": text, "name": name, "rel_video": rel_video})

    if not jobs:
        sys.exit(f"No videos published for {args.date}; held: {', '.join(held)}")

    if args.dry_run:
        for j in jobs:
            text = j["text"] if j["kind"] == "linkedin" else build_caption(j["sc"])
            log(f"Dry run ({j['kind']}): {j['rel_video']}\nCaption:\n{text}")
        if held:
            log(f"HELD: {', '.join(held)}")
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
    redeployed = False
    for j in jobs:
        marker = os.path.join(SENT_DIR, j["name"])
        if os.path.exists(marker) and not args.resend:
            log(f"Already sent to Make, skipping (use --resend to force): {j['name']}")
            continue
        url = base + j["rel_video"][len("docs/"):]
        log(f"Waiting for {url}")
        live = wait_live(url, minutes=3 if redeployed else 8)
        if not live and not redeployed:
            redeploy_pages(args.date)
            redeployed = True
            live = wait_live(url, minutes=10)
        if not live:
            log("ERROR: the video never went live on GitHub Pages. Check the Pages build.")
            failures += 1
            continue
        if j["kind"] == "linkedin":
            target = li_hook
            payload = {
                "date": args.date,
                "caption": j["text"][:3000],   # LinkedIn's post limit
                "video_url": url,
                "lang": "en",
                "platform": "linkedin",
            }
        else:
            target = hook
            payload = {
                "date": args.date,
                "caption": build_caption(j["sc"]),
                "video_url": url,
                "lang": j["sc"].get("lang", "en"),
                # SocialBee requires a TikTok privacy mode; kept for when its Make module supports it.
                "privacy": cfg.get("tiktok_privacy", "PUBLIC_TO_EVERYONE"),
            }
        req = urllib.request.Request(
            target, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                log(f"Make answered HTTP {r.status}: {r.read().decode(errors='replace')[:200]}")
            with open(marker, "w") as f:
                f.write(dt.datetime.now().isoformat())
        except (urllib.error.URLError, OSError) as e:
            log(f"ERROR sending to Make: {type(e).__name__}: {e}")
            failures += 1

    if held:
        log(f"HELD (see the errors above): {', '.join(held)}")
    if failures or held:
        sys.exit(f"{failures} video(s) failed, {len(held)} held. "
                 "Re-run later; sent ones are skipped.")
    log("Done. The drafts should appear in SocialBee in a moment "
        "(LinkedIn posts are the ones in English: publish them as they are).")


if __name__ == "__main__":
    main()
