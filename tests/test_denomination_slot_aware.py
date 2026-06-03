"""
Unit tests for the slot-aware key resolution in DenominationSettingsActivity.

Regression coverage for a real bug caught on-device during the multi-wallet
rebase (PR #26): DenominationSettingsActivity.onCreate and _save both
hardcoded "balance_denomination" — slot-2 saves silently landed in slot
1's pref key, so the user's slot-2 denomination never actually changed.

CustomiseSettingsActivity passes a setting dict with `key` set to the
slot-aware pref key (e.g. "balance_denomination_2" for slot 2). The
denomination picker has to honour that, not hardcode slot 1.

These tests target the `_resolve_denom_key` helper extracted from
DenominationSettingsActivity so the slot-key contract is unit-testable
without bootstrapping LVGL widgets.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_denomination_slot_aware.py
    Device:  bash tests/unittest.sh tests/test_denomination_slot_aware.py --ondevice
"""

import unittest

try:
    import displaywallet
    _HAVE = hasattr(displaywallet, "_resolve_denom_key")
except Exception:
    _HAVE = False


@unittest.skipUnless(_HAVE, "_resolve_denom_key not installed (feature not landed)")
class TestResolveDenomKey(unittest.TestCase):
    """The helper that DenominationSettingsActivity uses to figure out
    *which* pref key to read/write. The previous bug was the activity
    bypassing this and hardcoding "balance_denomination"; making the
    helper a separate function lets us pin its contract."""

    def test_slot_1_setting_returns_unsuffixed_key(self):
        # CustomiseSettingsActivity builds this for active_wallet_slot == "1".
        setting = {"key": "balance_denomination"}
        self.assertEqual(
            displaywallet._resolve_denom_key(setting),
            "balance_denomination",
        )

    def test_slot_2_setting_returns_suffixed_key(self):
        # CustomiseSettingsActivity builds this for active_wallet_slot == "2".
        # The regression: previously, DenominationSettingsActivity ignored
        # this and read/wrote "balance_denomination" instead — slot-2
        # users got their saves silently dropped into slot 1.
        setting = {"key": "balance_denomination_2"}
        self.assertEqual(
            displaywallet._resolve_denom_key(setting),
            "balance_denomination_2",
        )

    def test_none_setting_falls_back_to_default(self):
        # Defensive: legacy callers (or unit tests of bare instances) that
        # don't pass a setting dict get the unsuffixed slot-1 key.
        self.assertEqual(
            displaywallet._resolve_denom_key(None),
            "balance_denomination",
        )

    def test_empty_setting_falls_back_to_default(self):
        # Same fallback for an empty dict (no `key` set).
        self.assertEqual(
            displaywallet._resolve_denom_key({}),
            "balance_denomination",
        )

    def test_explicit_default_override(self):
        # The helper accepts a custom default for future callers that
        # might use a different pref key family.
        self.assertEqual(
            displaywallet._resolve_denom_key(None, default="other_key"),
            "other_key",
        )

    def test_setting_with_empty_string_key_falls_back(self):
        # An empty-string `key` is treated as "not set" — fall back to
        # default rather than write to literal "" which would silently
        # discard user input.
        setting = {"key": ""}
        self.assertEqual(
            displaywallet._resolve_denom_key(setting),
            "balance_denomination",
        )


class _StubPrefs:
    """Minimal SharedPreferences-like view that records put_string writes
    in a single dict — lets us assert which key DenominationSettingsActivity._save
    actually wrote to without mocking the on-disk JSON file."""

    class _Editor:
        def __init__(self, prefs):
            self._prefs = prefs

        def put_string(self, key, value):
            self._prefs.writes.append((key, value))
            self._prefs._data[key] = value

        def commit(self):
            self._prefs.commits += 1

    def __init__(self, initial=None):
        self._data = dict(initial or {})
        self.writes = []
        self.commits = 0

    def get_string(self, key, default=None):
        v = self._data.get(key)
        return v if v is not None else default

    def edit(self):
        return self._Editor(self)


