"""
Unit tests for NWC (NIP-47 Nostr Wallet Connect) URL parsing.

The codebase deliberately carries TWO copies of the parser:
  - NWCWallet.parse_nwc_url   (nwc_wallet.py)    — feeds the wallet object
  - NostrManager._parse_nwc_url (nostr_service.py) — feeds the relay layer

Every NWC credential a user enters passes through both, so besides testing
each parser's accept/reject behaviour, test_parsers_agree feeds the same
battery of URLs to both and asserts identical outcomes — guarding against
the copies drifting apart.

Both methods ignore `self`, so they're exercised unbound with None.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_nwc_url_parsing.py
"""

import sys
import unittest

# The MPOS nostr app's boot service can pre-load its own (older)
# nostr_service into sys.modules, shadowing Lightning Piggy's copy —
# purge so the imports below resolve to the app's own modules.
for _m in ("nostr_service", "nwc_wallet", "wallet", "payment", "unique_sorted_list"):
    if _m in sys.modules:
        del sys.modules[_m]

from nwc_wallet import NWCWallet
from nostr_service import NostrManager

PUBKEY = "ab" * 32  # 64 lowercase hex chars
SECRET = "cd" * 32
RELAY = "wss://relay.example.com"
LUD16 = "piggy@example.com"

VALID_URL = (
    "nostr+walletconnect://" + PUBKEY
    + "?relay=" + RELAY + "&secret=" + SECRET + "&lud16=" + LUD16
)

# Shaped like what coinos/Alby actually hand out: percent-encoded relay.
REAL_WORLD_URL = (
    "nostr+walletconnect://" + PUBKEY
    + "?relay=wss%3A%2F%2Frelay.coinos.io&secret=" + SECRET
    + "&lud16=" + LUD16
)

# (name, callable) for both parser copies — both return
# (relays, pubkey, secret, lud16) and wrap any failure in RuntimeError.
PARSERS = (
    ("NWCWallet.parse_nwc_url", lambda url: NWCWallet.parse_nwc_url(None, url)),
    ("NostrManager._parse_nwc_url", lambda url: NostrManager._parse_nwc_url(None, url)),
)


