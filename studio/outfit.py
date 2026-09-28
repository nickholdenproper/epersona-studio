"""Outfit reference scanning - shared by the HTTP route and the CLI.

A flat lay / product shot of clothing is described once, then the description
is injected into the main prompt as the outfit. The GUI keeps it on the Studio
singleton; the CLI takes the text explicitly because a one-shot process has no
session to keep it in.
"""
import re

from fastapi import HTTPException

from .config import GPU_OPTIONS
from .ollama import client_for_model, compress_image_b64, resolve_model

MAX_DESCRIPTION_CHARS = 350

OUTFIT_PROMPT = (
    "Focus ONLY on the clothing / outfit / dress visible in this image. "
    "Ignore the person wearing it, the background, and everything else. "
    "Describe the outfit with maximum precision for use in an AI image generation prompt. Cover:\n"
    "- Exact garment type(s)\n- Precise color(s) and any pattern\n- Fabric texture and finish\n"
    "- Fit and silhouette\n- Neckline\n- Sleeves\n- Length\n"
    "- Notable details: cutouts, embroidery, buttons, zippers, belts, ties, ruffles, sequins\n"
    "- Footwear if visible\n- Accessories that are part of the outfit\n"
    "Output as one dense descriptive paragraph with no bullet points or headers."
)


def _tidy(desc):
    """Strip the markdown habits vision models drift into."""
    desc = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', desc)
    desc = re.sub(r'#+\s*[^\n]+\n?', '', desc)
    desc = re.sub(r'^\s*[-\*\u2022]\s*', '', desc, flags=re.MULTILINE)
    desc = re.sub(r'\s+', ' ', desc).strip()
    if len(desc) > MAX_DESCRIPTION_CHARS:
        cut = desc[:MAX_DESCRIPTION_CHARS]
        last_dot = cut.rfind('.')
        desc = cut[:last_dot + 1] if last_dot > 150 else cut.rstrip(',; ')
    return desc


def describe_outfit(studio, image_path):
    """Describe the outfit in `image_path`. Raises ValueError / RuntimeError."""
    if not image_path:
        raise ValueError("No outfit image supplied")

    img_b64 = compress_image_b64(image_path, 896, 85)
    model = resolve_model(studio.selected_model)
    if not model:
        raise RuntimeError(
            f"{studio.selected_model} not found here nor on Ollama Cloud. "
            f"Run: ollama pull {studio.selected_model}"
        )
    cli = client_for_model(model)

    outfit_opts = dict(GPU_OPTIONS)
    outfit_opts['temperature'] = 0.2
    res = cli.generate(model=model, prompt=OUTFIT_PROMPT, images=[img_b64],
                       options=outfit_opts, keep_alive='24h')
    return _tidy((res.get('response') or '').strip())


def describe_outfit_route(studio, image_path):
    """HTTP-facing wrapper: runs the scan in the caller's background job."""
    if not image_path:
        raise HTTPException(400, "No outfit image uploaded")

    def work():
        desc = describe_outfit(studio, image_path)
        studio.outfit_description = desc
        studio.outfit_active = True
        return {'description': desc}

    return work
