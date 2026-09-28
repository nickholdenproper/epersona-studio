"""Job orchestration and the two-track generation pipeline.

Module-level job state (shared with the routes) plus run_generation,
refine_prompt_text and their helpers.
"""
import threading

from fastapi import HTTPException

from . import log
from .config import GPU_OPTIONS
from .florence import FLORENCE
from .history import append_history
from .ollama import client_for_model, resolve_model
from .ollama import compress_image_b64, hex_codes as _hex_codes
from .studio import STUDIO

logger = log.get_logger(__name__)

JOBS_LOCK = threading.Lock()
JOB = {'running': False, 'kind': None, 'step': '', 'error': None, 'result': None}

# Optional progress sink. The GUI polls /api/job instead, so it leaves this as
# None; the CLI sets it to print each step to stderr. Same module-level style as
# JOB, and a misbehaving sink can never break a generation.
STEP_HOOK = None


def start_job(kind, fn):
    with JOBS_LOCK:
        if JOB['running']:
            raise HTTPException(409, "Another job is already running")
        JOB.update(running=True, kind=kind, step="Starting...", error=None, result=None)

    def wrap():
        try:
            result = fn()
            with JOBS_LOCK:
                JOB['result'] = result
            if isinstance(result, dict) and result.get('prompt'):
                append_history(kind, result['prompt'], STUDIO.prompt_template)
        except Exception as e:
            logger.error("[JOB %s] ERROR: %s", kind, e)
            with JOBS_LOCK:
                JOB['error'] = str(e)
        finally:
            with JOBS_LOCK:
                JOB['running'] = False

    threading.Thread(target=wrap, daemon=True).start()


def set_step(step):
    with JOBS_LOCK:
        JOB['step'] = step
    hook = STEP_HOOK
    if hook is not None:
        try:
            hook(step)
        except Exception as e:
            logger.debug("[PIPELINE] step hook failed: %s", e)


REFINE_NOTE = (
    "You are polishing an AI image-generation prompt. Rewrite it ONCE, following these rules EXACTLY:\n"
    "1. PROMOTE FOCUS: image models attend most to the start of the prompt. Move the most important "
    "fixed attributes — her exact hair color WITH its hex code, her body shape/measurements, and the "
    "pose description — into the FIRST 2-3 sentences. Also KEEP every closing lock line "
    "('LOCKED...', '[Pose Lock]', '[Hair Lock]') and every inline hair-lock phrase such as "
    "'strictly <color> (<hex>)' or 'no other color anywhere' word-for-word.\n"
    "2. POSE IS SACRED: every positional, angular or directional statement (degrees, left/right, "
    "toward/away from camera, contact points) must be copied VERBATIM — never reworded, shortened, "
    "merged or 'simplified'. If two pose statements conflict, keep the one from the GROUND TRUTH/"
    "verification sections and delete only the contradicting words.\n"
    "3. REMOVE OTHER CONTRADICTIONS: for non-pose attributes (hair length/color/style, clothing "
    "described while she is also naked, conflicting environment or lighting details), keep the value "
    "stated in the LOCKED/custom/latest section and delete only the few outdated words.\n"
    "4. PRESERVE DATA: never change, round, merge or drop ANY number, degree symbol, measurement, "
    "color name, fabric, garment or hex code. Every hex code in the input MUST appear in your output.\n"
    "5. PRESERVE ENHANCEMENTS: keep every style/technical phrase verbatim — 'film grain', 'shallow depth "
    "of field', 'cinematic photoreal', 'HDR' / 'high-contrast', 'visible pores', 'realistic skin "
    "imperfections', 'tattoo-free', 'natural film grain'. Do NOT shorten, paraphrase or drop these.\n"
    "6. Do NOT invent anything new. Do NOT summarize. Only removals allowed: exact duplicate phrases "
    "and contradicted values per rules 2-3.\n"
    "7. Keep any 'HEX VALUES:' block byte-for-byte at the end.\n"
    "8. Output ONLY the rewritten prompt — no commentary."
)


