"""Draw the app icon (map pin on the brand gradient) at the sizes Android, iOS and the manifest need.

Usage: .venv/bin/python scripts/make_icons.py [path/to/custom.png]
With a custom PNG (square, ≥512 px) the artwork is used instead of the drawn pin.
"""
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path("simera/web/icons")
C1, C2, C3 = (24, 36, 110), (52, 84, 214), (128, 66, 220)   # hero gradient
SS = 4  # supersampling for smooth edges


def gradient(size):
    img = Image.new("RGBA", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size)
            a, b, k = (C1, C2, t * 2) if t < .5 else (C2, C3, (t - .5) * 2)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3)) + (255,)
    # soft highlight top-left and glow bottom-right
    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse([-size * .3, -size * .35, size * .55, size * .5], fill=(255, 255, 255, 70))
    g.ellipse([size * .45, size * .55, size * 1.3, size * 1.4], fill=(255, 170, 230, 55))
    glow = glow.filter(ImageFilter.GaussianBlur(size * .18))
    return Image.alpha_composite(img, glow)


def pin(size, maskable=False):
    s = size * SS
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = s / 2, s * (.43 if maskable else .41)
    r = s * (.155 if maskable else .185)
    # location rings
    for k, alpha in ((2.05, 40), (1.55, 60)):
        d.ellipse([cx - r * k, cy + r * 2.15 - r * k * .38, cx + r * k, cy + r * 2.15 + r * k * .38], outline=(255, 255, 255, alpha), width=int(s * .012))
    # shadow
    sh = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(sh).ellipse([cx - r * 1.05, cy + r * 2.0, cx + r * 1.05, cy + r * 2.5], fill=(10, 10, 50, 110))
    layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(s * .025)))
    d = ImageDraw.Draw(layer)
    # pin body: head + tail
    ang = .66
    tip = (cx, cy + r * 2.25)
    left = (cx - r * math.cos(ang), cy + r * math.sin(ang))
    right = (cx + r * math.cos(ang), cy + r * math.sin(ang))
    d.polygon([left, right, tip], fill=(255, 255, 255, 255))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 255))
    # inner dot in brand blue, with a tiny gloss
    hole = r * .46
    d.ellipse([cx - hole, cy - hole, cx + hole, cy + hole], fill=C2)
    # gloss on the head
    gloss = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    ImageDraw.Draw(gloss).ellipse([cx - r * .9, cy - r * 1.0, cx + r * .2, cy - r * .35], fill=(255, 255, 255, 45))
    layer = Image.alpha_composite(layer, gloss.filter(ImageFilter.GaussianBlur(s * .02)))
    return layer.resize((size, size), Image.LANCZOS)


def icon(size, maskable=False, custom=None):
    base = gradient(size)
    if custom is not None:
        art = custom.convert("RGBA").resize((size, size), Image.LANCZOS)
        base = art if not maskable else Image.alpha_composite(base, art.resize((int(size * .8), int(size * .8)), Image.LANCZOS).crop((-int(size * .1), -int(size * .1), int(size * .9), int(size * .9))))
    else:
        base = Image.alpha_composite(base, pin(size, maskable))
    if maskable:
        return base
    mask = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size * SS - 1, size * SS - 1], radius=int(size * SS * .225), fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(base, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


if __name__ == "__main__":
    custom = Image.open(sys.argv[1]) if len(sys.argv) > 1 else None
    OUT.mkdir(parents=True, exist_ok=True)
    icon(192, custom=custom).save(OUT / "icon-192.png")
    icon(512, custom=custom).save(OUT / "icon-512.png")
    icon(512, maskable=True, custom=custom).save(OUT / "maskable-512.png")
    icon(180, custom=custom).save(OUT / "apple-touch-icon.png")
    print("icons written to", OUT)
