"""Prompt Injector — rewrite an external prompt with Body Studio settings.

Pure function taking the Studio state object and an Ollama client, so the
LLM-touching logic can be unit-tested with a stubbed client.
"""
import json
import math
import re

from fastapi import HTTPException

from .config import GPU_OPTIONS, hairstyle_phrase, SKIN_TONES, SKIN_TONE_DEFAULT
from .text import body_parts

# --- script-level category keywords used as a fallback when the LLM-reported ---
# --- spans are paraphrased, partial, or the LLM returns unparseable output. ---
HAIR_KW = re.compile(
    r'(?i)\b(hair(?:line|style)?|locks|strands|tresses|braids?|ponytails?|buns?|'
    r'bangs|fringes?|curls?|extensions|wigs?|manes?)\b'
)
BODY_KW = re.compile(
    r'(?i)\b(body|torso|hips?|breasts?|curves?|thighs?|cleavage|busty|hourglass|'
    r'petite|voluptuous|physique|silhouette)\b'
)
BODY_SAFETY_KW = re.compile(
    r'(?i)\b(body|torso|hips?|breasts?|waist|figure|curves?|thighs?|cleavage|'
    r'busty|hourglass|petite|voluptuous)\b'
)
SKIN_KW = re.compile(r'(?i)\b(skin|complexion|porcelain|freckles?)\b')
CLOTHING_KW = re.compile(
    r'(?i)\b(clad in|wearing|dressed in|outfits?|bikini|dresses?|tops?|shirts?|'
    r'shorts|panties|lingerie|garments?|fabrics?|swimsuits?|bodysuits?|jeans|'
    r'jackets?|skirts?|boots?|heels?|blouses?|gowns?|robes?|coats?)\b'
)


def _parse_identified(output):
    """Parse the LLM's JSON response as leniently as possible."""
    output = (output or '').strip()
    output = re.sub(r'^```[a-zA-Z]*\n?', '', output)
    output = re.sub(r'\n?```$', '', output)
    data = {}
    candidates = [output]
    m = re.search(r'\{[\s\S]*\}', output)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            parsed = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            data = parsed
            break
    cleaned = {}
    for key in ('hair', 'body', 'skin', 'clothing', 'style'):
        val = data.get(key)
        if isinstance(val, str) and val.strip().lower() in ('null', 'none'):
            val = None
        elif not isinstance(val, str) or not val.strip():
            val = None
        cleaned[key] = val
    return cleaned


def _span_replace(text, old_text, new_text):
    """Replace an LLM-reported span, falling back to punctuation-trimmed variants."""
    if not old_text:
        return text, False
    variants = [old_text.strip()]
    trimmed = re.sub(r'^[^A-Za-z]+|[^A-Za-z]+$', '', old_text.strip())
    if trimmed and trimmed.lower() != variants[0].lower():
        variants.append(trimmed)
    for variant in variants:
        if not variant:
            continue
        candidate = re.sub(re.escape(variant), new_text or '', text, count=1, flags=re.IGNORECASE)
        if candidate != text:
            return candidate, True
    return text, False


def _strip_sentences(text, kw_regex):
    """Remove whole sentences (incl. an unterminated trailing one) that match kw_regex."""
    parts = re.split(r'(?<=[.!?])\s+', text or '')
    kept = [p.strip() for p in parts if p.strip() and not kw_regex.search(p)]
    cleaned = ' '.join(kept)
    cleaned = re.sub(r'\s*,\s*,', ',', cleaned)
    return cleaned.strip(' ,')


