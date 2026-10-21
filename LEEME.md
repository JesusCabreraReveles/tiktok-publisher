# tiktok-publisher

Convierte un guion corto (JSON) en un video vertical 1080×1920 con voz, titular grande y subtítulos,
y lo publica en TikTok. Todo el video se genera en una Raspberry Pi 5: sin GPU, sin servicios de pago.

- **Voz:** Kokoro (modelo abierto, corre en CPU). Voces en inglés y español.
- **Imagen:** Pillow (Python).
- **Video:** ffmpeg.
- **Publicación:** SocialBee (vía Make). La API directa de TikTok solo sirve para pruebas.

Páginas de la app (GitHub Pages, carpeta `docs/`):
- https://jesuscabrerareveles.github.io/tiktok-publisher/terms.html
- https://jesuscabrerareveles.github.io/tiktok-publisher/privacy.html

## Instalación en la Raspberry Pi 5

```bash
sudo apt update
sudo apt install -y git ffmpeg fonts-inter python3-venv espeak-ng

git clone https://github.com/JesusCabreraReveles/tiktok-publisher.git ~/tiktok-publisher
cd ~/tiktok-publisher

python3 -m venv .venv
source .venv/bin/activate
pip install kokoro-onnx soundfile pillow numpy

mkdir -p voices && cd voices
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx
wget https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
cd ..
```

El modelo pesa unos 120 MB en total y cabe de sobra en 4 GB de RAM.
En la Raspberry Pi 5, un video de ~28 s tarda unos 47 s en generarse.

## Generar un video

```bash
source .venv/bin/activate
python3 make_video.py guiones/ejemplo_en.json -o tiktok_en.mp4
python3 make_video.py guiones/ejemplo_es.json -o tiktok_es.mp4
```

## Formato del guion

```json
{
  "lang": "en",
  "voice": "am_michael",
  "tag": "AI · TUESDAY",
  "brand": "geminislabs.com",
  "caption": "Texto que aparece debajo del video.",
  "hashtags": ["#ai", "#softwareengineering", "#leadership", "#techtok"],
  "slides": [
    {"screen": "Titular grande en pantalla", "say": "Lo que dice la voz."}
  ]
}
```

- `lang`: `en` o `es`.
- `voice` (opcional). Inglés: `am_michael`, `am_adam`, `am_eric`, `bm_george` (británico), `af_heart`, `af_bella`…
  Español: `em_alex` (hombre), `ef_dora` (mujer).
- `caption` y `hashtags`: la descripción del post en TikTok.
- Recomendado: 4 a 6 slides, 20 a 45 segundos en total. El primer slide es el gancho.
- Hashtags: de 3 a 5, uno amplio (`#ai`, `#tech`), dos del tema del día y uno de comunidad (`#techtok`).

El diseño deja libre la franja derecha y la parte de abajo, que TikTok tapa con sus botones y la descripción.

## Flujo diario (publish_daily.py)

TikTok no aprueba apps de uso personal, así que la publicación va por SocialBee, que ya
tiene su app aprobada.

1. **Claude** deja el guion del día en `guiones/AAAA-MM-DD.json`.
2. **La Raspberry** (cron) ejecuta `publish_daily.py`:
   - `git pull`, genera `docs/videos/AAAA-MM-DD.mp4` y lo sube a GitHub;
   - espera a que GitHub Pages publique el video;
   - manda a Make la descripción con hashtags y la URL del video.
3. **Make** crea el post de TikTok en SocialBee como borrador.
4. **Tú** lo apruebas en SocialBee.

En `config.json` agrega `make_webhook_url` y `pages_base_url` (ver `config.example.json`).

```bash
python3 publish_daily.py --dry-run            # prueba sin subir nada
python3 publish_daily.py                      # guion de hoy
python3 publish_daily.py --date 2026-10-21    # otro día
```

La Raspberry sube a GitHub con una deploy key (`~/.ssh/tiktok_deploy`) que solo tiene acceso
a este repositorio.

## Pruebas con la API directa de TikTok (tiktok_upload.py)

TikTok solo deja publicar a apps sin auditar en **cuentas privadas**, y no aprueba apps de uso
personal. Este script queda para pruebas.

- Configuración: `client_key` y `client_secret` del Sandbox en `config.json`, luego
  `python3 tiktok_upload.py auth` (abre el enlace, acepta y pega la dirección con `?code=...`).
- Uso: `python3 tiktok_upload.py upload video.mp4 --script guion.json` (directo) o `--inbox`.
- `config.json` y `tokens.json` están en `.gitignore`: nunca se suben a GitHub.
