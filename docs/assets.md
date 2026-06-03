# Image asset format

This document defines the PNG format requirements for assets bundled with
LightningPiggyApp (and any LP fork). It is the **canonical source of truth**
for how PNG files in `com.lightningpiggy.displaywallet/res/` must be encoded.

---

## TL;DR

All PNG files under `com.lightningpiggy.displaywallet/res/drawable-mdpi/`
and `com.lightningpiggy.displaywallet/res/mipmap-mdpi/` must be saved as
**indexed-palette PNG** (PIL/Pillow mode `P`, identified by `file(1)` as
`8-bit colormap` or `4-bit colormap`).

**8-bit RGBA PNGs do NOT render on MicroPythonOS 0.10.0** — `lv.image.set_src()`
returns success, no error is printed, but the image widget stays at 0×0
and nothing draws. The MPOS-bundled lodepng decoder silently rejects
RGBA color type 6.

---

## Why indexed-palette only

The LVGL `lodepng` decoder shipped in MicroPythonOS 0.10.0 (and the
upstream lvgl-micropython build it's based on) does not produce pixels
for 8-bit RGBA PNGs in this build configuration. The exact root cause
(probably `LV_COLOR_DEPTH=16` interplay with RGBA→RGB565 alpha-blending)
is unresolved upstream; tracked at
[MicroPythonOS#140](https://github.com/MicroPythonOS/MicroPythonOS/issues/140).

Indexed PNGs (color type 3) work correctly — palette entries can include
an alpha channel via the `tRNS` chunk, so transparency is preserved.
For LP's mascot artwork (small, cartoony, limited palette) the visual
difference between 8-bit RGBA and 8-bit indexed is invisible at the
80×100 sizes used on the device.

---

## Converting an existing PNG

```python
from PIL import Image
img = Image.open("hero_lightningpiggy.png")
# colors=255 reserves slot 0 for the transparent palette entry, so up to
# 255 opaque colors fit in the remaining slots. method=2 (FASTOCTREE)
# preserves the alpha channel; the default method drops it.
img.quantize(colors=255, method=2, dither=Image.Dither.FLOYDSTEINBERG)\
   .save("hero_lightningpiggy.png", optimize=True)
```

Verify:

```sh
file hero_lightningpiggy.png
# expected: PNG image data, ..., 8-bit colormap, non-interlaced
```

---

## CI / pre-commit check

`scripts/check_png_format.py` walks the `res/` tree and exits non-zero
if any file is encoded as `RGBA` or `RGB` (truecolor). Run it before
committing new artwork:

```sh
python3 scripts/check_png_format.py
```

Add it to your local pre-commit hook if you frequently add or edit assets.

---

## What "works" and what doesn't

| PNG color type             | PIL mode | `file(1)` reports         | Renders on MPOS 0.10.0 |
|----------------------------|----------|---------------------------|------------------------|
| 0  (grayscale)             | `L`      | `... grayscale ...`       | ✓                     |
| 2  (RGB truecolor)         | `RGB`    | `8-bit/color RGB`         | ✓                     |
| 3  (indexed-palette)       | `P`      | `8-bit colormap` *(or 4)* | ✓ — preferred         |
| 4  (grayscale + alpha)     | `LA`     | `... grayscale + alpha`   | ✓                     |
| 6  (RGBA truecolor)        | `RGBA`   | `8-bit/color RGBA`        | ✗ silently 0×0         |

Pin all `res/` artwork to color type 3 (indexed) for consistency and to
keep transparency working without relying on the truecolor-RGBA path.

---

## When the upstream MPOS bug is fixed

Once MicroPythonOS ships a build that renders 8-bit RGBA PNGs correctly,
this restriction can be relaxed — but until then, the indexed-PNG
constraint is mandatory and the CI check should stay in place.
