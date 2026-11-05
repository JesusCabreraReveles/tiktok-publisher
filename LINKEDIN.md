# Diagramas animados para LinkedIn (plan v3, paso 1)

Convierte un diagrama animado (un archivo HTML) en un video MP4 para LinkedIn.
Claude escribe el HTML y la Raspberry Pi lo convierte en video. Costo extra: $0.

Este paso todavía **no** cambia el flujo diario: `publish_daily.py` solo lee `guiones/`,
y los diagramas viven en `linkedin/`. La conexión con Make y SocialBee es el paso 2.

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

Al terminar muestra el tamaño y cuánto tardó. En el servidor de Claude tardó 30 s;
en la Pi 5 calculo de 1 a 3 minutos. Para revisar un solo cuadro sin hacer todo el video:

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
  diagrama completo y una frase final. Sin voz: LinkedIn reproduce los videos en silencio.
- Colores del miércoles: verde + lima (los mismos que TikTok).
- El texto del post va aparte, en `linkedin/<nombre>.txt`, en inglés y con el footer.

## Siguiente paso (paso 2)

1. La tarea diaria de LinkedIn guarda `linkedin/AAAA-MM-DD.html` y `linkedin/AAAA-MM-DD.txt`.
2. `publish_daily.py` (o un script hermano) los convierte en MP4, los publica en GitHub Pages
   y manda texto + URL del video a un webhook de Make nuevo → SocialBee (perfil LinkedIn,
   categoría LinkedIn IA, Approved: No).
3. Antes: la limpieza automática de videos (v1.3), porque GitHub Pages tiene límite de 1 GB.
