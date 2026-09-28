"""Prompt builder — phased composition into the three supported templates.

Mixin keeps `self` working exactly as the original Studio method did; the whole
`build_advanced_prompt` body is preserved unchanged.
"""
import math
import re

from .config import hairstyle_phrase


class PromptBuilderMixin:

    def build_advanced_prompt(self, ai_description, pose_info, colors):
        ALL_LABELS = ['SHOT_ANGLE', 'WOMAN_POSITION', 'ACTION_ACTIVITY', 'CLOTHING', 'ENVIRONMENT',
                      'LIGHTING', 'MOOD', 'POSE', 'FACIAL_FEATURES', 'PROPS_OBJECTS', 'SKIN_DETAILS', 'SUBJECT_AGE']
        boundary_re = '|'.join(ALL_LABELS)

        def condense_block(text, max_chars):
            if not text or len(text) <= max_chars:
                return text
            cutoff = text[:max_chars]
            last_dot = cutoff.rfind('.')
            last_semi = cutoff.rfind(';')
            cut = max(last_dot, last_semi)
            if cut > max_chars // 2:
                return cutoff[:cut + 1].strip()
            sp = cutoff.rfind(' ')
            if sp > max_chars // 3:
                result = cutoff[:sp].rstrip(',;: ').strip()
                # Strip dangling short words (articles, prepositions) left mid-sentence
                while True:
                    words = result.rsplit(None, 1)
                    if len(words) != 2:
                        break
                    last_word = words[-1].lower()
                    if len(last_word) <= 4 and last_word in (
                        'a', 'an', 'the', 'and', 'or', 'but', 'with', 'for', 'of',
                        'to', 'in', 'on', 'at', 'by', 'as', 'from', 'into', 'over',
                        'near', 'than', 'like'
                    ):
                        result = words[0].rstrip(',;: ')
                    else:
                        break
                return result
            return cutoff.rstrip(',; ').strip()

        cleaned_ai = self.clean_text_advanced(ai_description)

        # ---- custom-layer locks computed first, used to de-conflict the palette ----
        lock_name, lock_hex = self.hair_lock_parts()

        def _rgb(hx):
            hx = hx.upper()
            return (int(hx[1:3], 16), int(hx[3:5], 16), int(hx[5:7], 16))

        l_rgb = _rgb(lock_hex)
        palette = []
        for c in (colors or [])[:12]:
            try:
                c_rgb = _rgb(c)
            except Exception:
                continue
            if math.sqrt((c_rgb[0] - l_rgb[0]) ** 2 + (c_rgb[1] - l_rgb[1]) ** 2
                         + (c_rgb[2] - l_rgb[2]) ** 2) >= 60:
                palette.append(c)
        colors_block = ""
        if palette:
            formatted_hex = [f'"{c}"' for c in palette]
            colors_block = f"\n\nHEX VALUES: [{', '.join(formatted_hex)}]"

        if not self.use_default_details:
            return cleaned_ai + colors_block

        cf = 0.55 if self.opt_compact else 1.0

        ai_no_hair = re.sub(r'[^.]*\b(hair|curls|blonde|brunette|dark brown|black hair|brown hair)\b[^.]*\.', '',
                            cleaned_ai, flags=re.IGNORECASE)
        ai_no_body = re.sub(r'[^.]*\b(breast|bust|cleavage|hip|hips|waist|hourglass|curvy|voluptuous|buxom|shapely|figure|body|thigh|thighs|backside|buttocks|derriere)\b[^.]*\.', '',
                            ai_no_hair, flags=re.IGNORECASE)
        ai_no_clothing = re.sub(r'[^.]*\b(dress|top|blouse|shirt|tank|turtleneck|sweater|cardigan|jacket|coat|blazer|jeans|pants|trousers|skirt|shorts|leggings|boots|shoes|heels|sneakers|sandals|jewelry|necklace|bracelet|earrings|ring|watch|belt|hat|scarf|gloves)\b[^.]*\.', '',
                                ai_no_body, flags=re.IGNORECASE)
        if self.opt_no_tattoos:
            ai_no_clothing = re.sub(r'[^.]*\b(tattoo|ink|body art|marking|sleeve|arm art|skin art)\b[^.]*\.', '',
                                ai_no_clothing, flags=re.IGNORECASE)

        def extract_section(section_name, text):
            pat = fr'(?:^|\n){section_name}\s*:\s*(.*?)(?=\n(?:{boundary_re})\s*:|\Z)'
            m = re.search(pat, text, re.IGNORECASE | re.DOTALL)
            if m:
                block = m.group(1).strip()
                block = re.sub(r'\n\s*[-•]\s*', ' ', block)
                block = re.sub(r'\s{2,}', ' ', block)
                return block
            m = re.search(fr'{section_name}\s*:\s*(.+?)(?=\s+(?:{boundary_re})\s*:|$)', text,
                          re.IGNORECASE | re.DOTALL)
            return m.group(1).strip() if m else ""

        # Sections are parsed from the RAW description: clean_text_advanced collapses
        # newlines, which breaks the line-anchored regexes and makes the first section
        # swallow the entire text. Cleaned text is only used for prose fallbacks below.
        raw_ai = ai_description

        # ---------- PHASE 1: position, camera, environment, lighting ----------
        pose = extract_section("POSE", raw_ai)
        shot_angle = extract_section("SHOT_ANGLE", raw_ai)
        woman_pos = extract_section("WOMAN_POSITION", raw_ai)
        action = extract_section("ACTION_ACTIVITY", raw_ai)
        environment = extract_section("ENVIRONMENT", raw_ai)
        lighting = extract_section("LIGHTING", raw_ai)

        gt = self.last_pose_gt or {}
        vlm = gt.get('vlm')

        if vlm:
            # Use the full Florence-2 caption as pose description directly
            # POSITION contains the complete caption — it's richer than parsing individual keys
            _pos = (vlm.get('POSITION') or '').strip()
            _back = vlm.get('BACK_VISIBLE', '').lower().startswith('true')

            if _pos:
                woman_pos = _pos
            if _back:
                woman_pos = f"Her back faces the camera directly. {_pos}"
            if vlm.get('CAMERA_ANGLE'):
                shot_angle = vlm['CAMERA_ANGLE']

        env_gt = self.last_env_gt or {}
        gt_env_txt = self._compose_env_text(env_gt)
        if gt_env_txt:
            environment = gt_env_txt
        gt_light = " ".join(x for x in (env_gt.get('LIGHTING'), env_gt.get('SHADOWS')) if x).strip()
        if gt_light:
            lighting = gt_light

        # ---------- PHASE 2: clothing ----------
        clothing = extract_section("CLOTHING", raw_ai)
        _cl_from_specialist = False
        cl_gt = self.last_clothing_gt
        if cl_gt:
            composed_cl = self._compose_clothing_text(cl_gt)
            if composed_cl:
                clothing = composed_cl
                _cl_from_specialist = True

        notes = (self.user_notes or '').strip()
        if notes:
            # Always apply user notes — they are highest-priority corrections regardless of vlm
            woman_pos = f"{woman_pos}. {notes}" if woman_pos else notes

        rear_line = self._rear_line(vlm, extra='' if vlm else notes)
        is_rear_facing = bool(rear_line)
        is_looking_back = self._is_looking_back(vlm) if is_rear_facing else False

        # When rear-facing AND not looking back: strip facial details (not visible)
        # When rear-facing AND looking back over shoulder: keep face (it's visible)
        if is_rear_facing and not is_looking_back:
            facial = "face turned away from the camera, not visible from this angle"
            subject_age = ""
            cleaned_ai = self._strip_front_facing_sentences(cleaned_ai)
            ai_no_clothing = self._strip_front_facing_sentences(ai_no_clothing)

        naked_override = ""
        if self.opt_naked:
            clothing = ""
            naked_override = (
                "She is completely naked — no clothing, no fabric, no undergarments, no coverings of any kind. "
                "Every part of her bare skin is fully exposed and visible, rendered with natural, realistic, "
                "photographic skin detail — pores, natural skin tone variations, subtle shadows, and realistic body lighting."
            )
        elif self.outfit_active and self.outfit_description:
            clothing = self.outfit_description

        if woman_pos and not pose:
            pose = woman_pos

        if not (pose or clothing or environment):
            sentences = [s.strip() for s in ai_no_clothing.split('.') if s.strip()]
            clothing_keywords = ['wear', 'cloth', 'outfit', 'dress', 'top', 'pant', 'jean', 'bikini', 'swimsuit', 'shirt', 'jacket']
            pose_keywords = ['pose', 'sit', 'lean', 'stand', 'recline', 'arch', 'position', 'look', 'gaze']
            setting_keywords = ['setting', 'background', 'room', 'space', 'headboard', 'curtain', 'window']
            for s in sentences:
                sl = s.lower()
                if any(k in sl for k in clothing_keywords) and not clothing:
                    clothing = s
                elif any(k in sl for k in pose_keywords) and not pose:
                    pose = s
                elif any(k in sl for k in setting_keywords) and not environment:
                    environment = s

        def strip_labels(text):
            return re.sub(rf'\b({boundary_re})\s*:\s*', '', text, flags=re.IGNORECASE).strip()

        # Tighter limits — generators attend most to the first ~300 tokens;
        # keeping each section lean ensures nothing important gets buried.
        # Exception: when specialist scans supply the data, trust it at full length.
        shot_angle = strip_labels(condense_block(shot_angle, int(130 * cf)))
        if vlm:
            woman_pos = strip_labels(woman_pos)   # specialist pose — full detail, no truncation
        else:
            woman_pos = strip_labels(condense_block(woman_pos, int(420 * cf)))
        action = strip_labels(condense_block(action, int(180 * cf)))
        if _cl_from_specialist:
            clothing = strip_labels(clothing)      # specialist clothing — full detail, no truncation
        else:
            clothing = strip_labels(condense_block(clothing, int(380 * cf)))
        environment = strip_labels(condense_block(environment, int(200 * cf)))
        lighting = strip_labels(condense_block(lighting, int(140 * cf)))

        # ---------- custom-layer extras pulled from the description ----------
        facial = strip_labels(extract_section("FACIAL_FEATURES", raw_ai))
        skin_details = strip_labels(extract_section("SKIN_DETAILS", raw_ai))
        props = strip_labels(extract_section("PROPS_OBJECTS", raw_ai))
        mood = strip_labels(extract_section("MOOD", raw_ai)) or (
            vlm.get('EXPRESSION') if vlm else '')
        subject_age = strip_labels(extract_section("SUBJECT_AGE", raw_ai))
        facial = condense_block(facial, int(180 * cf))
        skin_details = condense_block(skin_details, int(100 * cf))
        props = condense_block(props, int(100 * cf))
        mood = condense_block(mood, int(80 * cf))

        default_skin = self.get_skin_description()
        if self.opt_no_tattoos:
            default_skin += " Her skin is completely clear and pristine, entirely free of any tattoos."

        if self.opt_hdr:
            hdr_str = "high-key dramatic studio lighting with rich high-contrast details and deep shadows."
            lighting = f"{lighting} with {hdr_str}" if lighting else hdr_str

        detailed_pos = woman_pos or pose

        style_tags = []
        if self.opt_noise:
            style_tags.append("natural film grain")
        if self.opt_dof:
            style_tags.append("shallow depth of field")
        style_tags.append("cinematic photo")

        body_desc = self.get_body_description()
        _body_core = body_desc
        for _pfx in ("A woman with ", "A "):
            if _body_core.startswith(_pfx):
                _body_core = _body_core[len(_pfx):]
                break

        if self.prompt_template == "Soul 2.0":
            # Higgsfield Soul 2.0 format: Soul identity core -> anchors -> pose/scene.
            # Custom settings (body/hair/pose/clothing) always keep FULL detail — the
            # word budget may only ever trim optional scene extras (face/skin/env/light).
            age_word = re.sub(r'years?\s*old', '', subject_age or '').strip().rstrip('.').lower() \
                if subject_age else ''
            age_word = (age_word + ' yo') if age_word and not age_word.endswith('yo') else (age_word or 'young adult')
            eth = re.sub(r'\(.*\)', '', self.skin_tone).strip().lower()
            avg = (self.breast_size + self.hip_size) / 2
            build_word = ('slim-curvy' if avg < 25 else 'curvy hourglass' if avg < 45
                          else 'voluptuous hourglass' if avg < 65 else 'super-curvy hourglass' if avg < 85
                          else 'extreme hourglass')
            soul_line = f"Soul: {age_word} {build_word} woman, {eth} skin"

            hair_seg = f"{self._hair_core()} — {hairstyle_phrase(self.hairstyle, self.hair_length)}"
            face_seg = "" if (is_rear_facing and not is_looking_back) else condense_block(facial, 110)
            _skin_raw = re.sub(r'^Her ', '', default_skin).split('.')[0].strip()
            skin_seg = condense_block(_skin_raw.split(',')[0], 80)
            body_seg = body_desc.rstrip('.')
            pose_seg = (rear_line.rstrip('.') if rear_line
                        else condense_block(detailed_pos, 340).rstrip('.'))
            action_seg = condense_block(action, 90).rstrip('.') if action else ""
            cloth_seg = (naked_override.split('—')[0].strip().rstrip('.')
                         if naked_override else condense_block(clothing, 500).rstrip('.'))
            env_seg = condense_block(environment, 130).rstrip('.')
            light_seg = condense_block(lighting, 110).rstrip('.')
            style_seg = ("Cinematic photoreal" +
                         (", natural film grain" if self.opt_noise else "") +
                         (", shallow depth of field" if self.opt_dof else ""))
            mood_seg = condense_block(mood, 70).rstrip('.') if mood else ""

            orientation_seg = ""
            if is_rear_facing:
                if is_looking_back:
                    orientation_seg = "CRITICAL: body faces away from camera but she looks back over her shoulder, face visible"
                else:
                    orientation_seg = "CRITICAL: NOT facing camera — back and rear face the lens, face hidden"

            segs = [
                (soul_line, True),
                (body_seg, True),
                (f"She wears {cloth_seg[0].lower() + cloth_seg[1:]}", True) if cloth_seg and not naked_override else (cloth_seg, True) if cloth_seg else ("", False),
                (orientation_seg, True) if is_rear_facing else ("", False),
                (f"Her hair is strictly {hair_seg} — no other color anywhere", True),
                (pose_seg, True),
                (f"Setting: {env_seg}" if env_seg else "", True),
                (light_seg, True),
                (face_seg, False),
                (f"{skin_seg}, completely tattoo-free" if self.opt_no_tattoos else skin_seg, False),
                (f"She is {action_seg[0].lower() + action_seg[1:]}" if action_seg else "", False),
                (f"{style_seg}" + (f"; {mood_seg}" if mood_seg else ""), True),
            ]
            words = 0
            kept = []
            for txt, must in segs:
                t = txt.strip()
                if not t:
                    continue
                t = t[0].upper() + t[1:]
                w = len(t.split())
                if must or words + w <= 150:
                    if t[-1] not in '.!?':
                        t += '.'
                    kept.append(t)
                    words += w
            return ' '.join(kept)

        if self.prompt_template == "Direct Attributes":
            # PRIORITY LAYER ON TOP — image models weight the start of the prompt most,
            # so fixed custom attributes lead and scene details follow.
            parts = []
            if is_rear_facing:
                if is_looking_back:
                    parts.append("[Orientation]: body faces away from camera but she is looking back over her shoulder at the camera, face visible")
                else:
                    parts.append("[Orientation]: NOT facing the camera — her back/rear faces the lens, face hidden or turned away, no eye contact, no front view")
            parts.append(f"[Body]: {self.get_body_description().strip().rstrip('.')}")
            parts.append(f"[Hair]: {self.get_hair_description()}")
            skin_txt = default_skin + (", completely tattoo-free" if self.opt_no_tattoos else "")
            parts.append(f"[Skin]: {skin_txt}" + (f" ({skin_details})" if skin_details and not is_rear_facing else ""))
            if clothing:
                parts.append(f"[Clothing]: {clothing}")
            if naked_override:
                parts.append(f"[Bare Skin]: {naked_override}")
            _pos_txt = detailed_pos if detailed_pos else (
                'Positioned with her back to the camera, body relaxed.' if is_rear_facing
                else 'Seated comfortably, body relaxed and open.'
            )
            parts.append(f"[Position]: {rear_line + '. ' if rear_line else ''}{_pos_txt}")
            if shot_angle:
                parts.append(f"[Shot Angle]: {shot_angle}")
            if action:
                parts.append(f"[Action]: {action}")
            env_val = environment.lower() if environment else 'intimate indoor space.'
            parts.append(f"[Environment]: {env_val if env_val.startswith('the setting') else 'The setting is ' + env_val}")
            parts.append(f"[Lighting]: {lighting if lighting else 'Soft natural light filters through.'}")
            if not is_rear_facing or is_looking_back:
                face_bits = " ".join(x for x in (facial, props) if x).strip()
                if face_bits:
                    parts.append(f"[Face & Props]: {face_bits}")
            elif is_rear_facing and not is_looking_back:
                parts.append("[Face]: Not visible — turned away from camera, hidden from view")
            if mood:
                parts.append(f"[Mood]: The mood is {mood.lower()}.")
            parts.append(f"[Style]: {', '.join(style_tags)}.")
            # Single compact hair lock — body/outfit already appear in [Body] and [Clothing] above
            parts.append(f"[Hair Lock]: strictly {lock_name} ({lock_hex}) — no highlights, streaks, ombre or any other color anywhere.")
            if is_rear_facing:
                if is_looking_back:
                    parts.append(f"[Pose Lock]: body faces away from camera but she looks back over her shoulder — do NOT make her body face the camera.")
                else:
                    parts.append(f"[Pose Lock]: back and rear face the camera — do NOT generate a front-facing view.")
            final_prompt = "\n".join(parts)
        else:
            parts = []

            # 1. Hair color — #1 drifted attribute, must be first
            fh = self._final_hair_hex()
            cn = self._describe_hair_color(int(fh[1:3], 16), int(fh[3:5], 16), int(fh[5:7], 16))
            bp = self.HAIR_BREAKPOINTS
            sv = self.hair_length
            if sv <= bp[0][0]:
                cut_label = bp[0][2]
            elif sv >= bp[-1][0]:
                cut_label = bp[-1][2]
            else:
                cut_label = bp[0][2]
                for i in range(len(bp) - 1):
                    lo, hi = bp[i], bp[i + 1]
                    if lo[0] <= sv <= hi[0]:
                        cut_label = lo[2] if (sv - lo[0]) / (hi[0] - lo[0]) < 0.5 else hi[2]
                        break
            style_phrase = hairstyle_phrase(self.hairstyle, self.hair_length)
            parts.append(
                f"HAIR: {cn} color, EXACT hex {fh} — ONLY this hair color, no blonde, no highlights, no other tones."
            )
            parts.append(
                f"Hair style: {cut_label}, styled in {style_phrase}."
            )

            # 2. Style & enhancements — early placement for image model attention
            parts.append(f"The image has {', '.join(style_tags)}")

            # 3. Pose & orientation
            if is_rear_facing:
                if is_looking_back:
                    parts.append("CRITICAL: Her body faces away from the camera but she is looking back over her shoulder at the camera, her face is visible")
                else:
                    parts.append("CRITICAL: She is NOT facing the camera — her back/rear is the side the camera sees, her face is hidden or turned away, no eye contact")
            if rear_line:
                parts.append(rear_line)
            if detailed_pos:
                parts.append(detailed_pos)
            else:
                if is_rear_facing:
                    parts.append("She is positioned with her back to the camera, her body relaxed")
                else:
                    parts.append("She is seated comfortably, her body relaxed and open, gaze directed toward the camera")
            if shot_angle:
                sa = shot_angle.strip().rstrip('.')
                parts.append(sa if re.match(r'^(the|she|her)\b', sa, re.IGNORECASE)
                             else f"The camera is {sa}")
            if action:
                a_txt = action.strip().rstrip('.')
                if not re.match(r'^(she|her)\b', a_txt, re.IGNORECASE):
                    a_txt = "She is " + a_txt[0].lower() + a_txt[1:]
                parts.append(a_txt)

            # 4. Body shape
            parts.append(self.get_body_description().strip().rstrip('.'))

            # 5. Clothing
            if clothing:
                parts.append(clothing)
            if naked_override:
                parts.append(naked_override)

            # 6. Skin tone (condensed)
            skin_txt = default_skin.strip().rstrip('.')
            if self.opt_no_tattoos:
                skin_txt += ", completely tattoo-free"
            parts.append(skin_txt)

            # 7. Environment + lighting (condensed)
            env_text = environment.lower() if environment else ''
            woman_pos_lower = woman_pos.lower() if woman_pos else ''
            if env_text and env_text not in woman_pos_lower:
                parts.append(f"The setting is {env_text if not env_text.startswith('the setting') else environment.lower()}")
            elif not env_text and 'setting' not in woman_pos_lower:
                parts.append("The setting is an intimate indoor space")
            if lighting:
                parts.append(lighting)
            else:
                parts.append("Soft natural light filters through")

            # 8. Face + mood (only when face is visible)
            if not is_rear_facing:
                face_bits = " ".join(x for x in (facial, skin_details, props) if x).strip()
                if face_bits:
                    fb = face_bits.rstrip('.')
                    if re.match(r'^(she|her)\b', fb, re.IGNORECASE):
                        parts.append(fb)
                    else:
                        parts.append("She has " + fb[0].lower() + fb[1:])
            if mood:
                parts.append(f"The mood is {mood.lower()}")

            joined = []
            for part in parts:
                part = part.strip()
                if not part:
                    continue
                if part[-1] not in '.!?':
                    part += '.'
                joined.append(part)
            final_prompt = ' '.join(joined)
            final_prompt = re.sub(r'\.\s*\.', '.', final_prompt)
            final_prompt = re.sub(r'\s+', ' ', final_prompt)

            # Tail reinforcement — hair color + pose lock
            tail = f"HAIR COLOR: {lock_name} {lock_hex} — ONLY this color, no blonde, no highlights, no other tones"
            if is_rear_facing:
                if is_looking_back:
                    tail += ". POSE: body faces away but she looks back over shoulder — do NOT show front-facing body"
                else:
                    tail += ". POSE: back and rear face the camera — do NOT generate front-facing view"
            final_prompt = final_prompt.rstrip('. ') + ". " + tail + "."

        return final_prompt + colors_block