import io

from PIL import Image

from studio.studio import Studio


def _rgb_pixels(png, crop=None):
    with Image.open(io.BytesIO(png)) as src:
        im = src.convert("RGB")
    if crop:
        im = im.crop(crop)
    flat = getattr(im, "get_flattened_data", im.getdata)
    return list(flat())


def test_avatar_same_settings_deterministic(studio):
    a = studio.avatar_png()
    b = studio.avatar_png()
    assert isinstance(a, bytes) and len(a) > 100
    assert a == b


def test_avatar_hair_color_only_changes_circle(studio):
    red = studio.avatar_png(hair_color="#FF0000")
    blue = studio.avatar_png(hair_color="#0000FF")
    assert red != blue  # the color circle differs

    # Everything outside the color circle is identical — no hair recolor.
    assert _rgb_pixels(red, crop=(40, 0, 250, 400)) == _rgb_pixels(blue, crop=(40, 0, 250, 400))

    # The circle itself shows the exact hair color.
    dot = _rgb_pixels(red, crop=(0, 0, 40, 40))
    assert any(r > 200 and g < 60 and b < 60 for r, g, b in dot)
    dot_blue = _rgb_pixels(blue, crop=(0, 0, 40, 40))
    assert any(b > 200 and r < 60 and g < 60 for r, g, b in dot_blue)