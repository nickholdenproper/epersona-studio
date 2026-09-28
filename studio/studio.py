"""The Studio engine — assembled from mixins into a single headless object.

All previously-inlined Studio methods live in the mixin modules below; this file
keeps the class definition, the orchesterating __init__ and the shared singleton.
"""
import os
from collections import Counter

from PIL import Image

from . import log
from .avatar import AvatarMixin
from .config import (DEFAULT_MODEL, HAIRSTYLE_DEFAULT, PROMPT_TEMPLATE_DEFAULT,
                     SKIN_TONE_DEFAULT)
from .config import OLLAMA_CLOUD_API_KEY
from .prompt_builder import PromptBuilderMixin
from .settings import SettingsMixin
from .text import DescriptionsMixin as _RealDescriptionsMixin
from .vlm_florence import FlorenceScansMixin
from .vlm_ollama import OllamaScansMixin

try:
    from colorthief import ColorThief
    COLORTHIEF_AVAILABLE = True
except ImportError:
    COLORTHIEF_AVAILABLE = False

logger = log.get_logger(__name__)


class Studio(SettingsMixin, _RealDescriptionsMixin, PromptBuilderMixin,
             OllamaScansMixin, FlorenceScansMixin, AvatarMixin):
    """Headless prompt engine — no tkinter."""

    VLM_BACKENDS = ['Ollama', 'Florence-2']

    def __init__(self):
        self.templates = {}
        self.selected_model = DEFAULT_MODEL
        self.num_ctx = 4096
        self.vlm_backend = 'Ollama'
        self.selected_pose_model = ''
        self.hair_base_color = '#FFFFFF'
        self.hairstyle = HAIRSTYLE_DEFAULT
        self.skin_tone = SKIN_TONE_DEFAULT

        self.breast_size = 50
        self.hip_size = 50
        self.hair_length = 30
        self.hair_brightness = 100

        self.opt_noise = True
        self.opt_dof = True
        self.opt_realism = True
        self.opt_hdr = False
        self.opt_no_tattoos = False
        self.opt_naked = False
        self.opt_safe = False
        self.opt_compact = False
        self.use_default_details = True
        self.prompt_template = PROMPT_TEMPLATE_DEFAULT

        self.image_path = None
        self.thumb_dataurl = None
        self.detected_colors = []
        self.cloud_api_key = OLLAMA_CLOUD_API_KEY
        self._vlm_pose_cache = {}
        self._vlm_clothing_cache = {}
        self._vlm_env_cache = {}
        self.last_pose_gt = {}
        self.last_clothing_gt = None
        self.last_env_gt = None
        self.florence_scan_status = ""
        self.florence_scan_result = None

        self.outfit_image_path = None
        self.outfit_description = ""
        self.outfit_active = False

        self.user_notes = ""

        self.load_settings()

    # ---------------- colors ----------------
    def extract_colors(self, path=None):
        path = path or self.image_path
        if not path or not os.path.exists(path):
            return []
        hex_colors = []
        if COLORTHIEF_AVAILABLE:
            try:
                ct = ColorThief(path)
                palette = ct.get_palette(color_count=12, quality=1)
                hex_colors = [f'#{r:02x}{g:02x}{b:02x}' for r, g, b in palette]
            except Exception as e:
                logger.info("ColorThief failed: %s", e)
        if not hex_colors:
            try:
                with Image.open(path) as src:
                    src.thumbnail((200, 200))
                    img = src.convert('RGB')
                # getdata() is deprecated in Pillow 12 in favour of the
                # flat-sequence accessor; fall back on older versions.
                flat = getattr(img, 'get_flattened_data', img.getdata)
                pixels = list(flat())
                counts = Counter([(round(r / 8) * 8, round(g / 8) * 8, round(b / 8) * 8) for r, g, b in pixels])
                hex_colors = [f'#{c[0]:02x}{c[1]:02x}{c[2]:02x}' for c, _ in counts.most_common(12)]
            except Exception as e:
                logger.info("Color fallback failed: %s", e)
        self.detected_colors = hex_colors[:12]
        return self.detected_colors


STUDIO = Studio()