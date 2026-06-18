"""
Unit tests for auto-activating a newly-added wallet slot.

When the user adds a wallet to a slot that had no runnable credentials
(e.g. configuring the on-chain wallet in slot 2), the device should open
into that new wallet instead of staying on the previously-active slot.
WalletSettingsActivity._maybe_activate_added_wallet implements this:
it flips `active_wallet_slot` to the slot once it transitions from
unconfigured -> configured, but leaves it alone when merely editing an
already-configured slot.

Both the pure credential check (_slot_credentials_present) and the
switch decision (the method, called unbound against a stub) are tested
with a fake SharedPreferences.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_wallet_slot_activation.py
"""

import sys
import unittest

# MPOS apps can shadow these in sys.modules — purge so we get the app's own.
for _m in ("displaywallet", "nostr_service", "nwc_wallet", "wallet",
           "payment", "unique_sorted_list", "onchain_wallet",
           "lnbits_wallet", "wallet_cache"):
    if _m in sys.modules:
        del sys.modules[_m]

import displaywallet
from displaywallet import _slot_credentials_present, WalletSettingsActivity


class _FakeEditor:
    def __init__(self, prefs):
        self._prefs = prefs
        self._pending = {}

    def put_string(self, key, value):
        self._pending[key] = value
        return self

    def commit(self):
        self._prefs._data.update(self._pending)
        return True


class _FakePrefs:
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get_string(self, key, default=""):
        return self._data.get(key, default)

    def edit(self):
        return _FakeEditor(self)


class _StubActivity:
    """Bare holder for the unbound _maybe_activate_added_wallet call."""
    def __init__(self, prefs, slot, was_configured):
        self.prefs = prefs
        self.slot = slot
        self._slot_was_configured = was_configured


def _switch(prefs, slot, was_configured):
    stub = _StubActivity(prefs, slot, was_configured)
    WalletSettingsActivity._maybe_activate_added_wallet(stub)
    return stub


class TestSlotCredentialsPresent(unittest.TestCase):

    def test_onchain_with_xpub_is_configured(self):
        p = _FakePrefs({"wallet_type_2": "onchain", "onchain_xpub_2": "zpub6r..."})
        self.assertTrue(_slot_credentials_present(p, 2))

    def test_onchain_without_xpub_is_not_configured(self):
        # wallet_type pre-seeded but no credential yet
        p = _FakePrefs({"wallet_type_2": "onchain"})
        self.assertFalse(_slot_credentials_present(p, 2))

    def test_lnbits_needs_url_and_key(self):
        self.assertTrue(_slot_credentials_present(
            _FakePrefs({"wallet_type": "lnbits", "lnbits_url": "https://x",
                        "lnbits_readkey": "abc"}), 1))
        self.assertFalse(_slot_credentials_present(
            _FakePrefs({"wallet_type": "lnbits", "lnbits_url": "https://x"}), 1))

    def test_nwc_needs_url(self):
        self.assertTrue(_slot_credentials_present(
            _FakePrefs({"wallet_type": "nwc", "nwc_url": "nostr+walletconnect://x"}), 1))

    def test_no_wallet_type_is_not_configured(self):
        self.assertFalse(_slot_credentials_present(_FakePrefs({}), 2))


class TestAutoActivateAddedWallet(unittest.TestCase):

    def test_adding_onchain_switches_active_to_that_slot(self):
        # Lightning active in slot 1; user just entered the slot-2 xpub.
        p = _FakePrefs({
            "wallet_type": "lnbits", "lnbits_url": "https://x", "lnbits_readkey": "k",
            "wallet_type_2": "onchain", "onchain_xpub_2": "zpub6r...",
            "active_wallet_slot": "1",
        })
        stub = _switch(p, 2, was_configured=False)
        self.assertEqual(p.get_string("active_wallet_slot", "1"), "2")
        self.assertTrue(stub._slot_was_configured)

    def test_editing_already_configured_slot_does_not_switch(self):
        # Slot 2 was already configured when settings opened -> no forced switch.
        p = _FakePrefs({
            "wallet_type_2": "onchain", "onchain_xpub_2": "zpub6r...",
            "active_wallet_slot": "1",
        })
        _switch(p, 2, was_configured=True)
        self.assertEqual(p.get_string("active_wallet_slot", "1"), "1")

    def test_backing_out_without_credentials_does_not_switch(self):
        # wallet_type pre-seeded to onchain but the user never entered an xpub.
        p = _FakePrefs({"wallet_type_2": "onchain", "active_wallet_slot": "1"})
        _switch(p, 2, was_configured=False)
        self.assertEqual(p.get_string("active_wallet_slot", "1"), "1")

    def test_idempotent_second_resume_keeps_slot(self):
        p = _FakePrefs({
            "wallet_type_2": "onchain", "onchain_xpub_2": "zpub6r...",
            "active_wallet_slot": "1",
        })
        stub = _switch(p, 2, was_configured=False)          # first onResume: switches
        self.assertEqual(p.get_string("active_wallet_slot", "1"), "2")
        # second onResume reuses the now-True flag -> no re-evaluation churn
        WalletSettingsActivity._maybe_activate_added_wallet(stub)
        self.assertEqual(p.get_string("active_wallet_slot", "1"), "2")

    def test_adding_first_wallet_to_already_active_slot_no_write_needed(self):
        # Configuring slot 1 (already the active slot) shouldn't error or change it.
        p = _FakePrefs({
            "wallet_type": "lnbits", "lnbits_url": "https://x", "lnbits_readkey": "k",
            "active_wallet_slot": "1",
        })
        _switch(p, 1, was_configured=False)
        self.assertEqual(p.get_string("active_wallet_slot", "1"), "1")


if __name__ == "__main__":
    unittest.main()
