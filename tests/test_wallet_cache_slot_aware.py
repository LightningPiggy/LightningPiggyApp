"""
Unit tests for the slot-aware wallet_cache module — multi-wallet feature.

Targets LightningPiggyApp PR #26 (multi-wallet, stacked on PR #25's on-chain
work). Verifies that compute_fingerprints / compute_slot_key handle the
(wallet_type, wallet_slot) pair correctly so two slots with the same wallet
type (e.g. two LNBits wallets) get distinct cache entries.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_wallet_cache_slot_aware.py
    Device:  bash tests/unittest.sh tests/test_wallet_cache_slot_aware.py --ondevice
"""

import unittest

try:
    import wallet_cache
    _HAVE_WALLET_CACHE = True
except ImportError:
    _HAVE_WALLET_CACHE = False


class _StubPrefs:
    """Minimal stand-in for SharedPreferences. Only get_string is needed by
    compute_fingerprints / compute_slot_key, and only as a read-only view."""
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get_string(self, key, default=None):
        v = self._data.get(key)
        return v if v is not None else default


@unittest.skipUnless(_HAVE_WALLET_CACHE, "wallet_cache module not available")
class TestSlotSuffix(unittest.TestCase):
    def test_slot_1_returns_empty_suffix(self):
        # Slot 1 keeps unsuffixed pref keys for back-compat with the
        # pre-multi-wallet builds (`wallet_type`, `lnbits_url`, etc.).
        self.assertEqual(wallet_cache.slot_suffix(1), "")
        self.assertEqual(wallet_cache.slot_suffix("1"), "")

    def test_slot_2_returns_underscore_2(self):
        self.assertEqual(wallet_cache.slot_suffix(2), "_2")
        self.assertEqual(wallet_cache.slot_suffix("2"), "_2")

    def test_unknown_slot_treated_as_slot_1(self):
        # Defensive default: anything other than "2" / 2 means slot 1.
        # This keeps the cache from accidentally writing to a "_3" slot
        # if a future pref ends up with a bogus value.
        self.assertEqual(wallet_cache.slot_suffix(99), "")
        self.assertEqual(wallet_cache.slot_suffix("garbage"), "")


@unittest.skipUnless(_HAVE_WALLET_CACHE, "wallet_cache module not available")
class TestComputeSlotKey(unittest.TestCase):
    def test_lnbits_slot_1(self):
        self.assertEqual(wallet_cache.compute_slot_key("lnbits", 1), "lnbits_1")

    def test_nwc_slot_2(self):
        self.assertEqual(wallet_cache.compute_slot_key("nwc", 2), "nwc_2")

    def test_onchain_slot_1(self):
        self.assertEqual(wallet_cache.compute_slot_key("onchain", 1), "onchain_1")

    def test_string_slot_arg(self):
        # Some callers pass slot as a string ("1"/"2"). Both forms must yield
        # the same slot_key — otherwise the two would write to different
        # cache entries and never read each other's data back.
        self.assertEqual(
            wallet_cache.compute_slot_key("lnbits", "1"),
            wallet_cache.compute_slot_key("lnbits", 1),
        )


@unittest.skipUnless(_HAVE_WALLET_CACHE, "wallet_cache module not available")
class TestComputeFingerprints(unittest.TestCase):
    def test_lnbits_slot_aware_pref_reads(self):
        prefs = _StubPrefs({
            "lnbits_url": "https://lnbits.example.com",
            "lnbits_readkey": "ABCDEF1234",
            "lnbits_url_2": "https://lnbits2.example.com",
            "lnbits_readkey_2": "ZYXWVU9876",
        })
        creds1, _ = wallet_cache.compute_fingerprints("lnbits", prefs, slot=1)
        creds2, _ = wallet_cache.compute_fingerprints("lnbits", prefs, slot=2)
        # Different prefs in each slot → different fingerprints.
        self.assertNotEqual(creds1, creds2)
        # Both should be non-empty short hex strings.
        self.assertTrue(creds1)
        self.assertTrue(creds2)

    def test_same_creds_in_both_slots_still_distinct(self):
        # Edge case: user accidentally configures the same LNBits wallet
        # in both slots. The fingerprints must still be different so each
        # slot owns its own cache entry — the (wallet_type, slot) pair
        # is the cache identity, not just the credentials.
        prefs = _StubPrefs({
            "lnbits_url": "https://same.example.com",
            "lnbits_readkey": "samekey",
            "lnbits_url_2": "https://same.example.com",
            "lnbits_readkey_2": "samekey",
        })
        creds1, _ = wallet_cache.compute_fingerprints("lnbits", prefs, slot=1)
        creds2, _ = wallet_cache.compute_fingerprints("lnbits", prefs, slot=2)
        self.assertFalse(creds1 == creds2)

    def test_onchain_xpub_and_blockbook_url_in_fingerprint(self):
        # Changing the Blockbook URL pointed at the same xpub IS a config
        # change (different indexers can lag, or the user moves to a
        # self-hosted one) — must invalidate cached data.
        prefs_trezor = _StubPrefs({
            "onchain_xpub": "zpubABC",
            "onchain_blockbook_url": "https://btc1.trezor.io",
        })
        prefs_umbrel = _StubPrefs({
            "onchain_xpub": "zpubABC",
            "onchain_blockbook_url": "http://umbrel.local:9130",
        })
        c1, _ = wallet_cache.compute_fingerprints("onchain", prefs_trezor, slot=1)
        c2, _ = wallet_cache.compute_fingerprints("onchain", prefs_umbrel, slot=1)
        self.assertFalse(c1 == c2)

    def test_creds_fp_independent_of_static_override(self):
        # Changing only the optional static-receive-code override must NOT
        # invalidate balance/payments — only the QR-fp branch should change.
        prefs_no_override = _StubPrefs({
            "lnbits_url": "https://lnbits.example.com",
            "lnbits_readkey": "ABCDEF1234",
        })
        prefs_override = _StubPrefs({
            "lnbits_url": "https://lnbits.example.com",
            "lnbits_readkey": "ABCDEF1234",
            "lnbits_static_receive_code": "oink@demo.lnpiggy.com",
        })
        creds_no, qr_no = wallet_cache.compute_fingerprints("lnbits", prefs_no_override, slot=1)
        creds_o, qr_o = wallet_cache.compute_fingerprints("lnbits", prefs_override, slot=1)
        self.assertEqual(creds_no, creds_o)
        self.assertFalse(qr_no == qr_o)

    def test_unknown_wallet_type_returns_none_none(self):
        prefs = _StubPrefs({})
        creds, qr = wallet_cache.compute_fingerprints("unknown_type", prefs, slot=1)
        self.assertIsNone(creds)
        self.assertIsNone(qr)


if __name__ == "__main__":
    unittest.main()
