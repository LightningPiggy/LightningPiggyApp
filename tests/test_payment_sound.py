"""
Unit tests for the payment sound effect chooser.

_pick_payment_sound maps the `payment_sound` pref to a WAV path: "off" (and
anything unknown) is silence, each named sound maps to its file, and
"random" picks one of the named sounds via an injectable chooser.

Usage:
    MPOS_HOME=/path/to/MicroPythonOS bash tests/unittest.sh tests/test_payment_sound.py
"""

import sys
import unittest

for _m in ("displaywallet",):
    sys.modules.pop(_m, None)
from displaywallet import _pick_payment_sound, _payment_sound_label, PAYMENT_SOUND_OPTIONS, _SOUND_DIR


class TestPickPaymentSound(unittest.TestCase):
    def test_off_is_silent(self):
        self.assertIsNone(_pick_payment_sound("off"))

    def test_unknown_is_silent(self):
        self.assertIsNone(_pick_payment_sound("moo"))
        self.assertIsNone(_pick_payment_sound(""))
        self.assertIsNone(_pick_payment_sound(None))

    def test_named_sounds(self):
        self.assertEqual(_pick_payment_sound("oink"), _SOUND_DIR + "pig_oink.wav")
        self.assertEqual(_pick_payment_sound("squeal"), _SOUND_DIR + "pig_squeal.wav")
        self.assertEqual(_pick_payment_sound("hungry"), _SOUND_DIR + "pig_hungry.wav")

    def test_random_uses_chooser_over_named_sounds(self):
        offered = []
        def chooser(seq):
            offered.extend(seq)
            return "squeal"
        self.assertEqual(_pick_payment_sound("random", chooser), _SOUND_DIR + "pig_squeal.wav")
        self.assertEqual(sorted(offered), ["hungry", "oink", "squeal"])

    def test_random_default_chooser_yields_a_real_sound(self):
        for _ in range(20):
            self.assertIn(_pick_payment_sound("random"),
                          (_SOUND_DIR + "pig_oink.wav", _SOUND_DIR + "pig_squeal.wav", _SOUND_DIR + "pig_hungry.wav"))

    def test_labels(self):
        self.assertEqual(_payment_sound_label("oink"), "Pig Oink")
        self.assertEqual(_payment_sound_label("hungry"), "Hungry Pig")
        self.assertEqual(_payment_sound_label("random"), "Random")
        self.assertEqual(_payment_sound_label("off"), "Off")
        self.assertEqual(_payment_sound_label("bogus"), "Off")

    def test_picker_options_cover_every_file_plus_off_and_random(self):
        values = [v for _, v in PAYMENT_SOUND_OPTIONS]
        self.assertEqual(values, ["off", "oink", "squeal", "hungry", "random"])


if __name__ == "__main__":
    unittest.main()
