#!/usr/bin/env python3
"""
avatar.py - "el panda", the talking cartoon panda (Jesús) for the TikTok videos.

Each pose is a 1254x1254 PNG in avatar/ (navy background). Everything about a pose
(nose, mouth line, eyes) is measured automatically from the picture, so a new pose only
needs a new file named panda_<pose>.png. The nose is found by matching the nose of
panda_piensa.png; a pose without a recognizable nose (e.g. eyes shut, open mouth) is used
as a still picture: no talking, no blinking.

Mouth: the panda's own smile stays as the upper lip; when he talks a jaw opening appears
under it (4 sizes + a rounded "o"), driven by the voice loudness and brightness.
Blink: the eye is painted over with the colour around it and a closed-eye line is drawn.
All poses are aligned by the nose, so the head never jumps when the pose changes.

  python3 avatar.py --sheet hoja.png      # every pose: closed, open, "o", blink

make_video.py uses it (see "El panda" there). Needs numpy, pillow and scipy.
"""
import argparse
import glob
import math
import os
import random
import wave

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from scipy import ndimage
from scipy.signal import fftconvolve

HERE = os.path.dirname(os.path.abspath(__file__))
AVATAR_DIR = os.path.join(HERE, "avatar")
FPS = 30
INK = (14, 12, 16)
MOUTH_IN = (74, 24, 38)
TONGUE = (236, 120, 132)
PREFIX = "panda"
REF_POSE = "piensa"            # its nose is the template, and every pose is moved so its nose lands here
NOSE_BOX = (730, 520, 830, 600)  # nose of the reference pose (x1, y1, x2, y2)
REF_NOSE = (780, 560)
NOSE_MIN_SCORE = 0.8           # below this the pose has no usable face: shown as a still
STILL_POSES = {"lengua"}       # recognizable face, but talking would look wrong
LEVELS = [0, 10, 20, 30]
FADE_PX = 130                  # bottom of the torso fades out over this many pixels

# poses picked on their own for each part of a video: only neutral ones, so the panda never
# disagrees with what is being said. The rest (sarcasmo, duda, preocupado, aprobado, rechazo,
# cansado, lengua, panico, fastidio, tierno) appear only when the script asks for them:
# "panda": "<pose>".
ROLE_POSES = {
    "hook": ["piensa", "sorpresa", "saluda"],
    "middle": ["explica", "idea", "lentes", "senala"],
    "close": ["pulgar", "excelente"],
}
NUMBER_POSES = {1: "uno", 2: "dos", 3: "tres"}   # slides whose headline starts with "1." etc.


# ---------------------------------------------------------------- calibration
_TEMPLATE = None


def _nose_template():
    global _TEMPLATE
    if _TEMPLATE is None:
        g = np.asarray(Image.open(os.path.join(AVATAR_DIR, f"{PREFIX}_{REF_POSE}.png")).convert("L")).astype(float)
        x1, y1, x2, y2 = NOSE_BOX
        t = g[y1:y2, x1:x2]
        t = t - t.mean()
        _TEMPLATE = (t, np.sqrt((t ** 2).sum()))
    return _TEMPLATE


def _nose(img):
    """(x, y, score): centre of the nose, by normalized cross-correlation with the
    reference nose, searched around the middle of the face."""
    t, tn = _nose_template()
    g = np.asarray(img.convert("L")).astype(float)
    x0, y0, x1, y1 = 560, 430, 1000, 700
    S = g[y0:y1, x0:x1]
    num = fftconvolve(S, t[::-1, ::-1], mode="valid")
    ones = np.ones_like(t)
    s1 = fftconvolve(S, ones, mode="valid")
    s2 = fftconvolve(S ** 2, ones, mode="valid")
    ncc = num / (np.sqrt(np.maximum(s2 - s1 ** 2 / t.size, 1e-6)) * tn)
    iy, ix = np.unravel_index(int(np.argmax(ncc)), ncc.shape)
    return x0 + ix + t.shape[1] // 2, y0 + iy + t.shape[0] // 2, float(ncc.max())


