"""
The NWC wallet's "Optional LN Address" follows the NWC URL.

When the NWC URL carries a `lud16` lightning address, that address is
the one the wallet receives on, so the QR shows it and the settings row
displays it greyed out and cannot be edited. Only when the URL has no
lud16 does the manually entered address apply.

Before this, a manually entered address won over the URL's lud16: two
boards showed `oink@lightningpiggy.com` (an LNbits wallet) while they
displayed the payments of the Rizful wallet from the NWC URL, so a
payment to the QR never appeared on the screen.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_nwc_ln_address_from_url.py
"""

import sys
import unittest

for _m in ("displaywallet", "nostr_service", "nwc_wallet", "wallet",
           "payment", "unique_sorted_list", "onchain_wallet",
           "lnbits_wallet", "wallet_cache"):
    if _m in sys.modules:
        del sys.modules[_m]

import lvgl as lv

import wallet_cache
from displaywallet import WalletSettingsActivity, DisplayWallet

PUBKEY = "ab" * 32
SECRET = "cd" * 32
BASE = "nostr+walletconnect://" + PUBKEY + "?relay=wss://relay.example.com&secret=" + SECRET
URL_WITH_LUD16 = BASE + "&lud16=oink@rizful.com"
URL_WITHOUT_LUD16 = BASE


class _FakePrefs:
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get_string(self, key, default=None):
        return self._data.get(key, default)


class TestNwcUrlLud16(unittest.TestCase):

    def test_plain_lud16(self):
        self.assertEqual(wallet_cache.nwc_url_lud16(URL_WITH_LUD16), "oink@rizful.com")

    def test_url_encoded_lud16(self):
        url = BASE + "&lud16=oink%40rizful.com"
        self.assertEqual(wallet_cache.nwc_url_lud16(url), "oink@rizful.com")

    def test_lud16_before_other_params(self):
        url = ("nostr+walletconnect://" + PUBKEY + "?lud16=oink@rizful.com"
               "&relay=wss://relay.example.com&secret=" + SECRET)
        self.assertEqual(wallet_cache.nwc_url_lud16(url), "oink@rizful.com")

    def test_nwc_scheme(self):
        url = "nwc:" + PUBKEY + "?relay=wss://r.example.com&secret=" + SECRET + "&lud16=a@b.com"
        self.assertEqual(wallet_cache.nwc_url_lud16(url), "a@b.com")

    def test_no_lud16(self):
        self.assertIsNone(wallet_cache.nwc_url_lud16(URL_WITHOUT_LUD16))

    def test_lud16_without_at_is_ignored(self):
        self.assertIsNone(wallet_cache.nwc_url_lud16(BASE + "&lud16=nonsense"))

    def test_empty_lud16_is_ignored(self):
        self.assertIsNone(wallet_cache.nwc_url_lud16(BASE + "&lud16="))

    def test_empty_and_invalid_urls(self):
        for url in (None, "", "https://example.com/?lud16=a@b.com", "garbage"):
            self.assertIsNone(wallet_cache.nwc_url_lud16(url), repr(url))

    def test_malformed_percent_escape_does_not_raise(self):
        # mpos.util.urldecode raises on a "%" without two hex digits; this
        # helper runs while the settings screen is built.
        for tail in ("&lud16=a@b.com%", "&lud16=a%zz@b.com", "%", "&lud16=a@b.com&x=%zz"):
            self.assertIsNone(wallet_cache.nwc_url_lud16(BASE + tail), tail)

    def test_only_a_well_formed_address_comes_back(self):
        for value in ("@", "a@", "@b.com", "a@b", "a@b@c.com", "a b@c.com",
                      "a@b.com/x", "a@-b.com", "a@b..com", "a@b.com.",
                      "lightning:a@b.com", "a@b.com:8080", "x" * 320 + "@b.com"):
            self.assertIsNone(wallet_cache.nwc_url_lud16(BASE + "&lud16=" + value), value)

    def test_secret_of_a_malformed_url_never_comes_back(self):
        # ";" instead of "&": the whole tail used to be returned as the
        # address, and from there it reaches the settings row and the QR.
        url = ("nostr+walletconnect://" + PUBKEY + "?relay=wss://relay.example.com"
               "&lud16=a@b.com;secret=" + SECRET)
        self.assertIsNone(wallet_cache.nwc_url_lud16(url))

    def test_usual_addresses_are_accepted(self):
        for value in ("oink@rizful.com", "Oink@Rizful.com", "a.b-c_d+tag@sub.example.co.uk",
                      "1@1.1.1.1"):
            self.assertEqual(wallet_cache.nwc_url_lud16(BASE + "&lud16=" + value), value)

    def test_last_lud16_counts_as_in_the_wallet_parser(self):
        from nwc_wallet import NWCWallet
        url = BASE + "&lud16=first@example.com&lud16=last@example.com"
        self.assertEqual(wallet_cache.nwc_url_lud16(url), "last@example.com")
        self.assertEqual(NWCWallet.parse_nwc_url(None, url)[3], "last@example.com")

    def test_matches_the_wallet_parser(self):
        from nwc_wallet import NWCWallet
        for url in (URL_WITH_LUD16, BASE + "&lud16=oink%40rizful.com"):
            parsed = NWCWallet.parse_nwc_url(None, url)[3]
            self.assertEqual(wallet_cache.nwc_url_lud16(url), parsed)


