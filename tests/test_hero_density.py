"""
Unit tests for the hero-image density selection helpers.

_hero_density_factor picks the density class from the screen's smaller
dimension (classic 320x240 -> 1.0; hdpi-class like the 480x320 3.5" panel
-> 1.5). _resolve_hero_src prefers native-density art and falls back to the
mdpi file with a runtime upscale when hdpi art doesn't exist, stripping the
LVGL "M:" driver prefix before probing the filesystem.

Usage:
    MPOS_HOME=/path/to/MicroPythonOS bash tests/unittest.sh tests/test_hero_density.py
"""

import sys
import unittest

# MPOS apps can shadow these in sys.modules — purge so we get the app's own.
for _m in ("displaywallet",):
    sys.modules.pop(_m, None)
import displaywallet
from displaywallet import _hero_density_factor, _resolve_hero_src


ICON_PATH = "M:apps/com.lightningpiggy.displaywallet/"


class TestHeroDensityFactor(unittest.TestCase):
    def test_classic_landscape(self):
        self.assertEqual(_hero_density_factor(320, 240), 1.0)

    def test_classic_portrait(self):
        self.assertEqual(_hero_density_factor(240, 320), 1.0)

    def test_hdpi_landscape(self):
        self.assertEqual(_hero_density_factor(480, 320), 1.5)

    def test_hdpi_portrait(self):
        self.assertEqual(_hero_density_factor(320, 480), 1.5)

    def test_min_dimension_governs(self):
        # A wide-but-short screen stays classic: the SMALL dimension rules.
        self.assertEqual(_hero_density_factor(480, 240), 1.0)


class TestResolveHeroSrc(unittest.TestCase):
    def test_mdpi_native_never_probes_fs(self):
        calls = []
        src, zoom = _resolve_hero_src(ICON_PATH, "lightningpiggy", 1.0, calls.append)
        self.assertEqual(src, ICON_PATH + "res/drawable-mdpi/hero_lightningpiggy.png")
        self.assertEqual(zoom, 256)
        self.assertEqual(calls, [])

    def test_hdpi_native_when_art_exists(self):
        probed = []
        def exists(p):
            probed.append(p)
            return True
        src, zoom = _resolve_hero_src(ICON_PATH, "lightningpiggy", 1.5, exists)
        self.assertEqual(src, ICON_PATH + "res/drawable-hdpi/hero_lightningpiggy.png")
        self.assertEqual(zoom, 256)
        # the filesystem probe must NOT carry the LVGL "M:" driver prefix
        self.assertEqual(probed, ["apps/com.lightningpiggy.displaywallet/res/drawable-hdpi/hero_lightningpiggy.png"])

    def test_mdpi_fallback_upscales(self):
        src, zoom = _resolve_hero_src(ICON_PATH, "lightningpenguin", 1.5, lambda p: False)
        self.assertEqual(src, ICON_PATH + "res/drawable-mdpi/hero_lightningpenguin.png")
        self.assertEqual(zoom, 384)  # int(256 * 1.5)


if __name__ == "__main__":
    unittest.main()
