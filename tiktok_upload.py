#!/usr/bin/env python3
"""
tiktok_upload.py - Sends a video to your TikTok account using TikTok's official
Content Posting API. Only uses the Python standard library.

Two modes:
  direct (default)  Publishes with caption + hashtags taken from the script JSON.
                    Tries PUBLIC first; if TikTok refuses (app not audited yet),
                    publishes as PRIVATE automatically. Scope: video.publish
  --inbox           The video lands in your TikTok app as a notification/draft;
                    you add the caption yourself. Scope: video.upload

One-time setup:
  1. Create an app at https://developers.tiktok.com (see LEEME.md).
  2. Fill config.json (client_key, client_secret, redirect_uri).
  3. python3 tiktok_upload.py auth        -> log in once; saves tokens.json

Daily use:
  python3 tiktok_upload.py upload video.mp4 --script guion.json
  python3 tiktok_upload.py upload video.mp4 --caption "text" --hashtags "#ai #tech"
  python3 tiktok_upload.py upload video.mp4 --inbox
"""
import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "config.json")
TOKENS = os.path.join(HERE, "tokens.json")

API = "https://open.tiktokapis.com"
AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
SCOPES = "user.info.basic,video.upload,video.publish"

MAX_SINGLE_CHUNK = 64 * 1024 * 1024
CHUNK = 10 * 1024 * 1024


