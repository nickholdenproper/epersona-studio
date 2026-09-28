"""TTS mode — strip body/hair from a pasted prompt and re-inject current settings.

Pure function taking the Studio state object, so it can be unit-tested.
"""
import re


def tts_transform(studio, raw):
    if not raw:
        raise ValueError("Paste a prompt first")

    def remove_sentence_containing(text, keywords):
        sentences = re.split(r'(?<=[.!?])(?=\s+[A-Z"\'\(]|$)', text)
        kept = []
        for s in sentences:
            s_stripped = s.strip()
            if not s_stripped:
                continue
            tl = s_stripped.lower()
            if any(k in tl for k in keywords):
                continue
            kept.append(s_stripped)
        return ' '.join(kept)

    body_kw = ['breast', 'bust', 'cleavage', 'hip', 'waist', 'hourglass',
               'curvy', 'voluptuous', 'buxom', 'shapely', 'backside', 'buttocks', 'derriere', 'thigh']
    hair_kw = ['hair', 'curls', 'bob', 'pixie', 'ponytail', 'braid', 'bun', 'updo',
               'locks', 'tresses', 'mane', 'strands', 'blonde', 'brunette', 'auburn']

    cleaned = remove_sentence_containing(raw, body_kw)
    cleaned = remove_sentence_containing(cleaned, hair_kw)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    cleaned = re.sub(r'\.\s*\.+', '.', cleaned)
    cleaned = re.sub(r'^[.,;\s]+', '', cleaned)
    cleaned = re.sub(r'[.,;\s]+$', '', cleaned)

    body_text = studio.get_body_description()
    hair_text = studio.get_hair_description()
    skin_text = studio.get_skin_description()

    hex_idx = cleaned.find('HEX VALUES:')
    if hex_idx > 0:
        before = cleaned[:hex_idx].rstrip().rstrip('.')
        after = cleaned[hex_idx:]
        result = f"{before}. {body_text}. {hair_text}. {skin_text} {after}"
    else:
        result = f"{cleaned}. {body_text}. {hair_text}. {skin_text}"
    result = re.sub(r'\.\s*\.+', '.', result)
    result = re.sub(r'\s+', ' ', result).strip()
    return {'result': result}