def _largest_white(arr, box):
    """Pixels of the eye white in `box`: the biggest white blob plus the other pieces
    around it (a pupil can split the white in two)."""
    x1, y1, x2, y2 = box
    sub = arr[y1:y2, x1:x2]
    white = (sub.min(axis=2) > 228) & ((sub.max(axis=2) - sub.min(axis=2)) < 22)
    lab, n = ndimage.label(white)
    if n == 0:
        return None
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    sizes[sizes > 40000] = 0                     # not an eye: too big
    k = int(np.argmax(sizes)) + 1
    if sizes[k - 1] < 600:
        return None
    sl = ndimage.find_objects(lab)
    ky, kx = sl[k - 1]
    keep = [k]
    for j, (sy, sx) in enumerate(sl, start=1):
        if j == k or sizes[j - 1] < 60:
            continue
        h, w = sy.stop - sy.start, sx.stop - sx.start
        if h < 10:
            continue
        # must sit inside the eye's height (whiskers start lower and run outwards)
        if sx.start >= kx.start - 100 and sx.stop <= kx.stop + 100 and sy.start >= ky.start - 10 and sy.stop <= ky.stop + 10:
            keep.append(j)
    ys, xs = np.nonzero(np.isin(lab, keep))
    return [(int(x) + x1, int(y) + y1) for x, y in zip(xs, ys)]


def _smile(arr, nose):
    """{x: y just under the mouth line} for the columns of the smile: the first thin dark
    line under the nose (the beard is dark too, but thick, and is skipped)."""
    nx, ny = nose
    y0, y1 = ny + 28, ny + 115
    found = {}
    for x in range(nx - 170, nx + 150):
        dark = arr[y0:y1, x].sum(axis=1) < 200
        idx = np.nonzero(dark)[0]
        if not len(idx):
            continue
        i = j = idx[0]
        while j + 1 < len(dark) and dark[j + 1]:
            j += 1
        if j - i <= 16 and j + 6 < len(dark) and not dark[j + 3:j + 7].any():
            found[x] = y0 + j + 1
    # keep the run of columns around the nose (small gaps allowed)
    xs = sorted(found)
    if not xs:
        return {}
    runs, cur = [], [xs[0]]
    for x in xs[1:]:
        if x - cur[-1] <= 4:
            cur.append(x)
        else:
            runs.append(cur)
            cur = [x]
    runs.append(cur)
    best = min(runs, key=lambda r: 0 if r[0] <= nx <= r[-1] else min(abs(r[0] - nx), abs(r[-1] - nx)) + 1000 - len(r))
    return {x: found[x] for x in range(best[0], best[-1] + 1) if x in found}


def _hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def cutout_mask(img):
    """Transparent background: flood-fill the bluish background from the image border.
    The black outline stops the fill; white whiskers are kept."""
    a = np.asarray(img).astype(int)
    H, W = a.shape[:2]
    R, B, tot = a[..., 0], a[..., 2], a.sum(axis=2)
    bgable = ((R < 18) & (B > 30)) | (((B - R) > 20) & (tot > 240))
    lab, _ = ndimage.label(bgable)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge))
    m = Image.fromarray(((~bg) * 255).astype("uint8"))
    return m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))