class TestNWCURLParsing(unittest.TestCase):

    def _assert_rejected(self, url):
        for name, parse in PARSERS:
            try:
                result = parse(url)
            except RuntimeError:
                continue  # expected
            self.fail("{} accepted bad URL {!r} -> {!r}".format(name, url, result))

    def test_full_url_parses(self):
        for name, parse in PARSERS:
            relays, pubkey, secret, lud16 = parse(VALID_URL)
            self.assertEqual(relays, [RELAY], name)
            self.assertEqual(pubkey, PUBKEY, name)
            self.assertEqual(secret, SECRET, name)
            self.assertEqual(lud16, LUD16, name)

    def test_nwc_short_prefix(self):
        url = "nwc:" + PUBKEY + "?relay=" + RELAY + "&secret=" + SECRET
        for name, parse in PARSERS:
            relays, pubkey, secret, lud16 = parse(url)
            self.assertEqual(pubkey, PUBKEY, name)
            self.assertEqual(lud16, None, name)

    def test_missing_prefix_rejected(self):
        self._assert_rejected(PUBKEY + "?relay=" + RELAY + "&secret=" + SECRET)

    def test_urlencoded_relay_decoded(self):
        for name, parse in PARSERS:
            relays, _, _, lud16 = parse(REAL_WORLD_URL)
            self.assertEqual(relays, ["wss://relay.coinos.io"], name)
            self.assertEqual(lud16, LUD16, name)

    def test_multiple_relays_collected(self):
        url = (
            "nostr+walletconnect://" + PUBKEY
            + "?relay=wss://a.example&relay=wss://b.example&secret=" + SECRET
        )
        for name, parse in PARSERS:
            relays, _, _, _ = parse(url)
            self.assertEqual(relays, ["wss://a.example", "wss://b.example"], name)

    def test_lud16_optional(self):
        url = "nostr+walletconnect://" + PUBKEY + "?relay=" + RELAY + "&secret=" + SECRET
        for name, parse in PARSERS:
            _, _, _, lud16 = parse(url)
            self.assertEqual(lud16, None, name)

    def test_pubkey_wrong_length_rejected(self):
        url = "nostr+walletconnect://" + ("ab" * 16) + "?relay=" + RELAY + "&secret=" + SECRET
        self._assert_rejected(url)

    def test_pubkey_uppercase_hex_rejected(self):
        # Documents current strictness: only lowercase hex is accepted.
        url = "nostr+walletconnect://" + PUBKEY.upper() + "?relay=" + RELAY + "&secret=" + SECRET
        self._assert_rejected(url)

    def test_pubkey_non_hex_rejected(self):
        url = "nostr+walletconnect://" + ("zz" * 32) + "?relay=" + RELAY + "&secret=" + SECRET
        self._assert_rejected(url)

    def test_missing_secret_rejected(self):
        self._assert_rejected("nostr+walletconnect://" + PUBKEY + "?relay=" + RELAY)

    def test_secret_wrong_length_rejected(self):
        url = "nostr+walletconnect://" + PUBKEY + "?relay=" + RELAY + "&secret=" + ("cd" * 8)
        self._assert_rejected(url)

    def test_missing_relay_rejected(self):
        self._assert_rejected("nostr+walletconnect://" + PUBKEY + "?secret=" + SECRET)

    def test_no_query_string_rejected(self):
        self._assert_rejected("nostr+walletconnect://" + PUBKEY)

    def test_parsers_agree(self):
        # The drift guard: identical outcome (same tuple, or both reject)
        # for every URL in the battery.
        battery = [
            VALID_URL,
            REAL_WORLD_URL,
            "nwc:" + PUBKEY + "?relay=" + RELAY + "&secret=" + SECRET,
            "nostr+walletconnect://" + PUBKEY + "?relay=wss://a&relay=wss://b&secret=" + SECRET,
            # invalid ones:
            PUBKEY + "?relay=" + RELAY + "&secret=" + SECRET,
            "nostr+walletconnect://" + PUBKEY,
            "nostr+walletconnect://" + PUBKEY + "?relay=" + RELAY,
            "nostr+walletconnect://" + PUBKEY + "?relay=" + RELAY + "&secret=short",
            "nostr+walletconnect://short?relay=" + RELAY + "&secret=" + SECRET,
            "",
        ]
        for url in battery:
            outcomes = []
            for name, parse in PARSERS:
                try:
                    outcomes.append(parse(url))
                except RuntimeError:
                    outcomes.append("rejected")
            self.assertEqual(
                outcomes[0], outcomes[1],
                "parsers disagree on {!r}: {!r} vs {!r}".format(url, outcomes[0], outcomes[1]),
            )


class TestNWCWalletConstructor(unittest.TestCase):

    def test_valid_url_populates_wallet(self):
        w = NWCWallet(VALID_URL)
        self.assertEqual(w.slot_key, "nwc")
        self.assertEqual(w.relays, [RELAY])
        self.assertEqual(w.wallet_pubkey, PUBKEY)
        self.assertEqual(w.secret, SECRET)
        self.assertEqual(w.lud16, LUD16)

    def test_empty_url_raises_valueerror(self):
        for bad in ("", None):
            try:
                NWCWallet(bad)
            except ValueError:
                continue
            self.fail("NWCWallet({!r}) did not raise ValueError".format(bad))

    def test_malformed_url_raises(self):
        try:
            NWCWallet("nostr+walletconnect://" + PUBKEY)  # no relay/secret
        except RuntimeError:
            return
        self.fail("NWCWallet with malformed URL did not raise")


if __name__ == "__main__":
    unittest.main()
