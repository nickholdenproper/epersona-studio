"""Ollama specialist VLM scans - pose / clothing / environment ground truth.

Mixin so the scanner methods keep using the Studio instance (`self`) exactly as
before the refactor.
"""
import re

from . import log
from .config import CLOTH_VLM_KEYS, ENV_VLM_KEYS, POSE_VLM_KEYS
from .ollama import scan_client

logger = log.get_logger(__name__)


class OllamaScansMixin:

    def _scan_pose_with_vlm(self, img_b64, mp_facts):
        pm = self.selected_pose_model
        if not pm:
            return None
        cli, model = scan_client(pm)
        if cli is None:
            raise Exception(
                f"Pose model '{pm}' not installed here nor on Ollama Cloud. "
                f"Run: ollama pull {pm}"
            )
        if model != pm:
            logger.info("[POSE ] '%s' unavailable - using '%s'", pm, model)

        facts_block = ""
        if mp_facts:
            facts_block = ("\n\nMEASURED SKELETAL FACTS from joint tracking (verify each; "
                           "correct any that contradict what you see):\n"
                           + "\n".join(f"- {f}" for f in mp_facts))

        prompt = (
            "You are a precise human-pose and action analyst. Analyze ONLY this person's body "
            "position, orientation and current activity. Ignore environment, clothing colors, lighting.\n"
            "Answer with EXACTLY these labeled lines, one line each, no extra text:\n"
            "POSITION: <specific stance - standing/sitting/kneeling/lying/crouching, include spine angle and any body tilt>\n"
            "ORIENTATION: <how her torso faces the camera - toward camera, away from camera, three-quarter left/right, profile left/right>\n"
            "FACING: <one of EXACTLY: toward camera | away from camera | three-quarter left | three-quarter right | profile left | profile right>\n"
            "BACK_VISIBLE: <true or false - is her back/rear the primary surface the camera lens sees?>\n"
            "CAMERA_ANGLE: <camera height relative to subject (low/eye-level/high), degrees left or right of center, shot distance (close-up/medium/full body)>\n"
            "GAZE: <exactly where she looks - toward camera, away from camera, down, up, over left shoulder, over right shoulder>\n"
            "ARMS: <BOTH arms described precisely - raised/lowered, bent angle at elbow, what each hand holds/touches/rests on, distance from body>\n"
            "LEGS: <BOTH legs described precisely - feet distance apart, knee bend angle, weight distribution left/right, foot direction>\n"
            "ACTION: <exact verb phrase for what she is doing right now, specific not generic>\n"
            "EXPRESSION: <specific facial expression - smiling/neutral/serious/sultry etc>"
            f"{facts_block}\n"
            "RULES: Be measurable and specific - use angles, distances, directions, contact points. "
            "FACING must describe which way her chest/torso points. "
            "BACK_VISIBLE is true ONLY when her back or rear is the primary surface facing the camera. "
            "For ARMS and LEGS write exact positions as a physical therapist would - no vague phrases like 'at sides'. No markdown."
        )
        from .config import GPU_OPTIONS
        opts = dict(GPU_OPTIONS)
        opts['temperature'] = 0.1
        opts['num_predict'] = 220  # keep answers terse; each key needs only a short phrase
        res = cli.generate(model=model, prompt=prompt, images=[img_b64], options=opts, keep_alive='24h')
        txt = res.get('response', '') if res else ''
        parsed = {}
        for k in POSE_VLM_KEYS:
            m = re.search(rf'^{k}\s*:\s*(.+)$', txt, re.IGNORECASE | re.MULTILINE)
            if m:
                parsed[k] = m.group(1).strip().rstrip('.')
        if not (parsed.get('POSITION') or parsed.get('ACTION')):
            return None
        logger.info("[POSE ] %s → POS: %s | ACT: %s", model, parsed.get('POSITION', ''), parsed.get('ACTION', ''))
        return parsed

    @staticmethod
    def _rear_toward_camera(vlm, extra=''):
        if vlm and vlm.get('BACK_VISIBLE', '').lower().startswith('true'):
            return True
        texts = []
        if vlm:
            facing_val = str(vlm.get('FACING', '')).lower()
            if 'away' in facing_val:
                return True
            texts = [str(vlm.get('ORIENTATION', '')), str(vlm.get('POSITION', '')),
                     facing_val, str(vlm.get('ACTION', ''))]
        if extra:
            texts.append(extra)
        blob = re.sub(r'[^a-z]+', ' ', ' '.join(texts).lower()).strip()
        if not blob:
            return False
        turned_pats = (
            'turned around', 'turning around', 'her back to the camera',
            'back to the camera', 'back facing the camera', 'back faces the camera',
            'facing away from the camera', 'facing away from camera',
            'facing away from viewer', 'facing away from viewer',
            'butt facing the camera', 'backside facing the camera',
            'buttocks facing the camera', 'rear facing the camera',
            'backside faces the camera', 'rear faces the camera',
            'presenting her behind', 'from behind',
            'back is toward', 'back is to the', 'showing her back',
            'away from the camera', 'away from camera', 'away from viewer',
            'backside toward', 'backside towards', 'butt toward', 'butt towards',
            'rear toward', 'rear towards', 'backside visible',
            'camera behind her', 'shot from behind', 'viewed from behind',
            'her rear is', 'her backside is', 'presenting her back',
        )
        if any(p in blob for p in turned_pats):
            return True
        return bool(re.search(
            r'(butt|buttock|rear|backside|back)[^a-z]{0,6}(facing|toward|towards|pointed at|presented to|visible to|turned to)\s+(the\s+)?(camera|lens|viewer)',
            blob))

    @staticmethod
    def _is_looking_back(vlm):
        if vlm:
            gaze = vlm.get('GAZE', '').lower()
            facing_val = vlm.get('FACING', '').lower()
            looking_back = ('looking back' in gaze or 'glance' in gaze or 'toward camera' in gaze
                            or 'at camera' in gaze or 'back at' in gaze or 'over shoulder' in gaze)
            if not looking_back and 'away' in facing_val:
                orient_val = vlm.get('ORIENTATION', '').lower()
                if any(k in orient_val for k in ('shoulder', 'looking', 'glanc')):
                    looking_back = True
            if looking_back:
                return True
        return False

    def _rear_line(self, vlm, extra=''):
        if not self._rear_toward_camera(vlm, extra):
            return ""
        posture = ""
        if vlm:
            posture = (vlm.get('POSITION', '') + ' ' + vlm.get('ORIENTATION', '')).lower()
        looking_back = self._is_looking_back(vlm)
        # Skin modifiers - only include most relevant ones to avoid verbosity
        skin_mods = []
        if self.opt_no_tattoos:
            skin_mods.append("tattoo-free")
        if self.opt_realism:
            skin_mods.append("natural-textured")

        skin_desc = " ".join(skin_mods)
        if skin_desc:
            skin_desc = skin_desc + " "

        # Pick evocative phrase by posture
        if 'standing' in posture:
            if looking_back:
                return f"She is turning around, peaking back over her shoulder, her bare {skin_desc}butt facing the camera"
            return f"She is turning around, her bare {skin_desc}backside presented to the camera"
        if 'seated' in posture or 'sitting' in posture:
            return f"Seated with her bare {skin_desc}backside toward the camera, peaking over her shoulder"
        if 'kneel' in posture:
            return f"Kneeling with her {skin_desc}back to the camera, peaking back"
        if 'lying' in posture or 'prone' in posture or 'face-down' in posture:
            return f"Face-down with her bare {skin_desc}backside raised toward the camera"
        # Default evocative phrase
        if looking_back:
            return f"She is turning around, peaking back over her shoulder, her bare {skin_desc}butt facing the camera"
        return f"She is turned around, her bare {skin_desc}butt facing the camera"

    def _build_pose_prefix(self, vlm_pose, pose_model_name):
        lines = []
        if vlm_pose:
            lines.append(f"CRITICAL POSE & ACTION GROUND TRUTH - pre-analyzed by dedicated vision model '{pose_model_name}'.")
            lines.append("This analysis is already done at higher precision than you can achieve. Adopt it EXACTLY:")
            for k in POSE_VLM_KEYS:
                if k == 'CAMERA_ANGLE':
                    continue
                if vlm_pose.get(k):
                    lines.append(f"- {k}: {vlm_pose[k]}")
        else:
            return ""

        if vlm_pose and vlm_pose.get('CAMERA_ANGLE'):
            lines.append(f"- CAMERA/SHOT: {vlm_pose['CAMERA_ANGLE']}")

        lines.append("")
        if vlm_pose and (vlm_pose.get('FACING') or vlm_pose.get('BACK_VISIBLE')):
            lines.append(
                "MANDATORY ORIENTATION: FACING and BACK_VISIBLE above are CRITICAL. If BACK_VISIBLE is true, "
                "your description MUST clearly state her back/rear is the side facing the camera. If FACING says "
                "'away from camera', you MUST describe her as seen from behind. Never describe her front/chest "
                "face as visible when BACK_VISIBLE is true."
            )
        lines.append(
            "MANDATORY: Your WOMAN_POSITION and ACTION_ACTIVITY sections MUST restate these facts "
            "faithfully in natural language. Do NOT contradict any fact. SHOT_ANGLE must match the "
            "detected camera angle/crop."
        )
        return "\n".join(lines) + "\n\n"

    def _scan_clothing_with_vlm(self, img_b64):
        pm = self.selected_pose_model
        if not pm:
            return None
        cli, model = scan_client(pm)
        if cli is None:
            logger.info("[CLTH ] No detail model available here nor on Ollama Cloud - skipping clothing scan.")
            return None
        if model != pm:
            logger.info("[CLTH ] '%s' unavailable - using '%s'", pm, model)

        prompt = (
            "You are a forensic fashion analyst with expertise in haute couture and streetwear. "
            "Catalog EVERY visible garment and accessory on this person with maximum precision. "
            "Ignore body, pose, background, lighting.\n"
            "Answer with EXACTLY these labeled lines - one line each - OMITTING any line for items not visible:\n"
            "TOP: <exact garment type (crop top, turtleneck, blouse, tank) + PRECISE color name (ivory, charcoal, rust orange, not just 'white' or 'orange') + exact fabric (ribbed knit, silk charmeuse, cotton jersey) + neckline shape (scoop, V-neck, crew, off-shoulder) + sleeve type/length (cap sleeve, long bishop sleeve, sleeveless) + fit (skin-tight, relaxed, oversized) + any visible construction details (princess seams, darts, ruching)>\n"
            "BOTTOM: <exact type (high-waisted jeans, pleated skirt, tailored trousers) + PRECISE color + fabric (stretch denim, wool crepe, satin) + rise (high-rise, mid-rise, low-rise) + exact length (cropped above ankle, full-length, mini above knee) + fit through hip/thigh + visible details (belt loops, pleats, pockets, distressing)>\n"
            "DRESS: <exact silhouette (A-line, bodycon, wrap, shift) + PRECISE color + fabric + neckline + sleeve details + exact length (mini, midi, maxi, tea-length) + fit through bodice/waist/hips + construction details (boning, lining visible, back closure type)>\n"
            "OUTERWEAR: <exact type (trench coat, moto jacket, blazer, cardigan) + PRECISE color + fabric (leather, wool blend, technical nylon) + fit + how worn (fully buttoned, open, tied at waist) + collar/lapel details + hardware (buttons, zipper pull)>\n"
            "FOOTWEAR: <exact type (stiletto pumps, combat boots, sneakers, sandals) + PRECISE color + material (patent leather, suede, canvas) + heel height in inches if applicable + toe shape (pointed, round, square) + any visible details (straps, buckles, laces)>\n"
            "ACCESSORIES: <list each item separately: type + material + PRECISE color + placement (wrist, neck, ears) + any visible details (engraving, stones, chain style)>\n"
            "FIT: <overall silhouette description (hourglass-accentuating, boxy and oversized, body-skimming) + how garments interact with body shape>\n"
            "FABRIC: <dominant fabrics with texture descriptions (matte finish, glossy sheen, brushed texture, smooth hand-feel)>\n"
            "DETAILS: <patterns (floral print, stripes, polka dots, solid), graphics/logos (brand names if visible, text), hardware (gold-tone buttons, silver zipper, D-ring belt), embellishments (beading, embroidery, sequins), construction (visible seams, raw edges, hem treatment)>\n"
            "RULES: Use SPECIFIC color names (dusty rose, forest green, navy blue - never just 'pink' or 'green' or 'blue'). "
            "Name exact fabrics. Describe construction details you can see. Be as specific as a fashion buyer's catalog. No markdown."
        )
        from .config import GPU_OPTIONS
        opts = dict(GPU_OPTIONS)
        opts['temperature'] = 0.1
        try:
            res = cli.generate(model=model, prompt=prompt, images=[img_b64], options=opts, keep_alive='24h')
        except Exception as e:
            logger.info("[CLTH ] Scan failed: %s", e)
            return None
        txt = res.get('response', '') if res else ''
        parsed = {}
        for k in CLOTH_VLM_KEYS:
            m = re.search(rf'^{k}\s*:\s*(.+)$', txt, re.IGNORECASE | re.MULTILINE)
            if m:
                parsed[k] = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', m.group(1)).strip().rstrip('.')
        if not any(parsed.get(k) for k in ('TOP', 'BOTTOM', 'DRESS', 'OUTERWEAR')):
            return None
        logger.info("[CLTH ] %s → %s", model, ', '.join(k for k in CLOTH_VLM_KEYS if parsed.get(k)))
        return parsed

    def _build_clothing_prefix(self, cloth_gt, model_name):
        lines = [
            f"CRITICAL CLOTHING GROUND TRUTH - pre-analyzed by dedicated vision model '{model_name}'.",
            "This garment catalog is already done at higher precision than you can achieve. Adopt it EXACTLY:",
        ]
        for k in CLOTH_VLM_KEYS:
            if cloth_gt.get(k):
                lines.append(f"- {k}: {cloth_gt[k]}")
        lines.append(
            "MANDATORY: Your CLOTHING section must match every listed fact - same garments, same EXACT "
            "color names, same fabrics. Do NOT invent garments that are not listed, do NOT omit listed ones."
        )
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _compose_clothing_text(c):
        """Build a clear, sentence-per-garment clothing description.
        Uses em-dash separation within each item for readability by image generators.
        Does NOT produce comma-joined run-ons that get truncated mid-word.
        """
        sentences = []

        # Main garments - one sentence each
        dress = c.get('DRESS', '')
        if dress:
            sentences.append(f"She wears {dress[0].lower() + dress[1:].rstrip('.')}.")
        top = c.get('TOP', '')
        if top:
            sentences.append(f"Top: {top.rstrip('.')}.")
        bottom = c.get('BOTTOM', '')
        if bottom:
            sentences.append(f"Bottom: {bottom.rstrip('.')}.")
        outer = c.get('OUTERWEAR', '')
        if outer:
            sentences.append(f"Outerwear: {outer.rstrip('.')}.")

        # Footwear
        foot = c.get('FOOTWEAR', '')
        if foot and foot.lower().strip() not in ('none', 'none visible', 'n/a', ''):
            sentences.append(f"Footwear: {foot.rstrip('.')}.")

        # Accessories
        acc = c.get('ACCESSORIES', '')
        if acc and acc.lower().strip() not in ('none', 'none visible', 'n/a', ''):
            sentences.append(f"Accessories: {acc.rstrip('.')}.")

        # Silhouette fit (concise)
        fit = c.get('FIT', '')
        if fit:
            sentences.append(f"Silhouette: {fit.rstrip('.')}.")

        # Notable construction details (skip fabric - usually redundant with item description)
        details = c.get('DETAILS', '')
        if details:
            sentences.append(f"Details: {details.rstrip('.')}.")

        return ' '.join(sentences).strip()

    def _scan_env_with_vlm(self, img_b64):
        pm = self.selected_pose_model
        if not pm:
            return None
        cli, model = scan_client(pm)
        if cli is None:
            logger.info("[ENV  ] No detail model available here nor on Ollama Cloud - skipping environment scan.")
            return None
        if model != pm:
            logger.info("[ENV  ] '%s' unavailable - using '%s'", pm, model)

        prompt = (
            "You are a forensic scene analyst. Describe ONLY the surrounding environment/background "
            "and the lighting of this photo. Ignore the person entirely - no body, pose or clothing.\n"
            "Answer with EXACTLY these labeled lines - one line each - OMITTING any line that cannot be determined:\n"
            "SETTING: <indoor/outdoor + specific place type (bedroom, studio, street, beach...)>\n"
            "BACKGROUND: <walls, floor, furniture, windows/curtains, textiles, plants, visible depth behind her>\n"
            "PROPS_OBJECTS: <objects near her: furniture, devices, decor; 'none' if none>\n"
            "TIME_OF_DAY: <daytime / golden hour / evening / night + natural vs artificial indication>\n"
            "LIGHTING: <number/type of sources, direction relative to subject, soft or hard, color temperature>\n"
            "SHADOWS: <shadow character and direction, rim light, highlights, overall exposure>\n"
            "RULES: Terse concrete nouns. Only what is VISIBLE. No markdown."
        )
        from .config import GPU_OPTIONS
        opts = dict(GPU_OPTIONS)
        opts['temperature'] = 0.1
        try:
            res = cli.generate(model=model, prompt=prompt, images=[img_b64], options=opts, keep_alive='24h')
        except Exception as e:
            logger.info("[ENV  ] Scan failed: %s", e)
            return None
        txt = res.get('response', '') if res else ''
        parsed = {}
        for k in ENV_VLM_KEYS:
            m = re.search(rf'^{k}\s*:\s*(.+)$', txt, re.IGNORECASE | re.MULTILINE)
            if m:
                v = m.group(1).strip().rstrip('.')
                if v.lower() not in ('none', 'n/a', '-'):
                    parsed[k] = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', v)
        if not (parsed.get('SETTING') or parsed.get('BACKGROUND')):
            return None
        logger.info("[ENV  ] %s → %s", model, ', '.join(k for k in ENV_VLM_KEYS if parsed.get(k)))
        return parsed

    def _build_env_prefix(self, env_gt, model_name):
        lines = [
            f"CRITICAL ENVIRONMENT & LIGHTING GROUND TRUTH - pre-analyzed by dedicated vision model '{model_name}'.",
            "This scene analysis is already done at higher precision than you can achieve. Adopt it EXACTLY:",
        ]
        for k in ENV_VLM_KEYS:
            if env_gt.get(k):
                lines.append(f"- {k}: {env_gt[k]}")
        lines.append(
            "MANDATORY: Your ENVIRONMENT section must match the SETTING, BACKGROUND, PROPS_OBJECTS and "
            "TIME_OF_DAY facts exactly - same objects, same surfaces, same depth. Your LIGHTING section must "
            "match the LIGHTING and SHADOWS facts - same source count, direction, quality and color temperature."
        )
        return "\n".join(lines) + "\n\n"

    @staticmethod
    def _compose_env_text(e):
        parts = []
        if e.get('SETTING'):
            parts.append(e['SETTING'])
        if e.get('BACKGROUND'):
            parts.append("background: " + e['BACKGROUND'])
        if e.get('PROPS_OBJECTS'):
            parts.append("props nearby: " + e['PROPS_OBJECTS'])
        if e.get('TIME_OF_DAY'):
            parts.append(e['TIME_OF_DAY'])
        return "; ".join(parts)