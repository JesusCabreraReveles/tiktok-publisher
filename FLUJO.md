# Flujo de publicación en TikTok

Estado: en construcción (20 oct 2026). La generación del video y la publicación por SocialBee
ya se probaron por separado. Falta conectar Make, el cron y la tarea de Claude.

Para instalar y usar los scripts, ver [LEEME.md](LEEME.md).

## Resumen

Cada día hábil se publica en TikTok un video corto (20–45 s) sobre tecnología y liderazgo,
con voz, titular en pantalla y subtítulos. Todo es gratis: el video se genera en una
Raspberry Pi 5 y se publica a través de SocialBee. Jesús revisa y aprueba cada post.

```mermaid
flowchart LR
    A["Claude<br/>(tarea programada)"] -->|"guiones/AAAA-MM-DD.json"| B["GitHub<br/>tiktok-publisher"]
    B -->|git pull| C["Raspberry Pi 5<br/>publish_daily.py"]
    C -->|"genera video<br/>(Kokoro + ffmpeg)"| C
    C -->|"git push<br/>docs/videos/AAAA-MM-DD.mp4"| B
    B -->|GitHub Pages| D["URL pública<br/>del video"]
    C -->|"webhook: caption + video_url"| E["Make<br/>(plan gratis)"]
    E -->|Create a Post| F["SocialBee<br/>borrador TikTok"]
    F -->|"Jesús aprueba"| G["TikTok<br/>@jcr1984"]
```

## Paso a paso

| # | Quién | Cuándo | Qué hace |
|---|-------|--------|----------|
| 1 | Claude (tarea programada) | Lunes a viernes, mañana | Investiga el tema del día, escribe el guion (slides, `caption`, `hashtags`) y lo guarda en `guiones/AAAA-MM-DD.json`. |
| 2 | Raspberry (cron) | Después de Claude | `publish_daily.py`: `git pull`, genera `docs/videos/AAAA-MM-DD.mp4`, lo sube a GitHub, espera a que Pages lo publique y avisa a Make. |
| 3 | Make | Al instante | Escenario "tiktok-publisher": webhook → SocialBee *Create a Post*. |
| 4 | SocialBee | Al instante | El post llega como borrador al perfil de TikTok, categoría "TikTok". |
| 5 | Jesús | Cuando quiera | Revisa el borrador en SocialBee, lo aprueba y lo publica (Share now o programado). |

Temas por día (los mismos que LinkedIn): lunes CEO/liderazgo, martes IA, miércoles ingeniería
de software/arquitectura, jueves founders/startups, viernes tendencias tech.

## Componentes y cuentas

| Componente | Detalle |
|-----------|---------|
| Repositorio | `JesusCabreraReveles/tiktok-publisher` (público, rama `master`) |
| GitHub Pages | Rama `master`, carpeta `/docs` → `https://jesuscabrerareveles.github.io/tiktok-publisher/` |
| Raspberry Pi 5 (4 GB) | Usuario `chch`, proyecto en `~/tiktok-publisher`, entorno `.venv` |
| Escritura desde la Raspberry | Deploy key `~/.ssh/tiktok_deploy` con permiso de escritura, solo en este repositorio |
| Escritura desde Claude | App "Claude Github MCP Connector" instalada solo en este repositorio |
| Voz | Kokoro int8 (`voices/`, ~120 MB). Inglés `am_michael`, español `em_alex` |
| Make | Plan gratis (1,000 créditos/mes). El flujo usa 2 créditos por video (~44/mes) |
| SocialBee | Workspace "My Workspace", perfil TikTok `jcr1984` en *Direct posting*, categoría "TikTok" |
| App de TikTok for Developers | "JCR-PUBLISHER" en la organización "JESUS CABRERA". Solo Sandbox, para pruebas |

## Configuración

### `config.json` (solo en la Raspberry, nunca en GitHub)

| Campo | Uso |
|-------|-----|
| `make_webhook_url` | URL del webhook de Make. Es secreta: quien la tenga puede crear posts. |
| `pages_base_url` | `https://jesuscabrerareveles.github.io/tiktok-publisher/` |
| `client_key`, `client_secret`, `redirect_uri`, `scopes` | Solo para `tiktok_upload.py` (Sandbox). |

### Escenario de Make "tiktok-publisher"

