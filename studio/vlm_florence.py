"""Florence-2 based VLM scans — pose / clothing / environment / main.

Mixin so the scan methods keep using the Studio instance (`self`) and the shared
FLORENCE singleton exactly as before the refactor.
"""
import re

from PIL import Image

from . import log
from .config import CLOTH_VLM_KEYS, ENV_VLM_KEYS
from .florence import FLORENCE

logger = log.get_logger(__name__)


class FlorenceScansMixin:

    def _florence_scan_pose(self, image_path):
        try:
            with Image.open(image_path) as src:
                img = src.copy()
            result = FLORENCE.caption(img, mode="more_detailed")
            full_text = str(result) if isinstance(result, dict) else str(result)
            # Use the full caption — it's richer than keyword parsing
            # Florence-2 describes pose, orientation, expression, arms, legs all in one pass
            back_visible = any(k in full_text.lower() for k in (
                'back turned', 'back to', 'from behind', 'rear', 'backside',
                'butt facing', 'back of', 'behind her',
            ))
            facing = "away from camera" if back_visible else "toward camera"
            if any(k in full_text.lower() for k in ('side', 'profile', 'sideways')):
                facing = "profile"
            gaze = "toward camera"
            if any(k in full_text.lower() for k in ('looking away', 'looking down', 'eyes closed', 'looking up')):
                gaze = "away from camera"
            expression = "neutral"
            for expr in ('smiling', 'laughing', 'serious', 'happy', 'sad',
                         'surprised', 'sultry', 'seductive', 'playful', 'focused'):
                if expr in full_text.lower():
                    expression = expr
                    break
            parsed = {
                'POSITION': full_text[:400],
                'ORIENTATION': "back facing camera" if back_visible else "front facing",
                'FACING': facing,
                'BACK_VISIBLE': str(back_visible),
                'CAMERA_ANGLE': "eye-level medium shot",
                'GAZE': gaze,
                'ARMS': "see position description",
                'LEGS': "see position description",
                'ACTION': full_text[:300],
                'EXPRESSION': expression,
            }
            logger.info("[FLORENCE/POSE] → %s", full_text[:120])
            return parsed
        except Exception as e:
            logger.info("[FLORENCE/POSE] Scan failed: %s", e)
            return None

    def _florence_scan_clothing(self, image_path):
        try:
            with Image.open(image_path) as src:
                img = src.copy()
            detailed = FLORENCE.caption(img, mode="more_detailed")
            full_text = str(detailed) if isinstance(detailed, dict) else str(detailed)
            clothing_keywords = [
                'dress', 'shirt', 'blouse', 'top', 'pants', 'jeans', 'skirt',
                'jacket', 'coat', 'sweater', 'tank', 'bikini', 'swimsuit',
                'boots', 'shoes', 'heels', 'sneakers', 'sandals',
                'hat', 'scarf', 'gloves', 'necklace', 'bracelet', 'earrings',
                'glasses', 'belt', 'watch', 'ring',
            ]
            sentences = re.split(r'(?<=[.!?])\s+', full_text)
            cloth_sentences = [s for s in sentences if any(k in s.lower() for k in clothing_keywords)]
            cloth_text = ' '.join(cloth_sentences) if cloth_sentences else full_text

            def find_garment(text, keywords):
                for s in re.split(r'(?<=[.!?])\s+', text):
                    if any(k in s.lower() for k in keywords):
                        return s.strip()
                return ""
            parsed = {
                'TOP': find_garment(cloth_text, ['shirt', 'blouse', 'top', 'tank', 'sweater', 'turtleneck']),
                'BOTTOM': find_garment(cloth_text, ['pants', 'jeans', 'skirt', 'shorts', 'trousers']),
                'DRESS': find_garment(cloth_text, ['dress', 'gown', 'romper', 'jumpsuit']),
                'OUTERWEAR': find_garment(cloth_text, ['jacket', 'coat', 'blazer', 'cardigan']),
                'FOOTWEAR': find_garment(cloth_text, ['boots', 'shoes', 'heels', 'sneakers', 'sandals']),
                'ACCESSORIES': find_garment(cloth_text, ['hat', 'scarf', 'gloves', 'necklace', 'bracelet', 'earrings', 'glasses', 'belt']),
                'FIT': '',
                'FABRIC': '',
                'DETAILS': cloth_text[:300] if cloth_text else "",
            }
            if any(parsed.get(k) for k in ('TOP', 'BOTTOM', 'DRESS', 'OUTERWEAR')):
                logger.info("[FLORENCE/CLOTH] → %s", ', '.join(k for k in CLOTH_VLM_KEYS if parsed.get(k)))
                return parsed
            logger.info("[FLORENCE/CLOTH] No clothing detected")
            return None
        except Exception as e:
            logger.info("[FLORENCE/CLOTH] Scan failed: %s", e)
            return None

    def _florence_scan_env(self, image_path):
        try:
            with Image.open(image_path) as src:
                img = src.copy()
            detailed = FLORENCE.caption(img, mode="more_detailed")
            full_text = str(detailed) if isinstance(detailed, dict) else str(detailed)
            setting = ""
            background = ""
            time_of_day = ""
            lighting = ""
            if any(k in full_text.lower() for k in ('indoor', 'room', 'interior', 'inside')):
                setting = "indoor"
            elif any(k in full_text.lower() for k in ('outdoor', 'outside', 'street', 'park', 'beach', 'garden')):
                setting = "outdoor"
            bg_kws = ['wall', 'window', 'curtain', 'furniture', 'bed', 'sofa', 'table',
                       'tree', 'sky', 'building', 'door', 'floor', 'carpet', 'lamp']
            bg_lines = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_text)
                        if any(k in s.lower() for k in bg_kws)]
            background = '. '.join(bg_lines[:3]) if bg_lines else ""
            if any(k in full_text.lower() for k in ('night', 'dark', 'evening')):
                time_of_day = "nighttime"
            elif any(k in full_text.lower() for k in ('sunset', 'golden', 'dusk')):
                time_of_day = "golden hour"
            elif any(k in full_text.lower() for k in ('sun', 'day', 'bright', 'morning')):
                time_of_day = "daytime"
            light_kws = ['light', 'shadow', 'bright', 'dim', 'natural', 'artificial', 'lamp', 'sunlight']
            light_lines = [s.strip() for s in re.split(r'(?<=[.!?])\s+', full_text)
                           if any(k in s.lower() for k in light_kws)]
            lighting = '. '.join(light_lines[:2]) if light_lines else "natural lighting"
            parsed = {}
            if setting:
                parsed['SETTING'] = setting
            if background:
                parsed['BACKGROUND'] = background
            if time_of_day:
                parsed['TIME_OF_DAY'] = time_of_day
            if lighting:
                parsed['LIGHTING'] = lighting
            if parsed:
                logger.info("[FLORENCE/ENV] → %s", ', '.join(parsed.keys()))
            return parsed if parsed else None
        except Exception as e:
            logger.info("[FLORENCE/ENV] Scan failed: %s", e)
            return None
