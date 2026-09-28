"""Lock in the pure body / hair / skin / color description logic."""
import re

from studio.text import body_parts, clean_text_advanced, describe_hair_color, final_hair_hex
from studio.text import hex_to_rgb, strip_front_facing_sentences


# ---------------- body ----------------
def test_body_large_breakpoints(studio):
    studio.breast_size = 100
    studio.hip_size = 100
    d = studio.get_body_description()
    assert "oversized breasts" in d
    assert "extremely wide" in d


def test_body_small_breakpoints(studio):
    studio.breast_size = 5
    studio.hip_size = 5
    d = studio.get_body_description()
    assert "small, modest breasts" in d
    assert "slim, narrow hips" in d


def test_body_midpoint(studio):
    studio.breast_size = 50
    studio.hip_size = 50
    d = studio.get_body_description()
    assert "full, prominent breasts" in d
    assert "curved hips that flare" in d


def test_opt_safe_suppresses_explicit_wording(studio):
    """The Safe wording toggle used to be ignored on the main Generate path."""
    studio.breast_size = 100
    studio.hip_size = 100
    studio.opt_safe = False
    explicit = studio.get_body_description()
    studio.opt_safe = True
    safe = studio.get_body_description()

    assert "oversized breasts" in explicit
    assert "breasts" not in safe
    assert "curvaceous" in safe


def test_opt_safe_still_tracks_slider_extremes(studio):
    """Safe wording must still respond to the sliders, not collapse to one string."""
    studio.opt_safe = True
    studio.breast_size, studio.hip_size = 0, 0
    small = studio.get_body_description()
    studio.breast_size, studio.hip_size = 100, 100
    large = studio.get_body_description()
    assert small != large
    assert "delicate frame" in small
    assert "curvaceous" in large


def test_body_parts_returns_figure_label():
    assert body_parts(10, 10)[2] == "slender"
    assert body_parts(50, 50)[2] == "athletic"
    assert body_parts(100, 100)[2] == "curvy hourglass"


def test_body_parts_safe_and_explicit_differ():
    assert body_parts(100, 100, safe=True) != body_parts(100, 100, safe=False)


# ---------------- hair ----------------
def test_hair_short(studio):
    studio.hair_length = 0
    d = studio.get_hair_description()
    assert "buzz-cut" in d
    assert "inches" in d and "cm" in d


def test_hair_long(studio):
    studio.hair_length = 100
    d = studio.get_hair_description()
    assert "floor-length" in d


def test_hair_interpolation(studio):
    studio.hair_length = 50
    d = studio.get_hair_description()
    assert "Her hair is" in d
    assert re.search(r"\d+\.?\d* inches", d)


def test_final_hair_hex_uppercase(studio):
    studio.hair_base_color = "#4A2C1A"
    hx = studio._final_hair_hex()
    assert re.match(r"^#[0-9A-F]{6}$", hx)


def test_final_hair_hex_brightness_monotonic():
    low = final_hair_hex("#4A2C1A", 0)
    high = final_hair_hex("#4A2C1A", 100)
    low_r = int(low[1:3], 16)
    high_r = int(high[1:3], 16)
    assert high_r >= low_r


def test_hex_to_rgb():
    assert hex_to_rgb("#4A2C1A") == (0x4A, 0x2C, 0x1A)


def test_describe_hair_color_buckets():
    assert describe_hair_color(0, 0, 0) == "jet matte black"
    assert describe_hair_color(255, 255, 255) == "flat pure white"
    assert describe_hair_color(255, 0, 0) == "auburn red"
    assert describe_hair_color(0, 255, 0) == "vivid fantasy green"
    assert describe_hair_color(0, 0, 255) == "ice blue"


# ---------------- skin ----------------
def test_skin_realism(studio):
    studio.opt_realism = True
    d = studio.get_skin_description()
    assert "visible pores" in d


def test_skin_non_realism(studio):
    studio.opt_realism = False
    d = studio.get_skin_description()
    assert "pores" not in d


# ---------------- text utilities ----------------
def test_clean_text_advanced():
    assert clean_text_advanced("**bold** *ital* # Heading\nKeep this") == "Keep this"


def test_strip_front_facing_sentences():
    text = "She is looking at the camera. She stands by the window."
    assert "window" in strip_front_facing_sentences(text)
    assert "looking at the camera" not in strip_front_facing_sentences(text)