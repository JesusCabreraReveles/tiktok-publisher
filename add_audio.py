#!/usr/bin/env python3
"""
add_audio.py - Gives a LinkedIn diagram video a soundtrack, so it is never silent.

  1. Voice (optional): linkedin/<name>.voice.json, written by Claude next to the .html:
       {"voice": "am_michael",
        "segments": [{"at": 0.4,  "say": "Most outages get worse because of our retries."},
                     {"at": 6.5,  "say": "The fix: backoff, jitter, a budget and a breaker."},
                     {"at": 11.0, "say": "Retry with rules, not by reflex."}]}
     "at" = second when the line starts (match the diagram's problem / fix / takeaway).
     Read in English by the same Kokoro engine as TikTok. If a line would start before the
     previous one ends, it waits for it. If the voice runs past the end of the video, the
     last frame is held until the voice ends (plus a short tail).
  2. Background music: a soft ambient pad generated here (numpy, no files, no rights issues).
     Quiet under the voice; on its own when there is no voice file or the voice fails.

Usage:
  python3 add_audio.py silent.mp4 -o final.mp4 [--voice linkedin/2026-11-11.voice.json]
                       [--seed 123] [--no-music]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SR = 24000            # Kokoro's sample rate; the music is made at the same rate
VOICE_GAP = 0.25      # minimum pause between two lines
TAIL = 0.8            # silence kept after the last word when the video is extended
MUSIC_UNDER_VOICE = 0.10   # music level when there is a voice (about -20 dB)
MUSIC_ALONE = 0.40         # music level when it plays alone


def probe_duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", path],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


# ---------- voice ----------
def voice_track(spec_path):
    """Return (samples, end_time) of the narration placed on the timeline, or (None, 0)."""
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    segs = [s for s in spec.get("segments", []) if (s.get("say") or "").strip()]
    if not segs:
        return None, 0.0
    from kokoro_onnx import Kokoro
    model = os.environ.get("KOKORO_MODEL", os.path.join(HERE, "voices", "kokoro-v1.0.int8.onnx"))
    voices = os.environ.get("KOKORO_VOICES", os.path.join(HERE, "voices", "voices-v1.0.bin"))
    k = Kokoro(model, voices)
    voice = spec.get("voice") or "am_michael"
    speed = float(spec.get("speed", 1.0))
    placed, t_free = [], 0.0
    for i, s in enumerate(sorted(segs, key=lambda s: float(s.get("at", 0)))):
        audio, sr = k.create(s["say"].strip(), voice=voice, speed=speed, lang="en-us")
        audio = np.asarray(audio, dtype=np.float32)
        if sr != SR:   # Kokoro is 24 kHz; resample just in case
            n = int(len(audio) * SR / sr)
            audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
        at = float(s.get("at", 0))
        start = max(at, t_free)
        if start - at > 0.5:
            print(f"  WARNING: line {i + 1} starts {start - at:.1f}s late (the line before is too "
                  f"long for its slot; voice and diagram drift apart)")
        placed.append((start, audio))
        t_free = start + len(audio) / SR + VOICE_GAP
        print(f"  voice {i + 1}/{len(segs)}: {start:5.2f}s -> {start + len(audio) / SR:5.2f}s")
    end = max(st + len(a) / SR for st, a in placed)
    track = np.zeros(int((end + 0.05) * SR) + 1, dtype=np.float32)
    for st, a in placed:
        i0 = int(st * SR)
        track[i0:i0 + len(a)] += a
    return track, end


# ---------- music ----------
# A calm progression (Am - F - C - G), one chord every 4 s, as soft detuned sine pads with a
# slow bass and a quiet "breath" of filtered noise. Different seeds shift the key a little.
CHORDS = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]   # MIDI notes
BASS = [45, 41, 48, 43]


def midi_hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def music_track(duration, seed=0):
    rng = np.random.default_rng(seed)
    shift = int(rng.integers(-2, 3))          # small key change per video
    n = int(duration * SR)
    t = np.arange(n) / SR
    out = np.zeros(n, dtype=np.float64)
    bar = 4.0
    xfade = 1.2
    for b in range(int(np.ceil(duration / bar)) + 1):
        c = CHORDS[b % len(CHORDS)]
        t0 = b * bar - xfade / 2
        i0, i1 = max(0, int(t0 * SR)), min(n, int((t0 + bar + xfade) * SR))
        if i0 >= i1:
            continue
        tt = t[i0:i1] - t0
        L = bar + xfade
        env = np.clip(np.minimum(tt / xfade, (L - tt) / xfade), 0, 1)
        env = env * env * (3 - 2 * env)       # smooth fade in/out
        seg = np.zeros(i1 - i0)
        for note in c:
            f = midi_hz(note + shift)
            for det in (-0.12, 0.0, 0.12):    # three slightly detuned voices = soft chorus
                ph = rng.uniform(0, 2 * np.pi)
                seg += np.sin(2 * np.pi * f * (1 + det / 100) * tt + ph)
            seg += 0.25 * np.sin(2 * np.pi * 2 * f * tt)     # gentle upper harmonic
        bf = midi_hz(BASS[b % len(BASS)] + shift - 12)
        seg += 1.6 * np.sin(2 * np.pi * bf * tt)
        out[i0:i1] += seg * env
    # slow breathing tremolo + very quiet low-passed noise for air
    out *= 0.85 + 0.15 * np.sin(2 * np.pi * 0.11 * t)
    noise = rng.standard_normal(n)
    k = 400
    noise = np.convolve(noise, np.ones(k) / k, mode="same")
    out += noise * 6.0
    # fade the whole thing in and out
    fade = min(1.5, duration / 4)
    g = np.ones(n)
    fi = int(fade * SR)
    if fi > 0:
        g[:fi] = np.linspace(0, 1, fi)
        g[-fi:] = np.minimum(g[-fi:], np.linspace(1, 0, fi))
    out *= g
    peak = np.max(np.abs(out)) or 1.0
    return (out / peak).astype(np.float32)


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(description="Add voice and/or background music to a silent MP4")
    ap.add_argument("video")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--voice", help="linkedin/<name>.voice.json (optional)")
    ap.add_argument("--seed", type=int, default=0, help="changes the music key per video")
    ap.add_argument("--no-music", action="store_true")
    args = ap.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg/ffprobe are not installed")

    import soundfile as sf
    vid_dur = probe_duration(args.video)

    voice, voice_end = None, 0.0
    if args.voice and os.path.isfile(args.voice):
        try:
            print("Voice...")
            voice, voice_end = voice_track(args.voice)
        except Exception as e:   # a voice problem must never leave the video silent
            print(f"WARNING: voice failed ({type(e).__name__}: {e}). Using music only.")
            voice = None
    elif args.voice:
        print(f"No voice file ({args.voice}): music only.")

    total = max(vid_dur, voice_end + TAIL) if voice is not None else vid_dur
    hold = max(0.0, total - vid_dur)
    n = int(total * SR)
    mix = np.zeros(n, dtype=np.float32)
    if not args.no_music:
        level = MUSIC_UNDER_VOICE if voice is not None else MUSIC_ALONE
        mix += level * music_track(total, args.seed)
    if voice is not None:
        mix[:len(voice)] += 0.9 * voice[:n] / (np.max(np.abs(voice)) or 1.0)
    if not np.any(mix):
        sys.exit("Nothing to add (no voice and --no-music).")
    peak = np.max(np.abs(mix))
    if peak > 0.98:
        mix *= 0.98 / peak

    with tempfile.TemporaryDirectory() as work:
        wav = os.path.join(work, "track.wav")
        sf.write(wav, mix, SR)
        vf = ["-vf", f"tpad=stop_mode=clone:stop_duration={hold:.3f}"] if hold > 0.01 else []
        vcodec = (["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]
                  if vf else ["-c:v", "copy"])
        tmp_out = args.output + ".tmp.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", args.video, "-i", wav,
                        *vf, "-map", "0:v:0", "-map", "1:a:0", *vcodec,
                        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                        "-t", f"{total:.3f}", "-movflags", "+faststart", tmp_out], check=True)
        os.replace(tmp_out, args.output)
    what = ("voice + music" if voice is not None and not args.no_music
            else "voice" if voice is not None else "music")
    extra = f", last frame held {hold:.1f}s" if hold > 0.01 else ""
    print(f"Audio added ({what}): {args.output} ({total:.1f}s{extra})")


if __name__ == "__main__":
    main()
