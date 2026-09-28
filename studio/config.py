"""Central configuration — paths, presets, LLM backends and tunables.

All hardcoded values that previously lived at the top of server.py now live
here. Every value can be overridden via an environment variable (defaults are
identical to the original behavior).
"""
import os

STUDIO_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(STUDIO_PKG_DIR)
SETTINGS_PATH = os.path.join(BASE_DIR, 'settings.json')
AVATAR_DIR = os.path.join(BASE_DIR, 'avatar')
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
HISTORY_PATH = os.path.join(BASE_DIR, 'prompt_history.jsonl')
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ---- LLM backends -------------------------------------------------------
OLLAMA_HOST = os.environ.get('GEMMA_OLLAMA_HOST', 'http://localhost:11434')

# Ollama Cloud fallback — used automatically when the local server is down.
# The key is never stored here: set it via the GEMMA_CLOUD_API_KEY environment
# variable, or paste it into the app's Cloud API key field (persisted to the
# gitignored settings.json). Never commit a key to the repo.
OLLAMA_CLOUD_HOST = os.environ.get('GEMMA_OLLAMA_CLOUD_HOST', 'https://ollama.com')
OLLAMA_CLOUD_API_KEY = os.environ.get('GEMMA_CLOUD_API_KEY', '').strip()
# Advertised catalog (also the fallback list shown when the cloud API is slow).
CLOUD_MODELS = [
    'gemma4:31b',
    'gpt-oss:120b',
    'gpt-oss:20b',
    'nemotron-3-nano:30b',
    'nemotron-3-super',
    'nemotron-3-ultra',
]
# Default cloud model for generation; vision-capable fallback for specialist scans.
DEFAULT_CLOUD_MODEL = 'gemma4:31b'
CLOUD_POSE_MODEL = 'gemma4:31b'

PORT = int(os.environ.get('GEMMA_PORT', '8765'))
DEFAULT_MODEL = os.environ.get('GEMMA_DEFAULT_MODEL', 'qwen2.5vl:3b')
UPLOADS_MAX_AGE_DAYS = int(os.environ.get('GEMMA_UPLOADS_MAX_AGE_DAYS', '7'))
MODELS_CACHE_TTL = float(os.environ.get('GEMMA_MODELS_CACHE_TTL', '5'))
HISTORY_LIMIT = int(os.environ.get('GEMMA_HISTORY_LIMIT', '200'))

GPU_OPTIONS = {
    'num_gpu': 999,
    'main_gpu': 0,
    'num_thread': 16,
    'num_ctx': 8192,
    'f16_kv': True,
    'num_batch': 512,
}

# ---- Hair / skin presets -------------------------------------------------
HAIR_COLOR_PRESETS = [
    ("Pure White", "#FFFFFF"), ("Platinum Blonde", "#F2E9D8"), ("Golden Blonde", "#E0BE7A"),
    ("Honey Blonde", "#C89B5F"), ("Strawberry Blonde", "#E8A87C"), ("Auburn Red", "#A03A24"),
    ("Copper Ginger", "#B5622E"), ("Light Brown", "#9C7248"), ("Chestnut Brown", "#6B4226"),
    ("Dark Brown", "#4A2C1A"), ("Jet Black", "#14100E"), ("Silver Grey", "#BEBEBE"),
    ("Rose Pink", "#E7A6B8"), ("Ice Blue", "#A9CCE3"), ("Lavender Violet", "#9B7FB8"),
    ("Sand Beige", "#CBB89A"), ("Ash Brown", "#6E5D50"), ("Black Cherry", "#3D1A2B"),
    ("Fire Engine Red", "#C8102E"), ("Pastel Pink", "#F4B7C8"), ("Mint Green", "#A8E0CE"),
]

