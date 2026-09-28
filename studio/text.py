"""Pure text & color helpers plus the Studio description layer.

Contains the body / hair / skin description builders (previously methods on
Studio) as a mixin, delegating to pure functions so the logic is unit-testable
without touching a live Studio instance.
"""
import colorsys
import re

from .config import hairstyle_phrase, SKIN_TONES, SKIN_TONE_DEFAULT
from .config import HAIR_BREAKPOINTS as _HAIR_BREAKPOINTS

__all__ = [
    'clean_text_advanced',
    'strip_front_facing_sentences',
    'describe_hair_color',
    'final_hair_hex',
    'hex_to_rgb',
    'DescriptionsMixin',
]


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------
def clean_text_advanced(text):
    text = re.sub(r'\*\*[^*]+\*\*', '', text)
    text = re.sub(r'\*[^*]+\*', '', text)
    text = re.sub(r'#+\s*[^\n]+\n', '', text)
    text = re.sub(r'^[\s]*[-*•]\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'`[^`]+`', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def strip_front_facing_sentences(text):
    front_kws = (
        'looking at the camera', 'looking at camera', 'eye contact',
        'staring at the camera', 'staring at camera', 'facing the camera',
        'facing camera', 'faces the camera', 'faces camera',
        'gaze toward camera', 'gaze at camera', 'looking directly at',
        'eyes locked on', 'meets the camera', 'meets camera',
        'direct eye contact', 'looking straight at',
    )
    sentences = re.split(r'(?<=[.!?])(?=\s)', text)
    kept = []
    for s in sentences:
        sl = s.strip().lower()
        if any(k in sl for k in front_kws):
            continue
        kept.append(s)
    return ''.join(kept)


def describe_hair_color(r, g, b):
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hue = h * 360
    if v <= 0.12:
        return "jet matte black"
    if s < 0.12:
        if v >= 0.92:
            return "flat pure white"
        if v >= 0.68:
            return "silvery platinum white"
        if v >= 0.40:
            return "neutral medium grey"
        if v >= 0.15:
            return "dark charcoal grey"
        return "matte black"
    if 300 <= hue < 345 and s <= 0.55 and v >= 0.55:
        return "pastel rose pink"
    if hue < 18 or hue >= 345:
        if v >= 0.72 and s <= 0.45:
            return "strawberry blonde"
        if v >= 0.45:
            return "auburn red"
        return "deep burgundy"
    if hue < 45:
        if v >= 0.80 and s <= 0.32:
            return "champagne platinum blonde"
        if v >= 0.62 and s <= 0.55:
            return "golden blonde"
        if s >= 0.55 and v >= 0.45:
            return "vivid copper ginger"
        if v >= 0.35:
            return "caramel light brown"
        return "dark chestnut brown"
    if hue < 65:
        if v >= 0.62:
            return "honey dirty blonde"
        if v >= 0.35:
            return "ashy light brown"
        return "dark ash brown"
    if hue < 165:
        return "vivid fantasy green"
    if hue < 200:
        return "teal cyan"
    if hue < 250:
        return "ice blue"
    if hue < 290:
        return "lavender violet"
    return "soft rose pink"


def final_hair_hex(base_color, brightness):
    r = int(base_color[1:3], 16) / 255
    g = int(base_color[3:5], 16) / 255
    b = int(base_color[5:7], 16) / 255
    hh, s, v = colorsys.rgb_to_hsv(r, g, b)
    factor = (10 + (brightness / 100) * 245) / 255
    v2 = max(0.02, min(1.0, v * factor))
    r2, g2, b2 = colorsys.hsv_to_rgb(hh, s, v2)
    return f'#{int(r2 * 255):02X}{int(g2 * 255):02X}{int(b2 * 255):02X}'


def hex_to_rgb(hx):
    hx = hx.upper()
    return (int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16))


# --------------------------------------------------------------------------
# Body description tables (single source of truth)
#
# These drive both the main Generate path (get_body_description) and the
# Prompt Injector. They used to be duplicated across three call sites and had
# drifted apart, so the "Safe wording" toggle only affected the injector.
# --------------------------------------------------------------------------
_BREAST_EXPLICIT = [
    (15, "small, modest breasts"),
    (35, "average-sized, perky breasts"),
    (55, "full, prominent breasts"),
    (75, "large, full breasts that are round and prominent"),
    (90, "very large, heavy breasts that are round and protruding"),
    (100, "enormous, massive, oversized breasts that are round, heavy, and "
          "prominently protruding with a deep, exaggerated cleavage"),
]
_BREAST_SAFE = [
    (15, "a slim, delicate frame"),
    (35, "a lean, athletic frame"),
    (55, "a full, graceful figure"),
    (75, "a curvy, womanly figure"),
    (90, "a very curvy, full figure"),
    (100, "an extremely curvaceous, striking figure"),
]
_HIP_EXPLICIT = [
    (15, "slim, narrow hips"),
    (35, "moderately curved hips"),
    (55, "curved hips that flare"),
    (75, "wide, flaring hips that are broad"),
    (90, "very wide, sweeping hips that flare out dramatically"),
    (100, "extremely wide, sweeping hips that flare out dramatically, "
          "almost cartoonishly wide"),
]
_HIP_SAFE = [
    (15, "slim hips"),
    (35, "moderately curved hips"),
    (55, "curved hips that flare gently"),
    (75, "wide, flaring hips"),
    (90, "very wide, sweeping hips"),
    (100, "extremely wide, sweeping hips"),
]


def _bucket(val, table):
    """First table entry whose threshold `val` falls under."""
    for threshold, text in table:
        if val < threshold:
            return text
    return table[-1][1]


def body_parts(breast_size, hip_size, safe=False):
    """Resolve the breast/hip phrases and overall figure label for a slider pair.

    `safe=True` swaps in euphemistic framing that avoids anatomical wording.
    Returns (breast_desc, hip_desc, figure_label).
    """
    b, h = breast_size, hip_size
    breast = _bucket(b, _BREAST_SAFE if safe else _BREAST_EXPLICIT)
    hip = _bucket(h, _HIP_SAFE if safe else _HIP_EXPLICIT)
    if b < 30 and h < 30:
        label = "slender"
    elif b > 65 or h > 65:
        label = "curvy hourglass"
    else:
        label = "athletic"
    return breast, hip, label


# --------------------------------------------------------------------------
# Studio description layer (mixin — methods keep `self` working as before)
# --------------------------------------------------------------------------
class DescriptionsMixin:
    HAIR_BREAKPOINTS = _HAIR_BREAKPOINTS

    def get_body_description(self):
        breast, hip, _label = body_parts(self.breast_size, self.hip_size, self.opt_safe)
        if self.opt_safe:
            return (f"A woman with a curvy figure — {breast}, a defined cinched "
                    f"waist, {hip}, and rounded curves with shapely thighs.")
        return (f"A woman with a naturally curvy hourglass figure—featuring {breast}, a defined waist "
                f"that cinches, {hip}, and a rounded backside with thicker thighs.")

    def get_hair_description(self):
        bp = self.HAIR_BREAKPOINTS
        sv = self.hair_length
        if sv <= bp[0][0]:
            inches, label, landmark = bp[0][1], bp[0][2], bp[0][3]
        elif sv >= bp[-1][0]:
            inches, label, landmark = bp[-1][1], bp[-1][2], bp[-1][3]
        else:
            inches, label, landmark = bp[0][1], bp[0][2], bp[0][3]
            for i in range(len(bp) - 1):
                lo, hi = bp[i], bp[i + 1]
                if lo[0] <= sv <= hi[0]:
                    t = (sv - lo[0]) / (hi[0] - lo[0])
                    inches = lo[1] + t * (hi[1] - lo[1])
                    label = lo[2] if t < 0.5 else hi[2]
                    landmark = lo[3] if t < 0.5 else hi[3]
                    break
        inches_r = round(inches, 1)
        cm_r = round(inches_r * 2.54, 1)

        final_hex = self._final_hair_hex()
        cname = self._describe_hair_color(int(final_hex[1:3], 16), int(final_hex[3:5], 16), int(final_hex[5:7], 16))
        style_phrase = hairstyle_phrase(self.hairstyle, self.hair_length)
        return (
            f"Her hair is {cname}, exact color code {final_hex} — a true, uniform {cname} tone. "
            f"The cut is {label}, measuring exactly {inches_r} inches ({cm_r} cm) long, {landmark}, "
            f"styled in {style_phrase}, with visible strand texture, realistic root shadow, "
            f"flyaways, and slight variation in tone."
        )

    def hair_lock_parts(self):
        fh = self._final_hair_hex()
        cn = self._describe_hair_color(int(fh[1:3], 16), int(fh[3:5], 16), int(fh[5:7], 16))
        return cn, fh

    def _hair_core(self):
        """Compact hair anchor for the Soul 2.0 format: color, hex, cut label."""
        fh = self._final_hair_hex()
        cn = self._describe_hair_color(int(fh[1:3], 16), int(fh[3:5], 16), int(fh[5:7], 16))
        bp = self.HAIR_BREAKPOINTS
        sv = self.hair_length
        if sv <= bp[0][0]:
            label = bp[0][2]
        elif sv >= bp[-1][0]:
            label = bp[-1][2]
        else:
            label = bp[0][2]
            for i in range(len(bp) - 1):
                lo, hi = bp[i], bp[i + 1]
                if lo[0] <= sv <= hi[0]:
                    t = (sv - lo[0]) / (hi[0] - lo[0])
                    label = lo[2] if t < 0.5 else hi[2]
                    break
        return f"{cn} ({fh}) hair, {label}"

    def get_skin_description(self):
        tone = SKIN_TONES.get(self.skin_tone, SKIN_TONE_DEFAULT)
        if self.opt_realism:
            return (f"Her {tone} appears natural and realistic, with visible pores, natural "
                    f"texture, realistic skin imperfections.")
        return f"Her {tone} has a clean, smooth, natural look with realistic tone."

    def _final_hair_hex(self):
        return final_hair_hex(self.hair_base_color, self.hair_brightness)

    @staticmethod
    def _describe_hair_color(r, g, b):
        return describe_hair_color(r, g, b)

    @staticmethod
    def _strip_front_facing_sentences(text):
        return strip_front_facing_sentences(text)

    @staticmethod
    def clean_text_advanced(text):
        return clean_text_advanced(text)