1. **Webhooks → Custom webhook** (recibe `date`, `caption`, `video_url`, `lang`).
2. **SocialBee → Create a Post**:
   - Workspace: My Workspace
   - Profiles: solo `jcr1984` (TikTok)
   - Category: TikTok
   - Text: `caption`
   - Media URL: `video_url`
   - Approve: No (llega como borrador)
   - Sin hora de publicación y sin expiración
3. Programación: *Immediately as data arrives*, escenario activo.

### Cron de la Raspberry (pendiente de activar)

La Raspberry debe estar en hora de Ciudad de México (`sudo timedatectl set-timezone America/Mexico_City`).
Con `crontab -e`:

```cron
15 9 * * 1-5  cd /home/chch/tiktok-publisher && mkdir -p logs && .venv/bin/python publish_daily.py >> logs/daily.log 2>&1
```

## Operación diaria

- **Revisar:** en SocialBee, categoría TikTok, aprobar el borrador del día.
- **Si no llegó el borrador:** revisar `logs/daily.log` en la Raspberry.
- **Volver a correr un día:** `python3 publish_daily.py --date AAAA-MM-DD`.
- **Probar sin publicar:** `python3 publish_daily.py --dry-run`.
- **Plan B:** si falla Make o SocialBee, el video está en
  `https://jesuscabrerareveles.github.io/tiktok-publisher/videos/AAAA-MM-DD.mp4` y la descripción
  en el guion del día. Se descarga y se sube a mano desde la app de TikTok.

## Problemas comunes

| Síntoma | Causa probable | Qué hacer |
|---------|----------------|-----------|
| `No script for AAAA-MM-DD` | Claude no dejó el guion ese día | Revisar la tarea programada de Claude. |
| `git push` pide contraseña o falla | Deploy key | Verificar `git config core.sshCommand` y la key en Settings → Deploy keys. |
| `The video never went live` | GitHub Pages no se actualizó | Revisar Actions/Pages en el repositorio. |
| Make no crea el post | Escenario apagado o webhook cambiado | Activar el escenario; revisar `make_webhook_url`. |
| El post no se publica tras aprobarlo | Hora fija vencida o expiración | No usar hora fija ni "Expire after" (igual que en LinkedIn). |

## Lecciones aprendidas

- **TikTok no acepta texto solo**: cada post necesita video o imágenes.
- **API directa de TikTok descartada**: una app sin auditar solo puede publicar en *cuentas privadas*
  (`unaudited_client_can_only_post_to_private_accounts`), y TikTok no aprueba herramientas que
  solo publican en cuentas propias. El modo bandeja (`--inbox`) en Sandbox respondió
  `SEND_TO_USER_INBOX` pero el borrador nunca apareció en la app.
- **SocialBee sí publica en público** en TikTok porque su app ya está aprobada (probado el 20 oct 2026).
- **Zapier no alcanza**: los webhooks son de pago y LinkedIn ya usa ~66 de las 100 tareas gratis.
  Por eso TikTok va por Make.
- **No hace falta GPU ni modelo de IA en la Raspberry**: el video se arma con voz Kokoro (CPU) y
  ffmpeg. Tarda ~47 s por video en la Pi 5. Claude escribe el guion.
- **Hugging Face está bloqueado** desde el entorno de Claude; los modelos de voz se descargan de GitHub.
- **Inicio de sesión en TikTok**: si se hacen varios intentos seguidos, TikTok bloquea temporalmente.
  Usar el código QR desde el celular, que además evita entrar con la cuenta equivocada.
- **GitHub con varias cuentas**: este proyecto usa `JesusCabreraReveles`. Los permisos de Claude
  y de la Raspberry están limitados a este repositorio.

## Pendientes

1. Crear el escenario de Make y probarlo con el webhook.
2. Activar el cron en la Raspberry.
3. Agregar a la tarea programada de Claude la escritura del guion diario en `guiones/`.
4. Revisar la zona horaria de los perfiles en SocialBee: muestran GMT-05:00 y Ciudad de México
   es GMT-06:00 todo el año.
5. Licencia de SocialBee marcada "cancelling": revisar con soporte. Si se cancela, el flujo se cae
   (usar el plan B).
6. Opcional: borrar videos viejos de `docs/videos/` para que el repositorio no crezca de más
   (~1 MB por video).