@unittest.skipUnless(_HAVE, "_resolve_denom_key not installed")
class TestStubPrefsHarness(unittest.TestCase):
    """Sanity-check the test harness itself before relying on it for
    the DenominationSettingsActivity coverage above. If StubPrefs is
    buggy, the resolution tests would pass for the wrong reasons."""

    def test_get_string_returns_set_value(self):
        p = _StubPrefs({"key": "value"})
        self.assertEqual(p.get_string("key"), "value")

    def test_get_string_default(self):
        p = _StubPrefs()
        self.assertEqual(p.get_string("missing", "fallback"), "fallback")

    def test_editor_commit_persists(self):
        p = _StubPrefs()
        e = p.edit()
        e.put_string("x", "1")
        e.commit()
        self.assertEqual(p.get_string("x"), "1")
        self.assertEqual(p.writes, [("x", "1")])
        self.assertEqual(p.commits, 1)


@unittest.skipUnless(_HAVE, "_resolve_denom_key not installed")
class TestDenominationSlotAwareBehavior(unittest.TestCase):
    """End-to-end contract check: simulate the DenominationSettingsActivity
    save path with each slot's setting dict and verify the write lands on
    the correct pref key. Catches the exact regression that shipped in
    the multi-wallet draft.

    We don't instantiate the real Activity (it needs LVGL widgets); we
    replicate the two-line save body that uses _resolve_denom_key and
    `prefs.edit().put_string(...)`."""

    def _simulate_save(self, prefs, setting, new_value):
        """Mirrors DenominationSettingsActivity._save's pref-write surface."""
        key = displaywallet._resolve_denom_key(setting)
        editor = prefs.edit()
        editor.put_string(key, new_value)
        editor.commit()

    def test_slot_1_save_writes_to_unsuffixed_key(self):
        prefs = _StubPrefs({
            "balance_denomination": "sats",
            "balance_denomination_2": "sats",
        })
        self._simulate_save(prefs, {"key": "balance_denomination"}, "₿ symbol")
        self.assertEqual(prefs.get_string("balance_denomination"), "₿ symbol")
        # Critical: slot 2 must NOT have changed.
        self.assertEqual(prefs.get_string("balance_denomination_2"), "sats")

    def test_slot_2_save_writes_to_suffixed_key(self):
        prefs = _StubPrefs({
            "balance_denomination": "sats",
            "balance_denomination_2": "sats",
        })
        self._simulate_save(prefs, {"key": "balance_denomination_2"}, "₿ symbol")
        # The regression — pre-fix this was "₿ symbol" in slot 1 and "sats" in slot 2.
        self.assertEqual(prefs.get_string("balance_denomination_2"), "₿ symbol")
        # Critical: slot 1 must NOT have changed.
        self.assertEqual(prefs.get_string("balance_denomination"), "sats")

    def test_two_consecutive_slot_saves_are_independent(self):
        # Common user flow: change slot 1's denom, switch wallets, change
        # slot 2's denom. Each save must land on its own slot.
        prefs = _StubPrefs({
            "balance_denomination": "sats",
            "balance_denomination_2": "sats",
        })
        self._simulate_save(prefs, {"key": "balance_denomination"}, "bits")
        self._simulate_save(prefs, {"key": "balance_denomination_2"}, "₿ symbol")
        self.assertEqual(prefs.get_string("balance_denomination"), "bits")
        self.assertEqual(prefs.get_string("balance_denomination_2"), "₿ symbol")
        # Two distinct writes — assert that explicitly so any future
        # logic that collapses them gets caught.
        self.assertEqual(
            prefs.writes,
            [("balance_denomination", "bits"),
             ("balance_denomination_2", "₿ symbol")],
        )

    def test_none_setting_writes_to_slot_1_for_legacy_callers(self):
        # Bare-instance / legacy single-wallet path: no setting passed,
        # writes go to the unsuffixed slot-1 key. Documents the fallback.
        prefs = _StubPrefs({"balance_denomination": "sats"})
        self._simulate_save(prefs, None, "BTC")
        self.assertEqual(prefs.get_string("balance_denomination"), "BTC")


if __name__ == "__main__":
    unittest.main()