HAIRSTYLES = {
    "Deep Side Part (Voluminous)": "a deep side part sweeping across the crown with big, voluminous body that lifts naturally at the roots, the hair falling in soft full movement around the face",
    "Sleek Middle Part": "a clean center part with the hair falling symmetrically on both sides, sleek and smooth, framing the face evenly",
    "Slicked Straight Back": "slicked smoothly straight back away from the face, every strand combed flat with a polished, glossy finish and a sleek tight shape",
    "Loose Tousled Waves": "loose, tousled soft waves with effortless volume and natural movement, separated into light beachy strands around the face",
    "Straight & Glossy": "pin-straight, mirror-glossy hair falling in one smooth sleek sheet with a high-shine finish, flat and frizz-free",
    "Tight Defined Curls": "a head of tight, well-defined curls with springy bounce and natural volume, with soft face-framing ringlets",
    "Curtain Bangs": "curtain bangs parted down the middle and sweeping to both sides of the forehead, blending into the rest of the smoothly styled hair",
    "Blunt Bob": "a blunt, razor-sharp haircut with square, clean-cut ends and heavy one-length weight silhouetting the hair smoothly",
    "High Ponytail": "swept back and gathered into a sleek high ponytail perched near the top of the head, the face fully open with a few pieces left to frame the temples",
    "Box Braids": "neat, uniform box braids sized evenly and parted straight, hanging sleekly with smooth individual braids",
    "Fishtail Braid": "woven into a single thick fishtail braid trailing down the back, with a neat woven pattern and soft wispy ends",
    "Messy Bun": "gathered into a relaxed, slightly tousled bun with a few loose strands escaping softly around the face",
    "Sleek Updo": "pinned up into a polished, sleek low updo with every strand smoothed and swept neatly back",
    "Big-Volume Afro": "a full, rounded afro with big natural volume, an even puffy shape all around, and beautifully defined coils",
    "Space Buns": "parted and gathered into two high buns perched above the ears, with soft tendrils left out to frame the face",
    "Half-Up Half-Down": "with the upper half tied back loosely while the lower half falls free, blending gently through the crown",
    "Shaggy Layers": "a layered shag cut with choppy texture, feathered pieces, and a light wispy fringe brushing the face",
    "Wet Look Slick": "slicked into defined, glossy wet-look strands, sculpted close to the head with a reflective high-shine finish",
}

# Styles whose form assumes enough length to pull up / back. When the cut is a
# pixie/bob or shorter the base phrase would contradict the length, so a
# length-consistent variant is used instead.
HAIRSTYLES_SHORT = {
    "High Ponytail": "the hair gathered and clipped up in a small rounded micro-ponytail at the crown, ears and neck fully exposed",
    "Box Braids": "scalp-tight cornrow braids and a clean straight part, framing the face closely",
    "Fishtail Braid": "a single neat cropped fishtail braid tucked at the nape of the neck, clean and precise",
    "Messy Bun": "a tiny tousled topknot on top of the head, short sides tucked and softly textured",
    "Sleek Updo": "the short hair swept back into a smooth, low polished form hugging the head",
    "Space Buns": "two small buns perched above the ears with the rest of the short hair cropped close",
}


def hairstyle_phrase(style, hair_length):
    """Description for a hairstyle, adapting 'up' styles when hair is too short."""
    phrase = HAIRSTYLES.get(style, HAIRSTYLE_DEFAULT)
    if hair_length <= 34 and style in HAIRSTYLES_SHORT:
        return HAIRSTYLES_SHORT[style]
    return phrase

SKIN_TONES = {
    "Warm Tan (Default)": "warm natural tan skin with subtle freckles",
    "Fair Porcelain": "fair porcelain skin with cool pink undertones",
    "Pale Ivory": "pale ivory skin with soft rosy undertones",
    "Light Beige": "light beige skin with warm neutral undertones",
    "Olive Mediterranean": "smooth olive-toned Mediterranean skin",
    "Honey Bronze": "honey-bronze skin with golden undertones",
    "Sun-Kissed Latina": "sun-kissed light brown Latina skin with caramel undertones",
    "Golden Southeast Asian": "golden-toned Southeast Asian skin with amber undertones",
    "South Asian Brown": "rich light-brown South Asian skin with warm golden undertones",
    "Medium Brown": "even medium-brown skin with rich warm undertones",
    "Deep Brown African": "deep brown skin with warm mahogany undertones",
    "Rich Ebony": "radiant deep ebony skin with a smooth even tone",
    "Warm Ivory": "warm ivory skin with soft golden undertones",
    "Golden Fair": "golden fair skin with a warm luminous undertone",
    "Peach Blush": "peachy skin with a rosy natural flush",
    "Tan Bronze": "deep tan bronze skin with a sun-kissed glow",
    "Golden Caramel": "golden caramel skin with rich warm undertones",
    "Deep Mahogany": "deep mahogany skin with rich red-brown undertones",
    "Cool Ebony": "cool-toned deep ebony skin with an even matte finish",
}