class Pose:
    def __init__(self, name, path=None):
        self.name = name
        self.base = Image.open(path or os.path.join(AVATAR_DIR, f"{PREFIX}_{name}.png")).convert("RGB")
        arr = np.asarray(self.base).astype(int)
        nx, ny, score = _nose(self.base)
        self.animated = score >= NOSE_MIN_SCORE and name not in STILL_POSES
        if score < NOSE_MIN_SCORE:
            nx, ny = REF_NOSE
        self.nose = (nx, ny)
        self.offset = (nx - REF_NOSE[0], ny - REF_NOSE[1])
        self.smile = _smile(arr, self.nose) if self.animated else {}
        noseless = arr.copy()
        noseless[ny - 40:ny + 40, nx - 65:nx + 65] = 0      # the nose shine is white too
        self.eyes = [e for e in (_largest_white(noseless, (nx - 320, ny - 190, nx - 20, ny + 10)),
                                 _largest_white(noseless, (nx - 20, ny - 200, nx + 210, ny))) if e] if self.animated else []
        self.mask = cutout_mask(self.base)
        self._blink = None

    # ---- mouth
    def jaw(self, open_px, rounded=False, img=None):
        img = img or self.base
        sb = self.smile
        if open_px <= 0 or len(sb) < 20:
            return img
        xs_all = sorted(sb)
        x_lo, x_hi = xs_all[0], xs_all[-1]
        c = (x_lo + x_hi) / 2
        half = (x_hi - x_lo) * (0.17 if rounded else 0.30)     # the jaw opens in the middle
        xa, xb = c - half, c + half
        S = 4
        OX, OY = int(xa) - 40, min(sb[x] for x in xs_all) - 30
        OW, OH = int(xb - xa) + 80, max(sb[x] for x in xs_all) - OY + open_px + 40
        big = img.crop((OX, OY, OX + OW, OY + OH)).convert("RGBA").resize((OW * S, OH * S), Image.LANCZOS)
        d = ImageDraw.Draw(big)
        xs = [x for x in range(int(xa), int(xb) + 1) if x in sb]
        if len(xs) < 5:
            return img
        w = xs[-1] - xs[0]
        top = [(x, sb[x] - 2) for x in xs]
        bot = []
        for x in reversed(xs):
            t = (x - xs[0]) / w
            prof = math.sin(math.pi * t) ** (0.7 if rounded else 0.9)
            bot.append((x, sb[x] - 2 + open_px * prof))
        poly = [((x - OX) * S, (y - OY) * S) for x, y in top + bot]
        d.polygon(poly, fill=MOUTH_IN + (255,))
        if open_px >= 14:
            tl = Image.new("L", big.size, 0)
            cx = (xs[0] + xs[-1]) / 2
            ImageDraw.Draw(tl).ellipse([(cx - w * 0.3 - OX) * S, (min(y for _, y in bot) + open_px * 0.45 - OY) * S,
                                        (cx + w * 0.3 - OX) * S, (max(y for _, y in bot) + open_px * 0.5 - OY) * S],
                                       fill=255)
            m = Image.new("L", big.size, 0)
            ImageDraw.Draw(m).polygon(poly, fill=255)
            big.paste(Image.new("RGBA", big.size, TONGUE + (255,)), (0, 0), ImageChops.multiply(tl, m))
        d.line([((x - OX) * S, (y - OY) * S) for x, y in bot], fill=INK + (255,), width=8 * S, joint="curve")
        out = img.copy()
        out.paste(big.resize((OW, OH), Image.LANCZOS).convert("RGB"), (OX, OY))
        return out

    # ---- eyes
    def _eyes_box(self):
        xs = [p[0] for e in self.eyes for p in e]
        ys = [p[1] for e in self.eyes for p in e]
        return (min(xs) - 60, min(ys) - 60, max(xs) + 60, max(ys) + 60)

    def blink(self, img):
        """Same picture with the eyes closed (the mouth never touches the eye patch)."""
        if not self.eyes:
            return img
        box = self._eyes_box()
        if self._blink is None:
            self._blink = self._blink_patch(img.crop(box), box)
        out = img.copy()
        out.paste(self._blink, box[:2])
        return out

    def _eye_region(self, arr, pts):
        """Whole eye (white, pupil and its own outline) as a mask over the full image."""
        H, W = arr.shape[:2]
        hull = Image.new("L", (W, H), 0)
        ImageDraw.Draw(hull).polygon(_hull(pts), fill=255)
        hull = np.asarray(hull) > 0
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x1, y1 = max(min(xs) - 40, 0), max(min(ys) - 40, 0)
        x2, y2 = min(max(xs) + 40, W), min(max(ys) + 40, H)
        sub = arr[y1:y2, x1:x2]
        h = hull[y1:y2, x1:x2]
        dark = sub.sum(axis=2) < 200
        # dark pixels touching the white (outline and pupil), then everything they enclose
        lab, _ = ndimage.label(dark)
        touch = set(np.unique(lab[ndimage.binary_dilation(h, iterations=3) & dark])) - {0}
        eye = h | np.isin(lab, list(touch))
        # stay close to the eye (drops eyebrows or glasses touching the outline), then fill
        # what the outline encloses: a pupil sitting against the outline is inside it
        eye &= ndimage.distance_transform_edt(~h) < 18
        eye = ndimage.binary_fill_holes(ndimage.binary_closing(eye, iterations=4))
        eye = ndimage.binary_dilation(eye, iterations=3)
        out = np.zeros((H, W), bool)
        out[y1:y2, x1:x2] = eye
        return out

    def _blink_patch(self, crop, box):
        arr = np.asarray(self.base).astype(float)
        OX, OY, X2, Y2 = box
        patch = arr[OY:Y2, OX:X2].copy()
        tot = patch.sum(axis=2)
        white = (patch.min(axis=2) > 228) & ((patch.max(axis=2) - patch.min(axis=2)) < 22)
        fur_like = ~white & (tot > 45)          # around a panda eye: the dark patch
        light = arr.sum(axis=2) > 560
        lab, n = ndimage.label(light)
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)) if n else np.array([0])
        face = lab == (int(np.argmax(sizes)) + 1)
        lines = []
        for pts in self.eyes:
            m = ndimage.binary_dilation(self._eye_region(arr, pts), iterations=2)[OY:Y2, OX:X2]
            ring = ndimage.binary_dilation(m, iterations=25) & ~m & fur_like
            fill = np.median(patch[ring], axis=0)
            dark = ring & (tot < 300)
            dark_patch = dark.sum() > 0.3 * ring.sum()     # panda: the eye sits in a dark patch
            if dark_patch:
                fill = np.median(patch[dark], axis=0)
                # never paint over the face fur (the big light area) or the background
                m = m & ~face[OY:Y2, OX:X2] & (np.asarray(self.mask)[OY:Y2, OX:X2] > 128)
                patch[m] = fill
            # otherwise each row blends from the fur on the left of the eye to the fur on the right
            for y in (np.nonzero(m.any(axis=1))[0] if not dark_patch else []):
                row = m[y]
                xs = np.nonzero(row)[0]
                a, b = xs.min(), xs.max()
                lpx = [patch[y, x] for x in range(max(a - 25, 0), a) if fur_like[y, x] and not row[x]]
                rpx = [patch[y, x] for x in range(b + 1, min(b + 26, row.size)) if fur_like[y, x] and not row[x]]
                lc = np.median(lpx, axis=0) if len(lpx) >= 3 else fill
                rc = np.median(rpx, axis=0) if len(rpx) >= 3 else fill
                for x in xs:
                    u = (x - a) / max(b - a, 1)
                    patch[y, x] = lc * (1 - u) + rc * u
            sm = np.stack([ndimage.uniform_filter(patch[..., c], 9) for c in range(3)], axis=2)
            patch[m] = sm[m]
            hx = [p[0] for p in pts]
            hy = [p[1] for p in pts]
            l, r, t, b = min(hx), max(hx), min(hy), max(hy)       # the eye white, not the mask
            l, r = l + 4, r - 4
            lash = (226, 214, 208) if dark_patch else INK    # light line on the dark patch
            yl = t + (b - t) * 0.55
            lines.append((lash, [(l + (r - l) * u - OX, yl + (b - t) * 0.10 * math.sin(math.pi * u) - OY)
                                 for u in np.linspace(0, 1, 40)]))
        S = 4
        img = Image.fromarray(np.clip(patch, 0, 255).astype("uint8"))
        big = img.resize((img.width * S, img.height * S), Image.LANCZOS)
        d = ImageDraw.Draw(big)
        for col, ln in lines:
            n = len(ln)
            for k in range(n - 1):
                u = k / (n - 2)
                w = 4 + 6 * math.sin(math.pi * u)          # thicker in the middle, tapered ends
                d.line([(ln[k][0] * S, ln[k][1] * S), (ln[k + 1][0] * S, ln[k + 1][1] * S)],
                       fill=col, width=int(w * S))
                d.ellipse([(ln[k][0] - w / 2) * S, (ln[k][1] - w / 2) * S,
                           (ln[k][0] + w / 2) * S, (ln[k][1] + w / 2) * S], fill=col)
        return big.resize(img.size, Image.LANCZOS)


