#!/usr/bin/env python3
"""Verify every PNG under com.lightningpiggy.displaywallet/res/ is encoded
as indexed-palette (or grayscale), not RGBA / RGB.

Background: MicroPythonOS 0.10.0's lodepng decoder silently fails on
8-bit RGBA PNGs — `lv.image.set_src()` returns success, no error is
printed, the image widget stays at 0×0, and nothing draws. Indexed PNGs
work. See docs/assets.md.

Exits 0 if all PNGs comply, 1 otherwise. Suitable for a pre-commit
hook or CI step:

    python3 scripts/check_png_format.py

Reads each PNG's IHDR chunk directly (no Pillow dependency) so this can
run on a fresh checkout without `pip install`.
"""

from __future__ import annotations

import os
import struct
import sys


# PNG color type values from the spec (RFC 2083 §4.1.1).
_COLOR_TYPE_NAMES = {
    0: "grayscale",
    2: "RGB truecolor",
    3: "indexed-palette",
    4: "grayscale + alpha",
    6: "RGBA truecolor",
}

# Color types the MPOS lodepng decoder is known to render. Anything else
# fails silently and must be re-encoded.
_ALLOWED_COLOR_TYPES = {0, 2, 3, 4}


def _read_ihdr(path: str) -> tuple[int, int, int, int]:
    """Return (width, height, bit_depth, color_type) from a PNG's IHDR.

    Raises ValueError if the file isn't a PNG or the IHDR chunk is
    malformed.
    """
    with open(path, "rb") as f:
        header = f.read(33)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG file")
    # bytes 8..16: chunk length (4) + type "IHDR" (4)
    # bytes 16..24: width (4) + height (4)
    # byte 24: bit depth; byte 25: color type
    if header[12:16] != b"IHDR":
        raise ValueError("first chunk is not IHDR")
    width, height = struct.unpack(">II", header[16:24])
    bit_depth = header[24]
    color_type = header[25]
    return width, height, bit_depth, color_type


def main() -> int:
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res_root = os.path.join(
        repo_root, "com.lightningpiggy.displaywallet", "res"
    )
    if not os.path.isdir(res_root):
        print(
            "check_png_format: res/ not found at {} — nothing to check"
            .format(res_root),
            file=sys.stderr,
        )
        return 0

    bad: list[tuple[str, str]] = []
    checked = 0
    for dirpath, _dirs, files in os.walk(res_root):
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            path = os.path.join(dirpath, name)
            try:
                _w, _h, _bd, ct = _read_ihdr(path)
            except (OSError, ValueError) as e:
                bad.append((path, "unreadable: {}".format(e)))
                continue
            checked += 1
            if ct not in _ALLOWED_COLOR_TYPES:
                bad.append((
                    path,
                    "color type {} ({}) — re-encode as indexed-palette"
                    .format(ct, _COLOR_TYPE_NAMES.get(ct, "unknown")),
                ))

    if bad:
        print(
            "check_png_format: {} PNG(s) failed format check:\n"
            .format(len(bad)),
            file=sys.stderr,
        )
        for path, reason in bad:
            print("  {}: {}".format(os.path.relpath(path, repo_root), reason),
                  file=sys.stderr)
        print(
            "\nTo fix, re-encode each file as indexed-palette PNG. Example:\n"
            "  python3 -c \"from PIL import Image; img=Image.open('PATH');\\\n"
            "    img.quantize(colors=255, method=2,\\\n"
            "      dither=Image.Dither.FLOYDSTEINBERG)\\\n"
            "      .save('PATH', optimize=True)\"\n"
            "\nSee docs/assets.md for the full rationale.",
            file=sys.stderr,
        )
        return 1

    print("check_png_format: OK ({} PNGs checked, all indexed/grayscale/RGB)"
          .format(checked))
    return 0


if __name__ == "__main__":
    sys.exit(main())
