"""Lock in the curated preset dictionaries in studio.config."""
from studio import config


def test_hairstyle_count_and_default():
    assert len(config.HAIRSTYLES) == 18
    assert config.HAIRSTYLE_DEFAULT == "Deep Side Part (Voluminous)"


def test_new_hairstyles_present():
    for name in ("Curtain Bangs", "High Ponytail", "Box Braids", "Space Buns",
                 "Half-Up Half-Down", "Wet Look Slick"):
        assert name in config.HAIRSTYLES


def test_hairstyle_phrases_nonempty():
    assert all(v.strip() for v in config.HAIRSTYLES.values())


def test_skin_tone_count():
    assert len(config.SKIN_TONES) == 19
    assert config.SKIN_TONE_DEFAULT == "Warm Tan (Default)"
    for name in ("Warm Ivory", "Golden Caramel", "Deep Mahogany", "Cool Ebony"):
        assert name in config.SKIN_TONES


def test_hair_color_preset_count():
    assert len(config.HAIR_COLOR_PRESETS) == 21


def test_hair_color_presets_hex():
    import re
    for name, hx in config.HAIR_COLOR_PRESETS:
        assert re.match(r"^#[0-9A-F]{6}$", hx), (name, hx)


def test_new_presets_usable_in_studio(studio):
    studio.hairstyle = "High Ponytail"
    studio.skin_tone = "Golden Caramel"
    desc = studio.get_hair_description() + " " + studio.get_skin_description()
    assert "ponytail" in desc.lower()
    assert "caramel" in desc.lower()