# ---------- helpers ----------
def load(path):
    if not os.path.exists(path):
        sys.exit(f"Missing {os.path.basename(path)}. See LEEME.md.")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_tokens(data):
    data["obtained_at"] = int(time.time())
    with open(TOKENS, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.chmod(TOKENS, 0o600)


def http(method, url, data=None, headers=None, raw=None):
    headers = dict(headers or {})
    body = raw
    if data is not None:
        if headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            body = urllib.parse.urlencode(data).encode()
        else:
            headers.setdefault("Content-Type", "application/json; charset=UTF-8")
            body = json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = r.read().decode() or "{}"
            return r.status, json.loads(txt) if txt.strip().startswith("{") else {}
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(txt)
        except ValueError:
            return e.code, {"raw": txt}


def check(status, resp, what):
    err = (resp.get("error") or {})
    if status >= 300 or (err.get("code") not in (None, "", "ok")):
        sys.exit(f"{what} failed (HTTP {status}): {json.dumps(resp, ensure_ascii=False)}")
    return resp


# ---------- auth ----------
def cmd_auth(_args):
    cfg = load(CONFIG)
    state = secrets.token_urlsafe(16)
    q = {
        "client_key": cfg["client_key"],
        "scope": cfg.get("scopes", SCOPES),
        "response_type": "code",
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
    }
    print("\n1) Open this link in a browser where you are logged into TikTok and accept:\n")
    print(AUTH_URL + "?" + urllib.parse.urlencode(q))
    print("\n2) TikTok will redirect you to your redirect_uri. Copy the FULL address")
    print("   from the browser bar (it contains ?code=...) and paste it here.\n")
    pasted = input("Address: ").strip()
    params = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
    if params.get("state", [""])[0] != state:
        sys.exit("The 'state' does not match. Start again with: python3 tiktok_upload.py auth")
    if "code" not in params:
        sys.exit(f"No code in the address. TikTok said: {params}")
    status, resp = http(
        "POST", f"{API}/v2/oauth/token/",
        data={
            "client_key": cfg["client_key"],
            "client_secret": cfg["client_secret"],
            "code": params["code"][0],
            "grant_type": "authorization_code",
            "redirect_uri": cfg["redirect_uri"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if "access_token" not in resp:
        sys.exit(f"Token exchange failed (HTTP {status}): {resp}")
    save_tokens(resp)
    print(f"\nOK. Tokens saved in tokens.json. Scopes granted: {resp.get('scope')}")


def access_token():
    cfg = load(CONFIG)
    tok = load(TOKENS)
    age = time.time() - tok.get("obtained_at", 0)
    if age < tok.get("expires_in", 0) - 300:
        return tok["access_token"]
    status, resp = http(
        "POST", f"{API}/v2/oauth/token/",
        data={
            "client_key": cfg["client_key"],
            "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token",
            "refresh_token": tok["refresh_token"],
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if "access_token" not in resp:
        sys.exit(f"Could not refresh the token (HTTP {status}): {resp}\n"
                 "Run again: python3 tiktok_upload.py auth")
    save_tokens(resp)
    return resp["access_token"]


# ---------- upload ----------
def chunk_plan(size):
    if size <= MAX_SINGLE_CHUNK:
        return size, 1
    # TikTok rule: count = floor(size / chunk); the last chunk carries the remainder
    return CHUNK, size // CHUNK


def put_chunks(upload_url, path, size, chunk_size, count):
    with open(path, "rb") as f:
        for i in range(count):
            start = i * chunk_size
            end = size - 1 if i == count - 1 else start + chunk_size - 1
            f.seek(start)
            data = f.read(end - start + 1)
            status, resp = http("PUT", upload_url, raw=data, headers={
                "Content-Type": "video/mp4",
                "Content-Length": str(len(data)),
                "Content-Range": f"bytes {start}-{end}/{size}",
            })
            if status not in (200, 201, 206):
                sys.exit(f"Chunk {i + 1}/{count} upload failed (HTTP {status}): {resp}")
            print(f"  sent chunk {i + 1}/{count}")


def wait_status(token, publish_id):
    hdr = {"Authorization": f"Bearer {token}"}
    for _ in range(40):
        status, resp = http("POST", f"{API}/v2/post/publish/status/fetch/",
                            data={"publish_id": publish_id}, headers=hdr)
        check(status, resp, "Status check")
        st = resp.get("data", {}).get("status")
        print(f"  status: {st}")
        if st in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return st
        if st == "FAILED":
            sys.exit(f"TikTok rejected the video: {resp['data'].get('fail_reason')}")
        time.sleep(6)
    print("  Still processing; check the TikTok app in a few minutes.")
    return None


def cmd_upload(args):
    path = args.video
    if not os.path.exists(path):
        sys.exit(f"Video not found: {path}")
    size = os.path.getsize(path)
    chunk_size, count = chunk_plan(size)
    source = {"source": "FILE_UPLOAD", "video_size": size,
              "chunk_size": chunk_size, "total_chunk_count": count}

    token = access_token()
    hdr = {"Authorization": f"Bearer {token}"}

    if args.inbox:
        print("Sending to your TikTok inbox...")
        status, resp = http("POST", f"{API}/v2/post/publish/inbox/video/init/",
                            data={"source_info": source}, headers=hdr)
        check(status, resp, "Upload init")
        privacy = None
    else:
        caption = build_caption(args)
        print(f"Caption ({len(caption)} chars):\n  {caption}\n")
        status, info = http("POST", f"{API}/v2/post/publish/creator_info/query/", data={}, headers=hdr)
        check(status, info, "Creator info")
        options = info.get("data", {}).get("privacy_level_options", []) or ["SELF_ONLY"]

        # Try public first (if asked and offered); fall back to private if TikTok refuses.
        order = []
        if args.privacy == "public" and "PUBLIC_TO_EVERYONE" in options:
            order.append("PUBLIC_TO_EVERYONE")
        order.append("SELF_ONLY" if "SELF_ONLY" in options else options[-1])

        resp = None
        for privacy in order:
            print(f"Direct post, privacy {privacy}...")
            body = {
                "post_info": {
                    "title": caption,
                    "privacy_level": privacy,
                    "disable_comment": False,
                    "disable_duet": False,
                    "disable_stitch": False,
                    "is_aigc": True,  # AI voice -> TikTok asks to label AI-generated content
                },
                "source_info": source,
            }
            status, resp = http("POST", f"{API}/v2/post/publish/video/init/", data=body, headers=hdr)
            err = resp.get("error") or {}
            if status < 300 and err.get("code") in (None, "", "ok"):
                break
            print(f"  TikTok refused {privacy}: {err.get('code')} - {err.get('message')}")
            if privacy == order[-1]:
                check(status, resp, "Upload init")

    publish_id = resp["data"]["publish_id"]
    put_chunks(resp["data"]["upload_url"], path, size, chunk_size, count)
    st = wait_status(token, publish_id)

    if st == "SEND_TO_USER_INBOX":
        print("\nDone. Open TikTok: you'll see a notification to finish the post.")
    elif st == "PUBLISH_COMPLETE":
        vis = "PUBLIC" if privacy == "PUBLIC_TO_EVERYONE" else "PRIVATE (only you)"
        print(f"\nDone. Published as {vis}.")


def clean_tag(t):
    t = "".join(ch for ch in t.strip().lstrip("#") if ch.isalnum() or ch == "_")
    return f"#{t}" if t else ""


def build_caption(args):
    text, tags = args.caption or "", []
    if args.script:
        with open(args.script, encoding="utf-8") as f:
            sc = json.load(f)
        text = text or sc.get("caption", "")
        tags = sc.get("hashtags", [])
    if args.hashtags:
        tags += args.hashtags.replace(",", " ").split()
    seen, out = set(), []
    for t in tags:
        c = clean_tag(t)
        if c and c.lower() not in seen and c.lower() not in text.lower():
            seen.add(c.lower())
            out.append(c)
    caption = (text.strip() + ("\n\n" if text.strip() and out else "") + " ".join(out)).strip()
    return caption[:2200]  # TikTok caption limit


def main():
    ap = argparse.ArgumentParser(description="Upload a video to TikTok")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth", help="log in once and save tokens")
    up = sub.add_parser("upload", help="upload a video (direct post by default)")
    up.add_argument("video")
    up.add_argument("--script", help="script JSON; uses its 'caption' and 'hashtags'")
    up.add_argument("--caption", default="", help="caption text (overrides the script's)")
    up.add_argument("--hashtags", default="", help='extra hashtags, e.g. "#ai #leadership"')
    up.add_argument("--privacy", choices=["public", "private"], default="public",
                    help="try public first (falls back to private if TikTok refuses)")
    up.add_argument("--inbox", action="store_true", help="send to TikTok inbox instead (no caption)")
    args = ap.parse_args()
    {"auth": cmd_auth, "upload": cmd_upload}[args.cmd](args)


if __name__ == "__main__":
    main()