# ---------------------------------------------------------------- audio -> mouth
def read_wav(path):
    with wave.open(path) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        data = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32)
    if ch > 1:
        data = data.reshape(-1, ch).mean(axis=1)
    return data / 32768.0, sr


def mouth_track(samples, sr, fps=FPS):
    """[(level 0-3, rounded?)] per frame plus the loudness curve."""
    hop = sr // fps
    n = len(samples) // hop
    rms, cent = np.zeros(n), np.zeros(n)
    freqs = np.fft.rfftfreq(hop * 2, 1 / sr)
    win = np.hanning(hop * 2)
    for i in range(n):
        seg = samples[i * hop:i * hop + hop * 2]
        seg = np.pad(seg, (0, hop * 2 - len(seg)))
        rms[i] = np.sqrt((seg ** 2).mean())
        spec = np.abs(np.fft.rfft(seg * win))
        cent[i] = (spec * freqs).sum() / (spec.sum() + 1e-9)
    loud = np.clip(rms / (np.percentile(rms, 95) + 1e-9), 0, 1.2)
    out, cur, hold, e = [], 0, 0, 0.0
    for i, l in enumerate(loud):
        e = l if l > e else e * 0.6 + l * 0.4
        target = 0 if e < 0.12 else 1 if e < 0.40 else 2 if e < 0.72 else 3
        if target != cur and hold <= 0:
            cur += 1 if target > cur else -1
            hold = 1
        hold -= 1
        out.append((cur, cur >= 1 and 0 < cent[i] < 850))
    return out, loud


