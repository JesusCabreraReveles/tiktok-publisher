# Promo Geminis Labs · "Preguntas reales" (huashu-motion)

Hecha el 22 nov 2026 en una conversación con Claude. Jesús aprobó el resultado con la **música original compuesta** por la skill. **Publicada en TikTok (@jcr1984) el 22 nov 2026** desde SocialBee.

- 22 s, 1080×1350 (4:5), español (México).
- Tres preguntas tachadas y respondidas: ¿Dónde está mi flotilla? → **Nexus** · ¿Y si no tiene GPS? → **Orion** · Si me accidento en moto, ¿quién sabe quién soy? → **Signum**. Cierre: logo Geminis Labs + "De la señal a la decisión." + geminislabs.com.
- Voz: Kokoro `em_alex`, `es-419` (`voz.py`). Música: compuesta por huashu-motion (`OM.music({ style: 'pulse', ... })`) con su paquete de instrumentos reales: pieza nueva, sin riesgo de Content ID.

## Archivos
| Archivo | Qué es |
|---|---|
| `index.html` | La composición (GSAP + om.js). Textos, colores y pausa final son variables editables. Busca las imágenes en `assets/`. |
| `guion.txt` | Las 7 frases de la narración. |
| `voz.py` | Genera cada frase con Kokoro y arma `assets/voz.wav` en sus tiempos (sobre la rejilla de 2 s). |
| `treatment.md` | Plan de escenas y tiempos. (La línea de música es de la primera versión; la final usa música compuesta.) |
| `directions.md` | Las 3 direcciones que propuso la skill (Jesús eligió la C). |
| `materials.md` | De dónde salió cada material. |
| `wordmark.png`, `mark-nexus.png`, `mark-orion.png`, `mark-signum.png` | Logos (están junto al `index.html`; al regenerar se mueven a `assets/`, ver abajo). |

## Cómo volver a generarla
Requisitos: Node 18+, ffmpeg, Chrome/Chromium, Python con `kokoro-onnx` y los modelos `kokoro-v1.0.onnx` + `voices-v1.0.bin` (releases de `thewh1teagle/kokoro-onnx`).

```bash
git clone https://github.com/alchaincyf/huashu-motion && cd huashu-motion && git checkout 0a6157d   # versión revisada
OM=$PWD/skills/huashu-motion/bin/om
$OM samples build                      # instrumentos reales (una sola vez, ~51 MB)
$OM new ~/promo && cp -r promos/geminis-preguntas/* ~/promo/   # vendor/ (gsap, om.js) lo pone om new
cd ~/promo && mv *.png assets/           # los logos van en assets/
$OM fonts add Inter .
python3 voz.py                           # → assets/voz.wav
$OM voice . --audio assets/voz.wav --text guion.txt --asr off
$OM sound . && $OM check . && $OM render . && $OM qa .
```
Después: normalizar a −15 LUFS si hace falta y comprimir para SocialBee (≤3.8 MB):
`ffmpeg -i out/<video>.mp4 -c:v libx264 -preset veryfast -crf 27 -c:a aac -b:a 128k -movflags +faststart promo-socialbee.mp4`

## Publicar en TikTok desde SocialBee (probado el 22 nov 2026)
Create post → solo el perfil de TikTok → subir el MP4 al input de archivo → texto → **Customize for each profile** → privacidad **Public** (sin eso aparece "TikTok requires a privacy mode to be selected") → casillas Comment/Duet/Stitch vienen apagadas → Post now. Sin categoría no hay re-queue.

## Notas
- En el servidor de Claude `api.github.com` está bloqueado: para `om samples build` se generan los listados con `git fetch --filter=blob:none` + `git ls-tree` en `~/.cache/huashu-motion/samples/.src/<owner>_<repo>@<sha8>.json`, y hace falta `bsdtar` (`libarchive-tools`).
- `data-om-signature="off"` quita la firma "Made with huashu-motion".
- La voz `es` de la skill tiene acento de España; por eso se usa `voz.py` con `es-419`.
- Dune Rise (fuente de la marca) no tiene ñ ni acentos: solo en el logo; títulos en Inter.
- Para otro producto o mes: cambiar las variables de `index.html`, `guion.txt` y los tiempos de `voz.py`.
