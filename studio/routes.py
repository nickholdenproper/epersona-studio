"""FastAPI application — all HTTP endpoints for ePersona Studio.

Routes kept as thin handlers that delegate to the Studio singleton and the
pipeline / tts / inject modules. A few key hygiene fixes compared to the
original single-file server:

- /api/avatar no longer mutates the shared Studio singleton.
- /api/job returns a snapshot under the job lock.
- Settings persistence for templates is forced (immediate).
- Startup lifespan prunes stale uploads.
"""
import base64
import io
import os
import re
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

from . import log
from .caption import write_caption_route
from .config import (BASE_DIR, HAIR_COLOR_PRESETS, HAIRSTYLES,
                     SKIN_TONES, UPLOADS_DIR, UPLOADS_MAX_AGE_DAYS)
from .florence import FLORENCE, florence_available

from .history import append_history, clear_history, list_history
from .inject import inject_prompt
from .ollama import (backend_report, client_for_model, compress_image_b64,
                     list_models, resolve_model)
from .outfit import describe_outfit_route
from .pipeline import (JOBS_LOCK, JOB, refine_prompt_text, run_generation,
                       set_step, start_job)
from .studio import STUDIO
from .tts import tts_transform


logger = log.get_logger(__name__)


def cleanup_uploads(max_age_days=None):
    cutoff = time.time() - (max_age_days or UPLOADS_MAX_AGE_DAYS) * 86400
    if not os.path.isdir(UPLOADS_DIR):
        return
    removed = 0
    for fn in os.listdir(UPLOADS_DIR):
        p = os.path.join(UPLOADS_DIR, fn)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
                removed += 1
        except OSError as e:
            logger.info("[UPLOADS] Failed to remove %s: %s", p, e)
    if removed:
        logger.info("[UPLOADS] Cleaned %d stale upload(s)", removed)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_uploads()
    yield


app = FastAPI(title="ePersona Studio", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, 'static')), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, 'static', 'index.html'))


@app.get("/api/state")
def api_state():
    models = list_models()
    st = STUDIO
    pose_values = ["(None)"] + models
    return {
        'models': models,
        'backend': backend_report(),
        'selected_model': st.selected_model,
        'num_ctx': st.num_ctx,
        'vlm_backend': st.vlm_backend,
        'vlm_backends': st.VLM_BACKENDS,
        'has_cloud_key': bool(st.cloud_api_key),
        'florence_available': florence_available(),

        'pose_values': pose_values,
        'pose_model': st.selected_pose_model or "(None)",
        'hair_base_color': st.hair_base_color,
        'hairstyle': st.hairstyle,
        'hairstyles': list(HAIRSTYLES.keys()),
        'skin_tone': st.skin_tone,
        'skin_tones': list(SKIN_TONES.keys()),
        'sliders': {
            'breast_size': st.breast_size,
            'hip_size': st.hip_size,
            'hair_length': st.hair_length,
            'hair_brightness': st.hair_brightness,
        },
        'opts': {
            'opt_noise': st.opt_noise,
            'opt_dof': st.opt_dof,
            'opt_realism': st.opt_realism,
            'opt_hdr': st.opt_hdr,
            'opt_no_tattoos': st.opt_no_tattoos,
            'opt_naked': st.opt_naked,
            'opt_safe': st.opt_safe,
            'opt_compact': st.opt_compact,
            'use_default_details': st.use_default_details,
        },
        'template_mode': st.prompt_template,
        'templates': sorted(st.templates.keys()),
        'user_notes': st.user_notes,
        'image': {
            'loaded': bool(st.image_path),
            'thumb': st.thumb_dataurl,
            'colors': st.detected_colors,
        },
        'florence_scan': {
            'status': st.florence_scan_status,
            'result': st.florence_scan_result,
        },
        'outfit': {
            'loaded': bool(st.outfit_image_path),
            'active': st.outfit_active,
            'has_description': bool(st.outfit_description),
        },
        'hair_presets': [{'name': n, 'hex': h} for n, h in HAIR_COLOR_PRESETS],
    }


@app.post("/api/settings")
def api_settings(payload: dict):
    STUDIO.apply_updates(payload)
    return {'ok': True}


@app.get("/api/settings/cloud-key")
def api_cloud_key():
    """Return the stored cloud key so the Settings panel can show it.

    Deliberately not part of /api/state: the key is only read when the user
    actually opens the Settings panel, and never on the polling path. The
    server binds to 127.0.0.1 only (see main.py), and the browser's
    same-origin policy stops another site from reading this response.
    """
    return {'key': STUDIO.cloud_api_key, 'has_key': bool(STUDIO.cloud_api_key)}


