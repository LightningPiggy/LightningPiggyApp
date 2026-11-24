"""
Unit tests for fitting the hero name under the hero (`_hero_name_layout`).

The name used to be hard-truncated to 8 characters ("Super Coder" showed as
"Super Co") and on 480x320 screens the label ran 3 px off the bottom. Now the
whole name is shown when it fits right of the payments list and left of the
settings gear, with a font step down or "..." only when it doesn't.

Geometry below is absolute pixels. The first two are measured on real boards,
the portrait one is worked out from the layout code for a 240x320 panel:
  320x240 (Waveshare 2 inch): hero 224..303 x 112..211, payments end at 215,
      QR left 216, gear glyph x 294, y 212..234.
      "Super Coder" is 75 px at 12 pt, 63 px at 10 pt.
  480x320 (Waveshare 3.5 inch): hero 340..459 x 151..300, QR left 328,
      gear glyph x 445, y 283..311. "Super Coder" is 92 px at 14 pt.
  240x320 portrait (LilyGO T-HMI): hero 156..235 x 140..239, payments end at
      162, QR left 160, gear glyph x 208, y 285..310 (below the name row).

Usage:
    MPOS_HOME=/path/to/MicroPythonOS bash tests/unittest.sh tests/test_hero_name_fit.py
"""
import sys, unittest
for _m in ("displaywallet",):
    sys.modules.pop(_m, None)
import lvgl as lv
from displaywallet import _hero_name_layout, _text_size, _HERO_NAME_EDGE_MARGIN

MDPI = dict(hero_x1=224, hero_x2=303, hero_y2=211, left=216, gear=(294, 212, 234), screen_w=320, screen_h=240)
HDPI = dict(hero_x1=340, hero_x2=459, hero_y2=300, left=328, gear=(445, 283, 311), screen_w=480, screen_h=320)
PORTRAIT = dict(hero_x1=156, hero_x2=235, hero_y2=239, left=163, gear=(208, 285, 310), screen_w=240, screen_h=320)


def layout(widths, heights, g):
    return _hero_name_layout(widths, heights, g["hero_x1"], g["hero_x2"], g["hero_y2"],
                             g["left"], g["gear"], g["screen_w"], g["screen_h"])


def gear_right(g):
    return g["gear"][0] - _HERO_NAME_EDGE_MARGIN


class TestHeroNameFit(unittest.TestCase):
    def test_short_name_is_centred_under_hero(self):
        index, x1, y1, width, dots = layout([40, 34], [16, 11], MDPI)
        self.assertEqual((index, width, dots), (0, 40, False))
        self.assertEqual(x1, (224 + 303 + 1 - 40) // 2)

    def test_super_coder_fits_whole_on_mdpi_slid_left_of_gear(self):
        index, x1, y1, width, dots = layout([75, 63], [16, 11], MDPI)
        self.assertEqual((index, width, dots), (0, 75, False))
        self.assertEqual(x1, gear_right(MDPI) - 75 + 1)  # 218, measured on the board

    def test_super_coder_fits_whole_on_hdpi(self):
        index, x1, y1, width, dots = layout([92, 75], [18, 16], HDPI)
        self.assertEqual((index, width, dots), (0, 92, False))
        self.assertEqual(x1, gear_right(HDPI) - 92 + 1)  # 352, measured on the board

    def test_hdpi_label_stays_on_screen(self):
        index, x1, y1, width, dots = layout([92, 75], [18, 16], HDPI)
        self.assertEqual(y1, 301)  # was 306..323 on a 320 px screen
        self.assertTrue(y1 + 18 <= HDPI["screen_h"])

    def test_mdpi_keeps_the_5px_gap(self):
        index, x1, y1, width, dots = layout([75, 63], [16, 11], MDPI)
        self.assertEqual(y1, MDPI["hero_y2"] + 1 + 5)

    def test_steps_down_a_font_when_needed(self):
        index, x1, y1, width, dots = layout([85, 70], [16, 11], MDPI)
        self.assertEqual((index, width, dots), (1, 70, False))
        self.assertEqual(x1, gear_right(MDPI) - 70 + 1)

    def test_too_long_uses_dots_in_full_width(self):
        index, x1, y1, width, dots = layout([200, 160], [16, 11], MDPI)
        self.assertEqual((index, dots), (1, True))
        self.assertEqual(x1, MDPI["left"])
        self.assertEqual(width, gear_right(MDPI) - MDPI["left"] + 1)

    def test_exact_fit_does_not_use_dots(self):
        avail = gear_right(MDPI) - MDPI["left"] + 1
        index, x1, y1, width, dots = layout([avail, 50], [16, 11], MDPI)
        self.assertEqual((index, x1, width, dots), (0, MDPI["left"], avail, False))

    def test_tall_font_with_no_room_sits_on_bottom_edge(self):
        g = dict(MDPI, hero_y2=230)
        index, x1, y1, width, dots = layout([40, 34], [16, 11], g)
        self.assertEqual(y1, 240 - 16)

    def test_gear_below_the_name_row_does_not_limit_it(self):
        # Portrait: the name row (y 245..260) is above the gear (y 285..310),
        # so the screen edge is the limit and "Super Coder" fits whole.
        index, x1, y1, width, dots = layout([75, 63], [16, 11], PORTRAIT)
        self.assertEqual((index, width, dots), (0, 75, False))
        self.assertEqual(y1, 245)
        self.assertTrue(x1 >= PORTRAIT["left"])
        self.assertTrue(x1 + width - 1 <= PORTRAIT["screen_w"] - 1 - _HERO_NAME_EDGE_MARGIN)

    def test_never_starts_inside_the_payments_list(self):
        index, x1, y1, width, dots = layout([200, 160], [16, 11], PORTRAIT)
        self.assertTrue(dots)
        self.assertEqual(x1, PORTRAIT["left"])


class TestTextSize(unittest.TestCase):
    def test_measures_one_line(self):
        w, h = _text_size("Super Coder", lv.font_montserrat_12)
        self.assertEqual(w, 75)  # same as measured on the boards
        self.assertEqual(h, lv.font_montserrat_12.line_height)

    def test_longer_text_is_wider(self):
        self.assertTrue(_text_size("Super Coder Piggy", lv.font_montserrat_12)[0] > 75)


if __name__ == "__main__":
    unittest.main()
