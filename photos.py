#!/usr/bin/env python3
"""
photos.py - Finds a background photo on Pixabay for a slide (v1.2).

    from photos import get_photo
    path = get_photo("server room")   # local .jpg path, or None

Rules of the Pixabay API that this follows:
  - search responses are cached for 24 hours (cache/pixabay/);
  - images are downloaded and used from disk, never hotlinked;
  - only a handful of requests per video (limit: 100 per minute).
The videos show a small "Fotos: Pixabay" credit.

The key comes from config.json ("pixabay_api_key") or the PIXABAY_API_KEY environment
variable. Without a key, or if anything fails (no internet, no results, rate limit), it
returns None and the video is made with the normal background: a photo is never required.

Quick test:  python3 photos.py "server room"
"""
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache", "pixabay")
API = "https://pixabay.com/api/"
DAY = 24 * 3600
UA = {"User-Agent": "tiktok-publisher/1.2 (+https://github.com/JesusCabreraReveles/tiktok-publisher)"}


def _key():
    k = os.environ.get("PIXABAY_API_KEY")
    if k:
        return k.strip()
    try:
        with open(os.path.join(HERE, "config.json"), encoding="utf-8") as f:
            return (json.load(f).get("pixabay_api_key") or "").strip()
    except (OSError, ValueError):
        return ""


def _search(query, key):
    """Search results for `query`, from the 24 h cache when possible."""
    os.makedirs(CACHE, exist_ok=True)
    cpath = os.path.join(CACHE, "q-" + hashlib.sha1(query.lower().encode()).hexdigest()[:16] + ".json")
    if os.path.exists(cpath) and time.time() - os.path.getmtime(cpath) < DAY:
        with open(cpath, encoding="utf-8") as f:
            return json.load(f)
    params = {"key": key, "q": query[:100], "image_type": "photo", "orientation": "vertical",
              "safesearch": "true", "per_page": 20, "order": "popular", "lang": "en"}
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    hits = [{"id": h["id"], "url": h.get("largeImageURL") or h.get("webformatURL"),
             "w": h.get("imageWidth", 0), "h": h.get("imageHeight", 0)}
            for h in data.get("hits", []) if h.get("largeImageURL") or h.get("webformatURL")]
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(hits, f)
    return hits


def get_photo(query, seed=0):
    """Local path of a photo for `query`, or None. `seed` picks among the top results so
    two slides with similar queries don't get the same picture."""
    query = (query or "").strip()
    key = _key()
    if not query or not key:
        return None
    try:
        hits = _search(query, key)
        if not hits and " " in query:                      # retry with fewer words
            hits = _search(" ".join(query.split()[:2]), key)
        if not hits:
            print(f"  photo: no results for '{query}', using the normal background")
            return None
        hit = hits[seed % min(len(hits), 5)]
        path = os.path.join(CACHE, f"img-{hit['id']}.jpg")
        if not os.path.exists(path):
            req = urllib.request.Request(hit["url"], headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r, open(path + ".part", "wb") as f:
                f.write(r.read())
            os.replace(path + ".part", path)
        print(f"  photo: '{query}' -> pixabay #{hit['id']}")
        return path
    except Exception as e:   # never break a video because of a photo
        print(f"  photo: could not get '{query}' ({type(e).__name__}: {e}), using the normal background")
        return None


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "server room"
    print(get_photo(q) or "no photo (check the key in config.json)")