def inject_prompt(studio, client_, raw, model=None):
    if not raw:
        raise HTTPException(400, "Paste a base prompt first")

    st = studio

    # --- Clean trailing junk from input ---
    hex_match = re.search(r'HEX VALUES:\s*\[[^\]]*\]', raw, re.IGNORECASE)
    raw_prompt = raw[:hex_match.start()].strip() if hex_match else raw
    raw_prompt = re.sub(r'\bHAIR:\s*strictly\s+[^.]+\.', '', raw_prompt, flags=re.IGNORECASE).strip()
    raw_prompt = re.sub(r'\bPOSE:\s*[^.]+\.', '', raw_prompt, flags=re.IGNORECASE).strip()

    # --- Compute target values from Body Studio ---
    lock_name, lock_hex = st.hair_lock_parts()

    bp = st.HAIR_BREAKPOINTS
    sv = st.hair_length
    cut_label, cut_inches, cut_landmark = bp[0][2], bp[0][1], bp[0][3]
    for i in range(len(bp) - 1):
        lo, hi = bp[i], bp[i + 1]
        if lo[0] <= sv <= hi[0]:
            t = (sv - lo[0]) / (hi[0] - lo[0])
            cut_label = lo[2] if t < 0.5 else hi[2]
            cut_inches = round(lo[1] + t * (hi[1] - lo[1]), 1)
            cut_landmark = lo[3] if t < 0.5 else hi[3]
            break
    target_hair = (
        f"{lock_name} (hex {lock_hex}), "
        f"{cut_label} ({cut_inches} inches, {cut_landmark}), "
        f"{hairstyle_phrase(st.hairstyle, st.hair_length)}"
    )

    breast_desc, hip_desc, figure_label = body_parts(
        st.breast_size, st.hip_size, st.opt_safe)
    target_body = (
        f"{figure_label} figure — {breast_desc}, a defined cinched waist, "
        f"{hip_desc}, rounded backside, and thicker thighs"
    )

    target_skin = SKIN_TONES.get(st.skin_tone, SKIN_TONE_DEFAULT)
    if " with " in target_skin:
        target_skin = target_skin.split(" with ")[0]
    if st.opt_no_tattoos:
        target_skin += ", completely tattoo-free"
    if st.opt_realism:
        target_skin += ", with visible pores and natural skin texture"

    target_naked = ""
    if st.opt_naked:
        if st.opt_safe:
            target_naked = (
                "She is dressed in minimal, form-fitting clothing — a fitted "
                "crop-top and shorts with her arms, shoulders, and midriff bare."
            )
        else:
            target_naked = (
                "She is completely naked — no clothing, no fabric, no coverings "
                "of any kind, her bare skin fully exposed."
            )

    # Clothing target priority: naked → outfit scan → clothing specialist scan.
    target_clothing = ""
    if not target_naked:
        if st.outfit_active and (st.outfit_description or '').strip():
            target_clothing = st.outfit_description.strip()
        elif st.last_clothing_gt:
            target_clothing = st._compose_clothing_text(st.last_clothing_gt).strip()

    # --- Step 1: LLM identifies existing hair/body/skin/clothing/style sentences ---
    identify_prompt = (
        "Read the image generation prompt below.\n"
        "Find every part that describes: hair, body, skin, clothing, or photographic style/enhancements.\n"
        "Return a JSON object with these keys and the EXACT spans copied VERBATIM (character-for-character, punctuation included) from the prompt:\n"
        "{\n"
        '  "hair": "exact text about hair",\n'
        '  "body": "exact text about body shape/proportions (ONLY if body/torso/hips/breasts are explicitly described — return null for head shots, portraits, or any prompt that does not mention body proportions)",\n'
        '  "skin": "exact text about skin tone/complexion",\n'
        '  "clothing": "exact text about what she is wearing",\n'
        '  "style": "exact text about photo quality/enhancements"\n'
        "}\n"
        "Use null for any category not present in the prompt.\n"
        "IMPORTANT: For 'body', only extract it if the prompt explicitly describes body shape, proportions, figure, breasts, hips, waist, or similar. Head shots, face close-ups, or any prompt without body description MUST have body as null.\n"
        "Return ONLY valid JSON — no markdown, no explanation.\n\n"
        f"PROMPT:\n{raw_prompt}"
    )

    try:
        ml = client_.list()
        available = [m.model for m in ml.models] if hasattr(ml, 'models') else []
    except Exception as e:
        raise HTTPException(500, f"Ollama unreachable: {e}")

    model = model or st.selected_model
    if model not in available:
        model = available[0] if available else None
    if not model:
        raise HTTPException(500, "No Ollama models available")

    opts = dict(GPU_OPTIONS)
    opts['temperature'] = 0.0
    opts['num_predict'] = 256

    try:
        res = client_.generate(model=model, prompt=identify_prompt, options=opts, keep_alive='24h')
        llm_output = res['response'].strip()
    except Exception as e:
        raise HTTPException(500, f"LLM identification failed: {e}")

    # Parse LLM JSON response (leniently — also handles prose-wrapped output)
    identified = _parse_identified(llm_output)

    # --- Step 2: replacement ---
    result = raw_prompt

    # Safety: if the original prompt has no body-related words, discard any LLM body match
    if not BODY_SAFETY_KW.search(raw_prompt):
        identified['body'] = None

    replaced_keys = set()

    # Step 2a — exact/tolerant LLM-span replacements. These fire when the LLM
    # returns a verbatim (or near-verbatim) span.
    if identified.get('hair'):
        result, _ = _span_replace(result, identified['hair'], '')

    replacements = {
        'body': target_body,
        'skin': target_skin,
        'clothing': target_naked if target_naked else (target_clothing or None),
    }
    for key, target in replacements.items():
        old_text = identified.get(key)
        if not old_text or not target:
            continue
        candidate, ok = _span_replace(result, old_text, target)
        if ok:
            result = candidate
            replaced_keys.add(key)

    # Step 2b — script-level sentence cleanup for categories the LLM did not
    # replace. This guarantees the old hair/body/skin/clothing text is removed
    # even when the LLM paraphrased the span or returned unparseable output.
    # Runs before the fixed lead is prepended, so the injected values are safe.
    strip_keywords = {
        'hair': HAIR_KW, 'body': BODY_KW, 'skin': SKIN_KW, 'clothing': CLOTHING_KW,
    }
    for key in ('hair', 'body', 'skin', 'clothing'):
        if key in replaced_keys:
            continue
        stripped = _strip_sentences(result, strip_keywords[key])
        if stripped != result:
            result = stripped

    result = re.sub(r'\s*,\s*,', ',', result)
    result = re.sub(r'\s{2,}', ' ', result).strip(' ,')

    # --- Step 3: Always inject the Body Studio values (fixed attributes lead) ---
    # Even if the pasted prompt had no body/skin span (head shot, torso-only) or
    # the LLM could not locate one, the current settings must still appear.
    fixed_lead = [target_hair]
    for key in ('body', 'skin', 'clothing'):
        target = replacements.get(key)
        if target and key not in replaced_keys and target.lower() not in result.lower():
            fixed_lead.append(target)
    result = f"{'. '.join(fixed_lead)}. {result.lstrip()}"

    # --- Step 4: Inject enhancement tags (script, not LLM) ---
    enhancement_parts = []
    if st.opt_noise:
        enhancement_parts.append("natural film grain")
    if st.opt_dof:
        enhancement_parts.append("shallow depth of field")
    if st.opt_hdr:
        enhancement_parts.append("high dynamic range, high-key dramatic studio lighting")
    enhancement_parts.append("cinematic photo")

    style_inject = f"The image has {', '.join(enhancement_parts)}."
    if style_inject.lower() not in result.lower():
        result = result.rstrip() + " " + style_inject

    # Naked mode: strip any remaining clothing sentences if override is active
    if target_naked:
        clothing_kw = re.compile(
            r'(?i)(clad in|wearing|dressed in|outfit|bikini|top|dress|shirt|shorts|'
            r'panties|lingerie|garment|fabric covering|swimsuit|bodysuit)[^.]*\.'
        )
        result = clothing_kw.sub(target_naked, result)

    # --- Step 5: LLM grammar check (only fix grammar, nothing else) ---
    grammar_prompt = (
        "Fix any grammar, spelling, or punctuation errors in this prompt. "
        "Do NOT change any words, descriptions, or meaning. "
        "Do NOT add or remove any content. "
        "Keep the sentences about her hair, body figure, skin, and clothing exactly as written; "
        "only correct unrelated grammar, spelling, or punctuation. "
        "Return the corrected text only, nothing else.\n\n"
        f"{result}"
    )

    opts['num_predict'] = 1024
    try:
        res = client_.generate(model=model, prompt=grammar_prompt, options=opts, keep_alive='24h')
        grammar_result = res['response'].strip()
        grammar_result = re.sub(r'^```[a-zA-Z]*\n?', '', grammar_result)
        grammar_result = re.sub(r'\n?```$', '', grammar_result)
        if grammar_result:
            # Guard: never let the grammar model drop the injected Body Studio values.
            locked = [s for s in fixed_lead if s.strip()]
            missing = [s.lower() for s in locked if s.lower() not in grammar_result.lower()]
            if not missing:
                result = grammar_result
    except Exception:
        pass

    # --- Step 6: Append HEX palette ---

    input_hexes = re.findall(r'#[0-9a-fA-F]{6}', raw)
    palette = []

    def _rgb(hx):
        hx = hx.upper()
        return (int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16))

    l_rgb = _rgb(lock_hex)
    source_colors = input_hexes if input_hexes else st.extract_colors()
    if source_colors:
        for c in source_colors:
            c_up = c.upper()
            try:
                c_rgb = _rgb(c_up)
                if math.sqrt((c_rgb[0] - l_rgb[0])**2 + (c_rgb[1] - l_rgb[1])**2
                             + (c_rgb[2] - l_rgb[2])**2) >= 60:
                    if c_up not in palette:
                        palette.append(c_up)
            except Exception:
                if c_up not in palette:
                    palette.append(c_up)

    if lock_hex.upper() not in palette:
        palette.append(lock_hex.upper())
    if palette:
        formatted_hex = [f'"{c}"' for c in palette[:14]]
        result += f"\n\nHEX VALUES: [{', '.join(formatted_hex)}]"

    return {'result': result}