class TestNwcReceiveOverride(unittest.TestCase):

    def test_url_address_wins_over_typed_one(self):
        prefs = _FakePrefs({"nwc_url": URL_WITH_LUD16,
                            "nwc_static_receive_code": "oink@lightningpiggy.com"})
        self.assertEqual(wallet_cache.nwc_receive_override(prefs), "oink@rizful.com")

    def test_typed_address_used_when_url_has_none(self):
        prefs = _FakePrefs({"nwc_url": URL_WITHOUT_LUD16,
                            "nwc_static_receive_code": "oink@lightningpiggy.com"})
        self.assertEqual(wallet_cache.nwc_receive_override(prefs), "oink@lightningpiggy.com")

    def test_nothing_set(self):
        prefs = _FakePrefs({"nwc_url": URL_WITHOUT_LUD16})
        self.assertFalse(wallet_cache.nwc_receive_override(prefs))

    def test_slot_two_keys(self):
        prefs = _FakePrefs({"nwc_url": URL_WITHOUT_LUD16,
                            "nwc_url_2": URL_WITH_LUD16,
                            "nwc_static_receive_code_2": "x@y.com"})
        self.assertEqual(wallet_cache.nwc_receive_override(prefs, "_2"), "oink@rizful.com")
        self.assertFalse(wallet_cache.nwc_receive_override(prefs, ""))


class TestCachedQrFollowsUrlAddress(unittest.TestCase):

    def test_typed_address_does_not_change_qr_fingerprint_when_url_has_one(self):
        a = _FakePrefs({"nwc_url": URL_WITH_LUD16,
                        "nwc_static_receive_code": "oink@lightningpiggy.com"})
        b = _FakePrefs({"nwc_url": URL_WITH_LUD16})
        self.assertEqual(wallet_cache.compute_fingerprints("nwc", a),
                         wallet_cache.compute_fingerprints("nwc", b))

    def test_typed_address_changes_qr_fingerprint_when_url_has_none(self):
        a = _FakePrefs({"nwc_url": URL_WITHOUT_LUD16,
                        "nwc_static_receive_code": "oink@lightningpiggy.com"})
        b = _FakePrefs({"nwc_url": URL_WITHOUT_LUD16})
        self.assertNotEqual(wallet_cache.compute_fingerprints("nwc", a)[1],
                            wallet_cache.compute_fingerprints("nwc", b)[1])


class _FakeQr:
    def __init__(self):
        self.data = None

    def update(self, data, length):
        self.data = data

    def remove_flag(self, flag):
        pass


class _FakeWallet:
    def __init__(self, code=None):
        self.static_receive_code = code


class _RedrawStub:
    def __init__(self, prefs, wallet):
        self.prefs = prefs
        self.wallet = wallet
        self.receive_qr = _FakeQr()
        self.receive_qr_data = None

    def _active_slot_and_suffix(self):
        return "1", ""


class TestQrShowsUrlAddress(unittest.TestCase):

    def _redraw(self, data, wallet_code=None):
        stub = _RedrawStub(_FakePrefs(data), _FakeWallet(wallet_code))
        DisplayWallet.redraw_static_receive_code_cb(stub)
        return stub.receive_qr.data

    def test_url_address_beats_typed_address(self):
        qr = self._redraw({"wallet_type": "nwc", "nwc_url": URL_WITH_LUD16,
                           "nwc_static_receive_code": "oink@lightningpiggy.com"})
        self.assertEqual(qr, "lightning:oink@rizful.com")

    def test_typed_address_used_when_url_has_none(self):
        qr = self._redraw({"wallet_type": "nwc", "nwc_url": URL_WITHOUT_LUD16,
                           "nwc_static_receive_code": "oink@lightningpiggy.com"})
        self.assertEqual(qr, "lightning:oink@lightningpiggy.com")

    def test_lnbits_override_unchanged(self):
        qr = self._redraw({"wallet_type": "lnbits",
                           "lnbits_static_receive_code": "a@b.com"})
        self.assertEqual(qr, "lightning:a@b.com")