def refine_prompt_text(client_, model, text):
    """LLM polish pass: reorder for focus + strip contradictions. Returns (text, status);
    returns the ORIGINAL text untouched whenever the output fails a safety guard."""
    instruction = REFINE_NOTE + f"\n\nPROMPT:\n{text}"
    opts = dict(GPU_OPTIONS)
    opts['num_ctx'] = max(GPU_OPTIONS.get('num_ctx', 8192), 8192)
    opts['temperature'] = 0.2
    opts['num_predict'] = max(1024, len(text) // 2 + 384)
    res = client_.generate(model=model, prompt=instruction, options=opts, keep_alive='24h')
    out = (res.get('response') or '').strip()
    if not out:
        return text, 'empty-response'
    if len(out) < len(text) * 0.55:
        return text, f'too-short ({len(out)} < {int(len(text)*0.55)})'
    missing = [h for h in _hex_codes(text) if h.lower() not in out.lower()]
    if missing:
        return text, f'dropped-hex {missing}'
    return out, 'ok'


def run_generation(studio=None):
    """Two-track pipeline:
    - Track A (pose model set): specialist scans own pose/clothing/env at high precision;
      main model only handles face, mood, skin, age, props — no contradictions possible.
    - Track B (no pose model): main model analyzes everything (original behaviour).

    `studio` is injectable so the CLI can drive its own instance; the HTTP layer
    and anything else pass nothing and get the shared singleton.
    """
    st = studio or STUDIO
    if not st.image_path:
        raise Exception("No image loaded")

    set_step("Compressing image...")
    img_b64 = compress_image_b64(st.image_path)

    # ---- Florence-2 backend: scan image only, then hand off to Ollama ----
    if st.vlm_backend == 'Florence-2':
        logger.info("[PIPELINE] Florence-2 scans → Ollama writes prompt")
        try:
            FLORENCE._ensure_loaded()
        except Exception as e:
            raise Exception(f"Florence-2 not available: {e}")

        # Pose scan
        florence_pose_key = f"{st.image_path}|florence2-pose"
        if florence_pose_key in st._vlm_pose_cache:
            vlm_pose = st._vlm_pose_cache[florence_pose_key]
            set_step("Pose scan (cached)")
        else:
            set_step("Pose/action scan with Florence-2...")
            vlm_pose = st._florence_scan_pose(st.image_path)
            if vlm_pose:
                st._vlm_pose_cache[florence_pose_key] = vlm_pose
        st.last_pose_gt = {'vlm': vlm_pose, 'mp': None}

        # Clothing scan
        cloth_gt = None
        florence_cl_key = f"{st.image_path}|florence2-cl"
        if florence_cl_key in st._vlm_clothing_cache:
            cloth_gt = st._vlm_clothing_cache[florence_cl_key]
            set_step("Clothing scan (cached)")
        else:
            set_step("Clothing scan with Florence-2...")
            cloth_gt = st._florence_scan_clothing(st.image_path)
            if cloth_gt:
                st._vlm_clothing_cache[florence_cl_key] = cloth_gt
        st.last_clothing_gt = cloth_gt

        # Environment scan
        env_gt = None
        florence_env_key = f"{st.image_path}|florence2-env"
        if florence_env_key in st._vlm_env_cache:
            env_gt = st._vlm_env_cache[florence_env_key]
            set_step("Environment scan (cached)")
        else:
            set_step("Environment scan with Florence-2...")
            env_gt = st._florence_scan_env(st.image_path)
            if env_gt:
                st._vlm_env_cache[florence_env_key] = env_gt
        st.last_env_gt = env_gt

        specialist_covered = bool(vlm_pose or cloth_gt or env_gt)

        # Fall through to Ollama below — it reads st.last_pose_gt / last_clothing_gt / last_env_gt
        # and uses them as ground truth in the focused prompt.

    # ---- Ollama backend path (default) ----
    logger.info("[PIPELINE] Using Ollama backend")

    # ---- Specialist scans ----
    # When Florence-2 backend: scans already done above, pull from state.
    # When Ollama backend: run Ollama specialist scans now.
    vlm_pose = None
    cloth_gt = None
    env_gt = None
    pm = st.selected_pose_model

    if st.vlm_backend == 'Florence-2':
        # Florence-2 already populated st.last_pose_gt / last_clothing_gt / last_env_gt
        vlm_pose = (st.last_pose_gt or {}).get('vlm')
        cloth_gt = st.last_clothing_gt
        env_gt = st.last_env_gt
        specialist_covered = bool(vlm_pose or cloth_gt or env_gt)
        logger.info("[PIPELINE] Florence-2 data: pose=%s cloth=%s env=%s",
                    bool(vlm_pose), bool(cloth_gt), bool(env_gt))
    else:
        # Ollama specialist scans (original behaviour)
        if pm:
            cache_key = f"{st.image_path}|{pm}"
            if cache_key in st._vlm_pose_cache:
                vlm_pose = st._vlm_pose_cache[cache_key]
                set_step("Pose scan (cached)")
            else:
                set_step(f"Pose/action scan with {pm}...")
                vlm_pose = st._scan_pose_with_vlm(img_b64, [])
                if vlm_pose:
                    st._vlm_pose_cache[cache_key] = vlm_pose

        st.last_pose_gt = {'vlm': vlm_pose, 'mp': None}

        if pm:
            ckey = f"{st.image_path}|{pm}"
            if ckey in st._vlm_clothing_cache:
                cloth_gt = st._vlm_clothing_cache[ckey]
                set_step("Clothing scan (cached)")
            else:
                set_step(f"Exact clothing scan with {pm}...")
                cloth_gt = st._scan_clothing_with_vlm(img_b64)
                if cloth_gt:
                    st._vlm_clothing_cache[ckey] = cloth_gt
        st.last_clothing_gt = cloth_gt

        if pm:
            ekey = f"{st.image_path}|{pm}"
            if ekey in st._vlm_env_cache:
                env_gt = st._vlm_env_cache[ekey]
                set_step("Environment scan (cached)")
            else:
                set_step(f"Environment & lighting scan with {pm}...")
                env_gt = st._scan_env_with_vlm(img_b64)
                if env_gt:
                    st._vlm_env_cache[ekey] = env_gt
        st.last_env_gt = env_gt

        specialist_covered = bool(pm and (vlm_pose or cloth_gt or env_gt))

    model = resolve_model(st.selected_model)
    if not model:
        raise Exception(
            f"{st.selected_model} not found locally nor on Ollama Cloud. "
            f"Run: ollama pull {st.selected_model}"
        )
    cli = client_for_model(model)

    gen_opts = dict(GPU_OPTIONS)
    gen_opts['num_ctx'] = max(gen_opts.get('num_ctx', 8192), 8192)
    gen_opts['temperature'] = 0.2
    gen_opts['top_p'] = 0.8

    notes_block = ""
    if (st.user_notes or '').strip():
        notes_block = (
            "USER NOTES — HIGHEST PRIORITY. Treat as absolute ground truth:\n"
            + "\n".join(f"- {ln.strip()}" for ln in st.user_notes.strip().splitlines() if ln.strip())
            + "\n\n"
        )

    if specialist_covered:
        # ---- Track A: specialist scans captured some sections at high precision ----
        # Build an adaptive prompt that only asks the main model for what was NOT captured.
        _sp_pose = bool(vlm_pose)
        _sp_cloth = bool(cloth_gt) or bool(st.outfit_active and st.outfit_description)
        _sp_env = bool(env_gt)

        # Tell the model what is already done so it doesn't re-do those sections
        _already = [x for x, ok in [
            ("body pose/orientation/arms/legs", _sp_pose),
            ("clothing & accessories", _sp_cloth),
            ("environment & lighting", _sp_env),
        ] if ok]
        _already_str = ("Already captured by dedicated specialist scans (DO NOT repeat these): "
                        + "; ".join(_already) + ".\n") if _already else ""

        # Always ask main model for the 5 things only it can see
        focused_sections = (
            "FACIAL_FEATURES: face shape, eye shape/color, nose, lips, cheekbones. "
            "If face is not visible write exactly: face not visible from this angle\n"
            "SKIN_DETAILS: skin tone, texture, visible freckles/moles/marks, finish (matte/dewy)\n"
            "MOOD: emotional atmosphere in one short phrase\n"
            "SUBJECT_AGE: estimated age range (e.g. mid-20s) with brief visual evidence\n"
            "PROPS_OBJECTS: objects she holds or immediately beside her; 'none' if none\n"
        )

        # Fallback sections — only ask if specialist scan returned nothing
        if not _sp_cloth:
            focused_sections += (
                "CLOTHING: each garment — exact type, PRECISE color name "
                "(e.g. ivory / charcoal / navy not white/black/blue), fabric, fit, neckline, "
                "sleeves. Separate footwear and accessories.\n"
            )
        if not _sp_env:
            focused_sections += (
                "ENVIRONMENT: indoor/outdoor, floor, walls, furniture, background depth\n"
                "LIGHTING: source count/type, direction, quality (hard/soft), color temperature\n"
            )
        if not _sp_pose:
            focused_sections += (
                "SHOT_ANGLE: camera height (low/eye-level/high), shot distance (close-up/medium/full body)\n"
                "WOMAN_POSITION: stance, body orientation relative to camera, arm positions, leg positions\n"
                "ACTION_ACTIVITY: what she is specifically doing right now\n"
            )

        _need_extra = not (_sp_cloth and _sp_env and _sp_pose)
        set_step(f"Face & detail scan with {model}...")
        focused_prompt = notes_block + _already_str + (
            "Analyze ONLY the labeled sections below from this image.\n"
            "Use EXACTLY these labeled sections, one per line:\n\n"
            + focused_sections
            + "\nRULES: Only what is clearly VISIBLE. Precise short answers. No markdown. No inventing."
        )
        gen_opts['num_predict'] = 500 if _need_extra else 350
        res = cli.generate(model=model, prompt=focused_prompt, images=[img_b64],
                           options=gen_opts, keep_alive='24h')
        description = res['response']
        logger.info("[GEN ] Focused description (%d chars) | fallback: cloth=%s env=%s pose=%s",
                    len(description), not _sp_cloth, not _sp_env, not _sp_pose)
    else:
        # ---- Track B: no specialist data — main model analyzes everything ----
        set_step(f"Main analysis with {model}...")
        pose_prefix = st._build_pose_prefix(vlm_pose, pm or 'vision model')
        prompt = pose_prefix + notes_block + """Analyze this image. Use EXACTLY these section labels:

SHOT_ANGLE: camera angle (degrees left/right, height relative to subject), distance/framing, lens effect.
WOMAN_POSITION: stance (standing/sitting/lying/kneeling), spinal alignment, torso lean, head/gaze direction, shoulder/arm/hand/leg positions.
ACTION_ACTIVITY: exactly what she is doing right now — the specific action or gesture. If posing still, state precisely which pose.
FACIAL_FEATURES: face shape, eye shape/color, nose, lips, cheekbones. IF face NOT VISIBLE write: face not visible from this angle
CLOTHING: each garment — type, EXACT color name, pattern, fabric, fit, neckline, sleeves, details, footwear, jewelry.
ENVIRONMENT: indoor/outdoor, floor, walls, furniture, textiles, windows, background depth.
PROPS_OBJECTS: objects held or nearby — type, color, position.
LIGHTING: number/type of sources, direction, quality (hard/soft), color temp, shadows.
SKIN_DETAILS: tone, texture, freckles, moles, finish.
MOOD: emotional atmosphere (1 sentence).
SUBJECT_AGE: narrow age range with visual evidence.

RULES: Describe only what is VISIBLE. EXACT clothing colors. Skip hair/body measurements."""
        res = cli.generate(model=model, prompt=prompt, images=[img_b64],
                           options=gen_opts, keep_alive='24h')
        description = res['response']
        logger.info("[GEN ] Description received (%d chars)", len(description))

    set_step("Building final prompt...")
    colors = st.extract_colors()
    final_prompt = st.build_advanced_prompt(description, {}, colors)
    logger.info("[GEN ] Final prompt: %d chars", len(final_prompt))
    return {'prompt': final_prompt, 'description': description}