# ---------------------------------------------------------------- rig
class Rig:
    """All requested poses aligned by the nose, cut out, sharing one crop box."""

    def __init__(self, poses, width):
        self.poses = {p: Pose(p) for p in dict.fromkeys(poses)}
        boxes = []
        for p in self.poses.values():
            b = p.mask.getbbox()
            dx, dy = p.offset
            boxes.append((b[0] - dx, b[1] - dy, b[2] - dx, b[3] - dy))
        self.box = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), min(b[3] for b in boxes))
        # same scale for every pose (not the union box), so the head is always the same size;
        # `width` is the width of a ~1000 px wide body
        self.scale = width / 1000
        self.size = (round((self.box[2] - self.box[0]) * self.scale), round((self.box[3] - self.box[1]) * self.scale))
        self.cache = {}

    def image(self, pose, level=0, rounded=False, closed=False):
        key = (pose, level, rounded, closed)
        if key not in self.cache:
            p = self.poses[pose]
            if not p.animated:
                level, closed = 0, False
            im = p.jaw(LEVELS[level], rounded)
            if closed:
                im = p.blink(im)
            dx, dy = p.offset
            bx = (self.box[0] + dx, self.box[1] + dy, self.box[2] + dx, self.box[3] + dy)
            rgba = im.convert("RGBA")
            m = np.asarray(p.mask).astype(float)
            yy = np.arange(m.shape[0])[:, None]
            m *= np.clip((bx[3] - yy) / FADE_PX, 0, 1)
            rgba.putalpha(Image.fromarray(m.astype("uint8")))
            rgba = rgba.crop(bx)
            self.cache[key] = rgba.resize(self.size, Image.LANCZOS)
        return self.cache[key]


