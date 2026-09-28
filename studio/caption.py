"""Twitter/X caption writer - shared by the HTTP route and the CLI.

Extracted from routes.py so `studio caption` and the browser produce identical
captions instead of two copies of the same prompt drifting apart.
"""
from fastapi import HTTPException

from .config import GPU_OPTIONS
from .ollama import compress_image_b64, client_for_model, resolve_model

VIBE_PROMPTS = {
    'casual': 'Write in a relaxed, everyday conversational tone — like you are just chatting with friends.',
    'simple': 'Keep it minimal and clean — short words, no fluff, just pure vibes.',
    'sexy': 'Make it sultry, bold, and alluring — confident energy that turns heads.',
    'flirty': 'Write in a playful, teasing tone — fun, charming, and a little suggestive.',
    'mysterious': 'Keep it vague and intriguing — make people curious enough to look twice.',
    'funny': 'Make it witty and humorous — a clever joke, pun, or playful roast.',
    'hype': 'Go full energy, all caps allowed, maximum excitement — like you are shouting it from a rooftop.',
    'professional': 'Write in a polished, brand-friendly tone — clean, sleek, and marketable.',
}

LENGTH_RULES = {
    'short': 'Keep it VERY short — under 80 characters total.',
    'medium': 'Keep it moderate — between 100 and 200 characters total.',
    'long': 'Use the full Twitter limit — between 200 and 280 characters.',
}

class EmptyCaption(RuntimeError):
    """The model answered, but with nothing. Distinct from "no model available"."""


DEFAULT_VIBE = 'casual'
DEFAULT_LENGTH = 'medium'


def caption_prompt(vibe=DEFAULT_VIBE, length=DEFAULT_LENGTH):
    """Build the caption instruction. Unknown vibe/length fall back to defaults."""
    vibe = (vibe or DEFAULT_VIBE).lower().strip()
    length = (length or DEFAULT_LENGTH).lower().strip()
    vibe_style = VIBE_PROMPTS.get(vibe, VIBE_PROMPTS[DEFAULT_VIBE])
    length_rule = LENGTH_RULES.get(length, LENGTH_RULES[DEFAULT_LENGTH])

    return (
        "You are a social media expert. Look at this image and write a single catchy Twitter/X caption.\n\n"
        f"TONE: {vibe_style}\n"
        f"LENGTH: {length_rule}\n\n"
        "Rules:\n"
        "- Use 2-4 emojis placed naturally throughout the caption\n"
        "- End with exactly 2 relevant hashtags\n"
        "- Do NOT use quotation marks around the caption\n"
        "- Return ONLY the raw caption text — no explanation, no labels, no markdown\n"
    )


def write_caption(studio, image_path, vibe=DEFAULT_VIBE, length=DEFAULT_LENGTH):
    """Generate a caption for `image_path`. Raises ValueError for bad input and
    RuntimeError when no backend can serve the selected model."""
    if not image_path:
        raise ValueError("No image supplied")

    model = resolve_model(studio.selected_model)
    if not model:
        raise RuntimeError(
            f"{studio.selected_model} not found here nor on Ollama Cloud. "
            f"Run: ollama pull {studio.selected_model}"
        )
    cli = client_for_model(model)

    img_b64 = compress_image_b64(image_path, size=1280, quality=90)

    opts = dict(GPU_OPTIONS)
    opts['num_ctx'] = max(opts.get('num_ctx', 8192), 8192)
    opts['temperature'] = 0.7
    opts['num_predict'] = 192

    resp = cli.generate(
        model=model,
        prompt=caption_prompt(vibe, length),
        images=[img_b64],
        options=opts,
        keep_alive='24h',
    )
    caption = (resp.get('response') or '').strip()
    if not caption:
        raise EmptyCaption("Model returned an empty caption")
    return caption.strip('"').strip("'").strip('`')


def write_caption_route(studio, image_path, vibe, length):
    """HTTP-facing wrapper: maps errors onto status codes."""
    try:
        caption = write_caption(studio, image_path, vibe, length)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except EmptyCaption as e:
        raise HTTPException(502, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    return {'ok': True, 'caption': caption}
