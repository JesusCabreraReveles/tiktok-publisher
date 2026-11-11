# Diagramas animados para LinkedIn (plan v3)

Convierte un diagrama animado (un archivo HTML) en un video MP4 para LinkedIn.
Claude escribe el HTML y la Raspberry Pi lo convierte en video. Costo extra: $0.

Los diagramas viven en `linkedin/` (nunca en `guiones/`, que es solo para TikTok).

## Instalación en la Raspberry Pi (una sola vez)

```bash
cd ~/tiktok-publisher
git pull
source .venv/bin/activate
pip install playwright
python3 -m playwright install chromium
```

Si el último comando falla (Raspberry Pi OS a veces no es compatible con el Chromium de
Playwright), usa el Chromium del sistema. El script lo encuentra solo:

```bash
sudo apt install -y chromium
```

Las fuentes (`fonts-inter`) y `ffmpeg` ya están instalados por el flujo de TikTok.

## Prueba

```bash
python3 render_diagram.py linkedin/prueba-outbox.html -o /tmp/prueba-outbox.mp4
```

Al terminar muestra el tamaño y cuánto tardó. En la Pi 5, un video de 15 s tarda 48 s.
Para revisar un solo cuadro sin hacer todo el video:

```bash
python3 render_diagram.py linkedin/prueba-outbox.html --still /tmp/cuadro.png --at 9
```

## Formato del diagrama (para Claude)

- Un solo archivo HTML, sin fuentes ni imágenes de internet. Fuente: Inter.
- `<meta name="duration" content="15">` y `<meta name="size" content="1080x1350">` (4:5).
- Animaciones con CSS (`animation` con `animation-delay`) o SVG `<animate>`. **Sin
  temporizadores de JavaScript**: el script pausa las animaciones y las mueve cuadro por
  cuadro, y los temporizadores no se pueden pausar.
- Contar una historia en 2 pasos (problema → solución), 12 a 15 s, terminando con el
  diagrama completo y una frase final.
- Colores del miércoles: verde + lima (los mismos que TikTok).
- El texto del post va aparte, en `linkedin/<nombre>.txt`, en inglés y con el footer.

## Sonido (desde el 11 nov 2026)

Ningún video de LinkedIn sale mudo. `add_audio.py` le pone a cada video:

1. **Voz en inglés** (Kokoro `am_michael`, el mismo motor que TikTok), si existe
   `linkedin/<nombre>.voice.json` junto al `.html`:

   ```json
   {"voice": "am_michael",
    "segments": [{"at": 0.4,  "say": "Naive retries amplify outages."},
                 {"at": 6.5,  "say": "The fix: backoff, jitter, a retry budget, and a breaker."},
                 {"at": 11.2, "say": "Retry less. Recover sooner."}]}
   ```

   `at` = segundo en que empieza la frase (problema → solución → frase final). Regla para que
   la voz no se atrase: **unas 2 palabras por segundo** de espacio hasta la siguiente frase.
   Si una frase empieza más de 0.5 s tarde, el log dice `WARNING: line N starts … late`.
   Si la voz dura más que el video, se congela el último cuadro hasta que termina.
2. **Música de fondo suave**, generada en la Pi (sin archivos ni derechos de autor). Baja
   debajo de la voz y sola si no hay `.voice.json` o si falla la voz.

Si hasta la música fallara, el video sale mudo (con aviso en el log) en vez de detenerse.
Probar solo el audio sobre un video ya hecho:

```bash
python3 add_audio.py /tmp/prueba-outbox.mp4 -o /tmp/con-audio.mp4 --voice linkedin/2026-11-11.voice.json
```

## Flujo diario (paso 2)

1. La tarea de Claude guarda, para cada post con video:
   - `linkedin/AAAA-MM-DD.html` (diagrama) + `linkedin/AAAA-MM-DD.txt` (texto del post)
     + `linkedin/AAAA-MM-DD.voice.json` (narración), y
   - los miércoles, también `linkedin/AAAA-MM-DD-book.html` + `.txt` (post del libro, abre con
     la portada: `<img src="../portadas/<código>.jpg">`), con su `-book.voice.json`.
2. `publish_daily.py` (cron de la Pi, el mismo de TikTok) convierte cada par en
   `docs/videos/li-<nombre>-<hash>.mp4`, lo sube junto con los de TikTok y manda a Make:
   `{"caption": <texto del post>, "video_url": ..., "platform": "linkedin"}`.
3. Make: usa **el mismo escenario de TikTok** (ya crea el borrador con el perfil de LinkedIn).
   El borrador llega a SocialBee (categoría TikTok IA), en inglés y con el video: se publica
   tal cual en LinkedIn, **sin cambiarlo a TikTok**.

Opcional: si algún día se quiere separar (otra categoría), se clona el escenario de Make y se
pone su URL en `config.json` como `"make_webhook_linkedin_url"`; sin esa línea se usa el de TikTok.

Si algo falla en un post de LinkedIn (no hay `.txt`, falta una portada, falla el render o
falla el envío), **ese post se detiene y los videos de TikTok salen igual**.
La corrida termina con error para que el reintento lo vuelva a intentar. Nada se manda dos veces.

```bash
python3 publish_daily.py --dry-run     # genera los videos sin subir ni mandar nada
```