@app.get("/api/avatar")
def api_avatar(b: int = 50, h: int = 50, l: int = 30, br: int = 100, color: str = "#FFFFFF"):
    breast = max(0, min(100, b))
    hips = max(0, min(100, h))
    hair_len = max(0, min(100, l))
    hair_brightness = max(0, min(100, br))
    hair_color = color.upper() if re.match(r'^#[0-9A-Fa-f]{6}$', color) else STUDIO.hair_base_color
    png = STUDIO.avatar_png(breast=breast, hips=hips, hair_len=hair_len,
                            hair_brightness=hair_brightness, hair_color=hair_color)
    return Response(content=png, media_type='image/png')


@app.post("/api/upload")
def api_upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower() or '.png'
    if ext not in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'):
        raise HTTPException(400, "Unsupported image type")
    save_path = os.path.join(UPLOADS_DIR, f"img_{threading.get_ident()}_{int(time.time())}{ext}")
    with open(save_path, 'wb') as f:
        f.write(file.file.read())

    st = STUDIO
    st.image_path = save_path
    st._vlm_pose_cache.clear()
    st._vlm_clothing_cache.clear()
    st._vlm_env_cache.clear()
    st.last_pose_gt = {}
    st.last_clothing_gt = None
    st.last_env_gt = None
    st.user_notes = ""

    with Image.open(save_path) as img:
        w, hh_ = img.size
        thumb = img.copy()
        thumb.thumbnail((420, 420), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        if thumb.mode in ('RGBA', 'LA', 'P'):
            thumb = thumb.convert('RGB')
        thumb.save(buf, format='JPEG', quality=82)
    st.thumb_dataurl = 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()

    colors = st.extract_colors(save_path)

    # Florence-2 instant scan — run in background so upload stays fast
    if st.vlm_backend == 'Florence-2' and florence_available():

        def _format_florence_result(kind, data):
            if not data:
                return "not detected"
            if isinstance(data, dict):
                vals = [v for v in data.values() if v and str(v).lower() not in ('none', 'n/a', '-')]
                return ', '.join(vals[:3]) if vals else "not detected"
            s = str(data).strip()
            return s[:80] + '...' if len(s) > 80 else s

        def _florence_prescan(path, studio):
            try:
                FLORENCE._ensure_loaded()
                t0 = time.time()

                studio.florence_scan_status = "Loading Florence-2 model..."
                studio.florence_scan_result = None

                pose = studio._florence_scan_pose(path)
                if pose:
                    studio._vlm_pose_cache[f"{path}|florence2-pose"] = pose
                studio.last_pose_gt = {'vlm': pose, 'mp': None}
                pose_preview = _format_florence_result('Pose', pose)
                studio.florence_scan_status = f"Pose: {pose_preview}"

                cloth = studio._florence_scan_clothing(path)
                if cloth:
                    studio._vlm_clothing_cache[f"{path}|florence2-cl"] = cloth
                studio.last_clothing_gt = cloth
                cl_preview = _format_florence_result('Clothing', cloth)
                studio.florence_scan_status += f"\nClothing: {cl_preview}"

                env = studio._florence_scan_env(path)
                if env:
                    studio._vlm_env_cache[f"{path}|florence2-env"] = env
                studio.last_env_gt = env
                env_preview = _format_florence_result('Environment', env)
                studio.florence_scan_status += f"\nEnvironment: {env_preview}"

                elapsed = time.time() - t0
                studio.florence_scan_result = {
                    'pose': pose, 'clothing': cloth, 'environment': env,
                    'elapsed': round(elapsed, 1),
                }
                studio.florence_scan_status = f"Scan complete ({elapsed:.1f}s)"
                logger.info("[FLORENCE] Pre-scan done in %.1fs — pose=%s cloth=%s env=%s",
                            elapsed, bool(pose), bool(cloth), bool(env))
            except Exception as e:
                studio.florence_scan_status = f"Scan failed: {e}"
                logger.info("[FLORENCE] Pre-scan failed: %s", e)

        threading.Thread(target=_florence_prescan, args=(save_path, st), daemon=True).start()

    return {
        'thumb': st.thumb_dataurl,
        'width': w,
        'height': hh_,
        'colors': colors,
    }


@app.post("/api/generate")
def api_generate():
    if not STUDIO.image_path:
        raise HTTPException(400, "No image loaded")
    STUDIO.flush_settings()
    start_job('generate', run_generation)
    return {'started': True}


@app.get("/api/job")
def api_job():
    with JOBS_LOCK:
        return dict(JOB)


@app.post("/api/finalize")
def api_finalize(payload: dict):
    text = (payload.get('text') or '').strip()
    if not text:
        raise HTTPException(400, "No prompt to finalize")

    def work():
        set_step("Finalizing (focus & consistency)...")
        model = resolve_model(STUDIO.selected_model)
        if not model:
            return {'prompt': text}
        polished, status = refine_prompt_text(client_for_model(model), model, text)
        if status != 'ok':
            logger.info("[FINAL] kept original (%s)", status)
        return {'prompt': polished}

    start_job('finalize', work)
    return {'started': True}


# ---------------- outfit ----------------
@app.post("/api/outfit/upload")
def api_outfit_upload(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower() or '.png'
    save_path = os.path.join(UPLOADS_DIR, f"outfit_{threading.get_ident()}_{int(time.time())}{ext}")
    with open(save_path, 'wb') as f:
        f.write(file.file.read())
    st = STUDIO
    st.outfit_image_path = save_path
    st.outfit_description = ""
    st.outfit_active = False
    with Image.open(save_path) as img:
        thumb = img.copy()
        thumb.thumbnail((300, 120), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        if thumb.mode in ('RGBA', 'LA', 'P'):
            thumb = thumb.convert('RGB')
        thumb.save(buf, format='JPEG', quality=82)
    return {'thumb': 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()}


@app.post("/api/outfit/scan")
def api_outfit_scan():
    st = STUDIO
    if not st.outfit_image_path:
        raise HTTPException(400, "No outfit image uploaded")
    start_job('outfit_scan', describe_outfit_route(st, st.outfit_image_path))
    return {'started': True}



@app.post("/api/outfit/clear")
def api_outfit_clear():
    st = STUDIO
    st.outfit_image_path = None
    st.outfit_description = ""
    st.outfit_active = False
    return {'ok': True}


# ---------------- TTS mode ----------------
@app.post("/api/tts")
def api_tts(payload: dict):
    raw = (payload.get('text') or '').strip()
    if not raw:
        raise HTTPException(400, "Paste a prompt first")
    res = tts_transform(STUDIO, raw)
    append_history('tts', res.get('result'), STUDIO.prompt_template)
    return res


# ---------------- Prompt injection ----------------
@app.post("/api/inject")
def api_inject(payload: dict):
    raw = (payload.get('text') or '').strip()
    model = resolve_model(STUDIO.selected_model)
    res = inject_prompt(STUDIO, client_for_model(model) if model else None, raw, model=model)
    append_history('inject', res.get('result'), STUDIO.prompt_template)
    return res


# ---------------- Prompt history ----------------
@app.get("/api/history")
def api_history():
    return {'items': list_history(50)}


@app.delete("/api/history")
def api_history_clear():
    clear_history()
    return {'ok': True}


# ---------------- templates ----------------
TEMPLATE_FIELDS = ['breast_size', 'hip_size', 'hair_length', 'hair_brightness',
                   'opt_noise', 'opt_dof', 'opt_realism', 'opt_hdr',
                   'opt_no_tattoos', 'opt_naked', 'opt_safe', 'opt_compact',
                   'use_default_details']


@app.post("/api/templates/save")
def api_templates_save(payload: dict):
    name = (payload.get('name') or '').strip()
    if not name:
        raise HTTPException(400, "Template name required")
    st = STUDIO
    tmpl = {f: getattr(st, f) for f in TEMPLATE_FIELDS}
    tmpl['prompt_template'] = st.prompt_template
    tmpl['hair_base_color'] = st.hair_base_color
    tmpl['hairstyle'] = st.hairstyle
    tmpl['skin_tone'] = st.skin_tone
    st.templates[name] = tmpl
    st.save_settings()
    return {'ok': True, 'templates': sorted(st.templates.keys())}


@app.post("/api/templates/load/{name}")
def api_templates_load(name: str):
    st = STUDIO
    if name not in st.templates:
        raise HTTPException(404, "Template not found")
    st.apply_updates(st.templates[name])
    return {'ok': True}


@app.delete("/api/templates/delete/{name}")
def api_templates_delete(name: str):
    st = STUDIO
    if name not in st.templates:
        raise HTTPException(404, "Template not found")
    del st.templates[name]
    st.save_settings()
    return {'ok': True, 'templates': sorted(st.templates.keys())}


# ========== Twitter Caption ==========
TWITTER_IMAGE_PATH = None


@app.post("/api/twitter/upload")
async def api_twitter_upload(file: UploadFile = File(...)):
    global TWITTER_IMAGE_PATH
    ext = os.path.splitext(file.filename or 'img.png')[1].lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'):
        raise HTTPException(400, "Unsupported image format")
    tid = id(STUDIO)
    ts = int(time.time() * 1000)
    path = os.path.join(UPLOADS_DIR, f'twitter_{tid}_{ts}{ext}')
    raw = await file.read()
    with open(path, 'wb') as f:
        f.write(raw)
    TWITTER_IMAGE_PATH = path
    # Build thumbnail
    thumb_b64 = compress_image_b64(path, size=800, quality=85)
    thumb_url = f"data:image/jpeg;base64,{thumb_b64}"
    return {'ok': True, 'thumb': thumb_url}


@app.post("/api/twitter-caption")
def api_twitter_caption(payload: dict = None):
    if payload is None:
        payload = {}
    if not TWITTER_IMAGE_PATH or not os.path.exists(TWITTER_IMAGE_PATH):
        raise HTTPException(400, "Upload an image first")
    return write_caption_route(STUDIO, TWITTER_IMAGE_PATH,
                               payload.get('vibe'), payload.get('length'))