class _FakeLabel:
    def __init__(self, text):
        self.text = text

    def set_text(self, text):
        self.text = text


class _FakeCont:
    def __init__(self):
        self.states = set()
        self.opa = None

    def add_state(self, state):
        self.states.add(state)

    def set_style_opa(self, opa, part):
        self.opa = opa


class _SettingsStub:
    def __init__(self, prefs, slot=1):
        self.prefs = prefs
        self.slot = slot
        s = "_2" if str(slot) == "2" else ""
        self.row = {"key": "nwc_static_receive_code" + s,
                    "cont": _FakeCont(), "value_label": _FakeLabel("(not set)")}
        self.settings = [
            {"key": "nwc_url" + s, "cont": _FakeCont(), "value_label": _FakeLabel("x")},
            self.row,
        ]


class TestSettingsRowLocked(unittest.TestCase):

    def test_row_shows_url_address_and_is_disabled(self):
        stub = _SettingsStub(_FakePrefs({"wallet_type": "nwc", "nwc_url": URL_WITH_LUD16,
                                         "nwc_static_receive_code": "oink@lightningpiggy.com"}))
        WalletSettingsActivity._lock_nwc_ln_address(stub)
        self.assertEqual(stub.row["value_label"].text, "oink@rizful.com")
        self.assertIn(lv.STATE.DISABLED, stub.row["cont"].states)
        self.assertIsNotNone(stub.row["cont"].opa)

    def test_row_editable_when_url_has_no_address(self):
        stub = _SettingsStub(_FakePrefs({"wallet_type": "nwc", "nwc_url": URL_WITHOUT_LUD16}))
        WalletSettingsActivity._lock_nwc_ln_address(stub)
        self.assertEqual(stub.row["value_label"].text, "(not set)")
        self.assertEqual(stub.row["cont"].states, set())

    def test_malformed_url_leaves_the_row_editable(self):
        for url in (URL_WITH_LUD16 + "%", BASE + "&lud16=a@b.com;secret=" + SECRET):
            stub = _SettingsStub(_FakePrefs({"wallet_type": "nwc", "nwc_url": url}))
            WalletSettingsActivity._lock_nwc_ln_address(stub)
            self.assertEqual(stub.row["value_label"].text, "(not set)", url[-12:])
            self.assertEqual(stub.row["cont"].states, set())

    def test_other_rows_untouched(self):
        stub = _SettingsStub(_FakePrefs({"wallet_type": "nwc", "nwc_url": URL_WITH_LUD16}))
        WalletSettingsActivity._lock_nwc_ln_address(stub)
        self.assertEqual(stub.settings[0]["cont"].states, set())

    def test_slot_two(self):
        stub = _SettingsStub(_FakePrefs({"wallet_type_2": "nwc", "nwc_url_2": URL_WITH_LUD16}), slot=2)
        WalletSettingsActivity._lock_nwc_ln_address(stub)
        self.assertEqual(stub.row["value_label"].text, "oink@rizful.com")
        self.assertIn(lv.STATE.DISABLED, stub.row["cont"].states)

    def test_other_wallet_type_leaves_stale_row_alone(self):
        # The row is hidden for an LNbits wallet; its "cont" is left over
        # from an earlier render and points at a deleted LVGL object.
        stub = _SettingsStub(_FakePrefs({"wallet_type": "lnbits", "nwc_url": URL_WITH_LUD16}))
        WalletSettingsActivity._lock_nwc_ln_address(stub)
        self.assertEqual(stub.row["cont"].states, set())
        self.assertEqual(stub.row["value_label"].text, "(not set)")

    def test_hidden_row_is_skipped(self):
        stub = _SettingsStub(_FakePrefs({"wallet_type": "nwc", "nwc_url": URL_WITH_LUD16}))
        del stub.row["cont"]
        del stub.row["value_label"]
        WalletSettingsActivity._lock_nwc_ln_address(stub)


if __name__ == "__main__":
    unittest.main()