HAIRSTYLE_DEFAULT = next(iter(HAIRSTYLES))
SKIN_TONE_DEFAULT = next(iter(SKIN_TONES))

# ---- VLM scan label sets -------------------------------------------------
POSE_VLM_KEYS = ['POSITION', 'ORIENTATION', 'FACING', 'CAMERA_ANGLE', 'GAZE', 'ARMS', 'LEGS', 'ACTION', 'EXPRESSION']
CLOTH_VLM_KEYS = ['TOP', 'BOTTOM', 'DRESS', 'OUTERWEAR', 'FOOTWEAR', 'ACCESSORIES', 'FIT', 'FABRIC', 'DETAILS']
ENV_VLM_KEYS = ['SETTING', 'BACKGROUND', 'PROPS_OBJECTS', 'TIME_OF_DAY', 'LIGHTING', 'SHADOWS']

# ---- Hair length breakpoints ----------------------------------------------
HAIR_BREAKPOINTS = [
    (0, 2, "buzz-cut / ear-length", "just at the ears"),
    (10, 4, "very short, cropped pixie cut", "at the nape of the neck"),
    (20, 7, "short pixie cut", "just below the ear"),
    (30, 10, "short, chin-length bob", "at the jawline / chin"),
    (38, 12, "collarbone-length lob", "grazing the collarbone"),
    (46, 15, "shoulder-length", "resting on the shoulders"),
    (54, 20, "below-shoulder, mid-back length", "a few inches below the shoulders"),
    (62, 26, "long, mid-back length", "reaching mid-back"),
    (70, 32, "long, lower-back length", "reaching the lower back"),
    (78, 38, "very long, waist-length", "reaching the natural waist"),
    (86, 46, "very long, hip-length", "reaching the hips"),
    (93, 56, "extremely long, thigh-length", "falling to mid-thigh"),
    (100, 72, "dramatic floor-length", "cascading all the way to the floor"),
]

# ---- Prompt templates ------------------------------------------------------
# Single source of truth: the UI buttons, the Studio default and settings
# validation all derive from this list.
PROMPT_TEMPLATES = ['Natural Paragraph', 'Direct Attributes', 'Soul 2.0']
PROMPT_TEMPLATE_DEFAULT = PROMPT_TEMPLATES[0]

__all__ = [
    'BASE_DIR', 'SETTINGS_PATH', 'AVATAR_DIR', 'UPLOADS_DIR', 'HISTORY_PATH',
    'OLLAMA_HOST', 'OLLAMA_CLOUD_HOST', 'OLLAMA_CLOUD_API_KEY', 'CLOUD_MODELS',
    'DEFAULT_CLOUD_MODEL', 'CLOUD_POSE_MODEL', 'PORT', 'DEFAULT_MODEL',
    'UPLOADS_MAX_AGE_DAYS', 'MODELS_CACHE_TTL', 'HISTORY_LIMIT', 'GPU_OPTIONS',
    'HAIR_COLOR_PRESETS', 'HAIRSTYLES', 'HAIRSTYLES_SHORT', 'HAIRSTYLE_DEFAULT',
    'hairstyle_phrase',
    'SKIN_TONES', 'SKIN_TONE_DEFAULT',
    'POSE_VLM_KEYS', 'CLOTH_VLM_KEYS', 'ENV_VLM_KEYS',
    'HAIR_BREAKPOINTS', 'PROMPT_TEMPLATES', 'PROMPT_TEMPLATE_DEFAULT',
]