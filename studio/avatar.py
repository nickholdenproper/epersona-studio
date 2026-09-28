"""2D avatar preview compositor.

Mixin so `avatar_png` keeps `self` access, while accepting optional numeric
overrides so the HTTP preview endpoint no longer has to mutate the shared
Studio singleton.
"""
import io
import os

from PIL import Image, ImageDraw

from .config import AVATAR_DIR
from .text import final_hair_hex


class AvatarMixin:

    def avatar_png(self, cw=250, ch=400, breast=None, hips=None, hair_len=None,
                   hair_brightness=None, hair_color=None):
        variants_4 = [(25, '-R1C1.png'), (50, '-R1C2.png'), (75, '-R1C3.png'), (100, '-R1C4.png')]

        breast_size = self.breast_size if breast is None else breast
        hip_size = self.hip_size if hips is None else hips
        hair_length = self.hair_length if hair_len is None else hair_len
        brightness = self.hair_brightness if hair_brightness is None else hair_brightness
        base_color = self.hair_base_color if hair_color is None else hair_color

        def file_for(kind_prefix, row, val):
            for threshold, fname in variants_4:
                if val <= threshold:
                    return os.path.join(AVATAR_DIR, f"{kind_prefix}-R{row}" + fname.replace('-R1', ''))
            # Unreachable: the last variant_4 threshold is 100 and `val` is
            # clamped to 0-100 by settings.apply_updates.

        def load_layer(path):
            if not path or not os.path.exists(path):
                return None
            with Image.open(path) as src:
                img = src.convert('RGBA')
            img.thumbnail((cw, ch), Image.Resampling.LANCZOS)
            px = img.load()
            for y in range(img.height):
                for x in range(img.width):
                    r, g, b, a = px[x, y]
                    if 10 <= a < 255:
                        sf = 255.0 / a
                        px[x, y] = (min(255, int(r * sf)), min(255, int(g * sf)), min(255, int(b * sf)), a)
                    elif a < 10:
                        px[x, y] = (255, 255, 255, a)
            layer = Image.new('RGBA', (cw, ch), (0, 0, 0, 0))
            x = (cw - img.width) // 2
            y = (ch - img.height) // 2
            layer.paste(img, (x, y), img)
            return layer

        bust_file = file_for('bust', 1, breast_size)
        hips_file = file_for('hips', 2, hip_size)
        hair_file = file_for('hairsize', 3, hair_length)

        fh = final_hair_hex(base_color, brightness)
        hc_rgb = (int(fh[1:3], 16), int(fh[3:5], 16), int(fh[5:7], 16))

        canvas = Image.new('RGBA', (cw, ch), (255, 255, 255, 255))
        for pth in [os.path.join(AVATAR_DIR, 'Base.png'), hips_file, bust_file, hair_file]:
            layer = load_layer(pth)
            if layer:
                canvas = Image.alpha_composite(canvas, layer)

        hc = hc_rgb + (255,)
        d = ImageDraw.Draw(canvas)
        d.ellipse([8, 8, 30, 30], fill=hc, outline=(200, 200, 200, 255))

        buf = io.BytesIO()
        canvas.convert('RGB').save(buf, format='PNG')
        return buf.getvalue()