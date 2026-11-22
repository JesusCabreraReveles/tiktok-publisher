"""Narración de la promo: Kokoro em_alex, es-419, cada frase en su tiempo.

Uso: python3 voz.py [ruta_modelos]   →  assets/voz.wav (22 s, 24 kHz)
"""
import sys, os
import numpy as np, soundfile as sf
from kokoro_onnx import Kokoro

MODELS = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/models')
k = Kokoro(f'{MODELS}/kokoro-v1.0.onnx', f'{MODELS}/voices-v1.0.bin')

# (texto, segundo en que empieza) — rejilla de 2 s (120 BPM)
LINES = [
    ("¿Dónde está mi flotilla?", 0.25),
    ("Nexus. GPS en tiempo real, en web y en app.", 2.15),
    ("¿Y si el dispositivo no tiene GPS?", 6.05),
    ("Orion lo ubica con la señal celular.", 8.6),
    ("Si me accidento en moto, ¿quién sabe quién soy?", 12.05),
    ("Signum. Tu identidad médica en un código QR.", 14.6),
    ("Geminis Labs. De la señal a la decisión.", 18.35),
]
SR, T = 24000, 22.0
out = np.zeros(int(T * SR), dtype=np.float32)
for text, t in LINES:
    a, sr = k.create(text, voice='em_alex', speed=1.1, lang='es-419')
    nz = np.where(np.abs(a) > 0.01)[0]
    a = a[max(0, nz[0] - 240):nz[-1] + 480]
    s = int(t * SR)
    out[s:s + len(a)] += a[:len(out) - s]
    print(f'{t:5.2f}–{t + len(a) / SR:5.2f}  {text}')
# +5 dB (sin pasar de 0.95 de pico)
out *= min(10 ** (5 / 20), 0.95 / np.abs(out).max())
os.makedirs('assets', exist_ok=True)
sf.write('assets/voz.wav', out, SR)
