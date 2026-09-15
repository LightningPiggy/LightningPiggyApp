"""
Unit tests for the Payment Animation setting helper.

`payment_animation` pref: "none" disables the confetti burst on a received
payment; "confetti" (default) and anything unknown keep it, so a stale or
mistyped pref never silently turns the celebration off.

Usage:
    python3 scripts/test_runner.py --tests-dir <app assets dir> tests/test_payment_animation.py
"""
import sys, unittest
for _m in ("displaywallet",):
    sys.modules.pop(_m, None)
from displaywallet import _payment_animation_enabled, PAYMENT_ANIMATION_OPTIONS

class TestPaymentAnimation(unittest.TestCase):
    def test_none_disables(self):
        self.assertFalse(_payment_animation_enabled("none"))

    def test_confetti_enables(self):
        self.assertTrue(_payment_animation_enabled("confetti"))

    def test_unknown_and_empty_keep_confetti(self):
        self.assertTrue(_payment_animation_enabled(""))
        self.assertTrue(_payment_animation_enabled("sparkles"))
        self.assertTrue(_payment_animation_enabled(None))

    def test_options(self):
        self.assertEqual([v for _, v in PAYMENT_ANIMATION_OPTIONS], ["none", "confetti"])

if __name__ == "__main__":
    unittest.main()
