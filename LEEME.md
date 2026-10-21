# tiktok-publisher

Convierte un guion corto (JSON) en un video vertical 1080×1920 con voz, titular grande y subtítulos,
y lo publica en TikTok con la API oficial. Todo corre en una Raspberry Pi 5: sin GPU, sin servicios de pago.

- **Voz:** Kokoro (modelo abierto, corre en CPU). Voces en inglés y español.
- **Imagen:** Pillow (Python).
- **Video:** ffmpeg.
- **Publicación:** TikTok Content Posting API.

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

## Generar un video

```bash
source .venv/bin/activate
python3 make_video.py guiones/ejemplo_en.json -o tiktok_en.mp4
python3 make_video.py guiones/ejemplo_es.json -o tiktok_es.mp4
```

En el servidor de pruebas (2 núcleos) cada video de ~28 s tardó unos 40 s. En la Raspberry
probablemente tarde de 1 a 4 minutos; hay que medirlo la primera vez.

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

## Publicar en TikTok (tiktok_upload.py)

Solo necesita Python, sin paquetes extra.

**Dos modos:**
- **Directo (predeterminado):** publica con la descripción y los hashtags del guion.
  Primero intenta en **público**. Si TikTok lo rechaza (app sin auditar), lo publica en
  **privado** automáticamente y te lo dice.
- `--inbox`: el video llega a tu app de TikTok como notificación y tú pones la descripción.

El video se marca como contenido hecho con IA (`is_aigc`), como pide TikTok.
Límite de TikTok: máximo 5 subidas pendientes en 24 horas.

### 1. Crear la app en TikTok (una sola vez)

1. En https://developers.tiktok.com crea una organización y una app.
2. Datos básicos: ícono (`docs/icon.png`), nombre, categoría, descripción, y las URLs de
   Términos y Privacidad de arriba.
3. Productos:
   - **Login Kit**, con Redirect URI `https://jesuscabrerareveles.github.io/tiktok-publisher/`
   - **Content Posting API**, con **Direct Post** activado.
4. Scopes: `user.info.basic`, `video.publish` y `video.upload` (este último solo para `--inbox`).
5. Para probar sin esperar revisión, usa la pestaña **Sandbox** y agrega tu cuenta de TikTok
   como usuario de prueba.

### 2. Configurar en la Raspberry

```bash
cp config.example.json config.json
nano config.json          # pega client_key y client_secret de tu app
chmod 600 config.json
python3 tiktok_upload.py auth
```

`auth` te da un enlace. Ábrelo, acepta, y TikTok te manda a la página del proyecto con
`?code=...` en la barra de direcciones. Copia esa dirección completa y pégala en la terminal.
Se guarda `tokens.json` y el script lo renueva solo.

`config.json` y `tokens.json` están en `.gitignore`: nunca se suben a GitHub.

### 3. Uso diario

```bash
python3 make_video.py guiones/hoy.json -o hoy.mp4
python3 tiktok_upload.py upload hoy.mp4 --script guiones/hoy.json                    # directo
python3 tiktok_upload.py upload hoy.mp4 --script guiones/hoy.json --privacy private  # privado
python3 tiktok_upload.py upload hoy.mp4 --inbox                                      # a tu bandeja
```

## Pendiente

1. Que Claude deje el guion del día en `guiones/` y la Raspberry lo tome con cron.
