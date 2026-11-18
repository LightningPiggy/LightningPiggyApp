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
from displaywallet import _pick_payment_sound, _payment_sound_label, _payment_sound_output, PAYMENT_SOUND_OPTIONS, _SOUND_DIR


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


class _Output:
    def __init__(self, name, kind, buzzer_gain=None):
        self.name = name
        self.kind = kind
        if buzzer_gain is not None:
            self.buzzer_gain = buzzer_gain  # only MicroPythonOS 0.22.0+ outputs have it


class _Audio:
    """Stands in for the AudioManager class: a default output and an output list."""

    def __init__(self, outputs, default=None, default_raises=False):
        self.outputs = outputs
        self.default = default
        self.default_raises = default_raises

    def get_default_output(self):
        if self.default_raises:
            raise AttributeError("no get_default_output on this firmware")
        return self.default

    def find_output_by_kind(self, kind):
        for output in self.outputs:
            if output.kind == kind:
                return output
        return None


class TestPaymentSoundOutput(unittest.TestCase):
    def test_chosen_speaker_is_used(self):
        a = _Output("speaker A", "i2s")
        b = _Output("speaker B", "i2s")
        self.assertIs(_payment_sound_output(_Audio([a, b], default=b)), b)

    def test_chosen_buzzer_is_used_when_it_can_play_files(self):
        speaker = _Output("speaker", "i2s")
        buzzer = _Output("buzzer", "buzzer", buzzer_gain=800)
        self.assertIs(_payment_sound_output(_Audio([buzzer, speaker], default=buzzer)), buzzer)

    def test_buzzer_only_board_plays_on_new_firmware(self):
        buzzer = _Output("buzzer", "buzzer", buzzer_gain=800)
        self.assertIs(_payment_sound_output(_Audio([buzzer], default=buzzer)), buzzer)

    def test_chosen_buzzer_on_old_firmware_falls_back_to_speaker(self):
        speaker = _Output("speaker", "i2s")
        buzzer = _Output("buzzer", "buzzer")
        self.assertIs(_payment_sound_output(_Audio([buzzer, speaker], default=buzzer)), speaker)

    def test_buzzer_only_board_on_old_firmware_is_silent(self):
        buzzer = _Output("buzzer", "buzzer")
        self.assertIsNone(_payment_sound_output(_Audio([buzzer], default=buzzer)))

    def test_no_outputs_is_silent(self):
        self.assertIsNone(_payment_sound_output(_Audio([])))

    def test_failing_default_lookup_falls_back_to_speaker(self):
        speaker = _Output("speaker", "i2s")
        self.assertIs(_payment_sound_output(_Audio([speaker], default_raises=True)), speaker)

    def test_unknown_output_kind_falls_back_to_speaker(self):
        speaker = _Output("speaker", "i2s")
        other = _Output("bluetooth", "a2dp")
        self.assertIs(_payment_sound_output(_Audio([other, speaker], default=other)), speaker)


if __name__ == "__main__":
    unittest.main()
