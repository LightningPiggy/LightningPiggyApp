"""
Unit tests for the density-aware font step.

Header fonts (balance number, unit suffix, bolt, gear, hero name) step up one
built-in Montserrat size on hdpi-class screens; the balance underline moves
down with the taller number. mdpi screens are unchanged.

Usage:
    MPOS_HOME=/path/to/MicroPythonOS bash tests/unittest.sh tests/test_font_density.py
"""
import sys, unittest
for _m in ("displaywallet",):
    sys.modules.pop(_m, None)
from displaywallet import _density_font_size, _balance_underline_y, _HDPI_FONT_STEP

class TestDensityFontStep(unittest.TestCase):
    def test_mdpi_is_identity(self):
        for b in (8, 10, 12, 14, 16, 18, 20, 24, 28):
            self.assertEqual(_density_font_size(b, 1.0), b)

    def test_hdpi_header_sizes(self):
        self.assertEqual(_density_font_size(24, 1.5), 28)  # balance number, bolt
        self.assertEqual(_density_font_size(16, 1.5), 20)  # unit suffix
        self.assertEqual(_density_font_size(18, 1.5), 24)  # gear
        self.assertEqual(_density_font_size(12, 1.5), 14)  # hero name

    def test_hdpi_never_exceeds_compiled_max(self):
        self.assertEqual(_density_font_size(28, 1.5), 28)
        self.assertTrue(all(v <= 28 for v in _HDPI_FONT_STEP.values()))

    def test_only_compiled_sizes_are_produced(self):
        compiled = {8, 10, 12, 14, 16, 18, 20, 24, 28}
        self.assertTrue(set(_HDPI_FONT_STEP.values()) <= compiled)

    def test_unknown_base_passes_through(self):
        self.assertEqual(_density_font_size(22, 1.5), 22)

    def test_underline_follows_density(self):
        self.assertEqual(_balance_underline_y(1.0), 35)
        self.assertEqual(_balance_underline_y(1.5), 41)
        self.assertEqual(_balance_underline_y(2.0), 35)  # unknown factor: safe default

if __name__ == "__main__":
    unittest.main()