class Animator:
    """Per-frame panda: mouth from the audio, blinks, a little sway, and a pop when the
    pose changes. Call frame(n, pose) for n = 0, 1, 2, ..."""

    def __init__(self, rig, samples, sr, seed=7):
        self.rig = rig
        self.track, self.loud = mouth_track(samples, sr)
        self.rng = random.Random(seed)
        self.next_blink = self.rng.uniform(1.5, 3.5) * FPS
        self.left = 0
        self.smooth = 0.0
        self.last_pose, self.since = None, 99

    def frame(self, n, pose):
        """(RGBA image, dy) for frame n; dy is relative to the resting position."""
        if pose != self.last_pose:
            self.last_pose, self.since = pose, 0
        self.since += 1
        if n >= self.next_blink:
            self.left, self.next_blink = 4, n + self.rng.uniform(2.5, 5.0) * FPS
        closed = self.left > 0
        self.left = max(0, self.left - 1)
        level, rounded = self.track[min(n, len(self.track) - 1)]
        loud = self.loud[min(n, len(self.loud) - 1)]
        self.smooth = 0.85 * self.smooth + 0.15 * min(loud, 1.2)
        img = self.rig.image(pose, level, rounded, closed)
        t = n / FPS
        ang = math.sin(t * 2 * math.pi * 0.3) * 1.0 + self.smooth * 1.2
        img = img.rotate(ang, resample=Image.BICUBIC)
        if self.since < 8:
            pop = 0.90 + 0.14 * math.sin(min(self.since / 8, 1) * math.pi * 0.75) / math.sin(math.pi * 0.75)
            img = img.resize((round(img.width * pop), round(img.height * pop)), Image.BICUBIC)
        dy = math.sin(t * 2 * math.pi * 0.45) * 3 - self.smooth * 6
        return img, dy


def pick_poses(n_slides, rng, requested=None):
    """One pose per slide: hook, middle, close. `requested` is a list with a pose name or
    None per slide (from the script)."""
    requested = requested or [None] * n_slides
    out, used = [], set()
    for i in range(n_slides):
        if requested[i]:
            out.append(requested[i])
            used.add(requested[i])
            continue
        role = "hook" if i == 0 else "close" if i == n_slides - 1 else "middle"
        opts = [p for p in ROLE_POSES[role] if p not in used] or ROLE_POSES[role]
        p = rng.choice(opts)
        out.append(p)
        used.add(p)
    return out


def available_poses():
    n = len(PREFIX) + 1
    return sorted(os.path.basename(f)[n:-4] for f in glob.glob(os.path.join(AVATAR_DIR, f"{PREFIX}_*.png")))


# ---------------------------------------------------------------- CLI
def sheet(path):
    names = available_poses()
    rig = Rig(names, 250)
    cols = 4
    tile_w, tile_h = rig.size
    out = Image.new("RGB", (cols * tile_w, len(names) * (tile_h + 24)), (40, 12, 44))
    d = ImageDraw.Draw(out)
    for r, n in enumerate(names):
        for c, args in enumerate([(0, False, False), (3, False, False), (2, True, False), (0, False, True)]):
            im = rig.image(n, *args)
            out.paste(im, (c * tile_w, r * (tile_h + 24) + 24), im)
        d.text((6, r * (tile_h + 24) + 4), f"{n}  (cerrada / abierta / o / parpadeo)", fill="white")
    out.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet")
    a = ap.parse_args()
    if a.sheet:
        sheet(a.sheet)


if __name__ == "__main__":
    main()
