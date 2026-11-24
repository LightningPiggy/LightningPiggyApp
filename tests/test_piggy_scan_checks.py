"""
Unit tests for piggy_scan_checks: the format checks MicroPythonOS runs on
data scanned from a QR code into a wallet setting (the setting's
`scan_check`). A check returns True when the data has the format the wallet
needs, otherwise a warning string telling the user to check the QR code.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_piggy_scan_checks.py
"""

import sys
import unittest

# The MPOS nostr app's boot service can pre-load its own nostr_service into
# sys.modules, shadowing Lightning Piggy's copy; purge so nwc_wallet (which
# check_nwc_url imports) resolves to the app's own modules.
for _m in ("nostr_service", "nwc_wallet", "wallet", "payment", "unique_sorted_list"):
    if _m in sys.modules:
        del sys.modules[_m]

import piggy_scan_checks as checks
from nwc_wallet import NWCWallet

HINT = "Check that you scanned the right QR code."

# BIP-173 / BIP-350 and well-known mainnet addresses (all valid).
P2WPKH = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
P2TR = "bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"
P2PKH = "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2"
P2SH = "3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"
XPUB = "xpub6CUGRUonZSQ4TWtTMmzXdrXDtypWKiKrhko4egpiMZbpiaQL2jkwSB1icqYh2cfDfVxdx4df189oLKnC5fSwqPfgyP3hooxujYzAu3fDVmz"
ZPUB = "zpub6rFR7y4Q2AijBEqTUquhVz398htDFrtymD9xYYfG1m4wAcvPhXNfE3EfH1r1ADqtfSdVCToUG868RvUUkgDKf31mGDtKsAYz2oz2AGutZYs"
LNURL = ("LNURL1DP68GURN8GHJ7UM9WFMXJCM99E3K7MF0V9CXJ0M385EKVCENXC6R2C35XVUKXEFCV5MKVV34X5EKZD3EV56NYD3HXQURZEPEXEJXXEPNXSCRVWFNV9NXZCN9XQ6XYEFHVGCXXCMYXYMNSERXFQ5FNS")
LN_ADDRESS = "piggy@example.com"
BOLT11 = "lnbc10u1pjl70yqpp5qqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqqqsyqcyq5rqwzqfqypq"
READ_KEY = "fd92e3f8168ba314dc22e54182784045"
BOLT12 = "lno1" + "qgsqvgnwgcg35z6ee2h3yczraddm72xrfua9uve2rlrm9deu7xyfzr" * 2
SILENT = "sp1qq" + "gste7k9hx0qftg6qmwlkqtwuy6cycyavzmzj85c6qdfhjdpdjtdgqjuexzk6murw56suy3e0rd2cgqvycxttddwsvgxe2usfpxumr70xc9pkqwv"
# Real bech32 LNURLs: an LNbits withdraw voucher, an LNURL-auth login, and a
# pay link whose username merely starts with "withdraw".
LNURL_WITHDRAW = "LNURL1DP68GURN8GHJ7MR9VAJKUEPWD3HXY6T5WVHXXMMD9AMKJARGV3EXZAE0V9CXJTMKXYHKCMN4WFKZ7WZRVDHKSD25DEUNXAJYVEUYSKJYTPR4J66VCALZLQ"
LNURL_LOGIN = ("LNURL1DP68GURN8GHJ7UMFW3JJUCM0D5HKCMN4WFKZ6MR0VA5KU0M5V9NN6MR0VA5KUFNTXY7KZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVG67FR3L")
LNURL_PAY_WITHDRAWBOB = "LNURL1DP68GURN8GHJ7ETCV9KHQMR99E3K7MF09EMK2MRV944KUMMHDCHKCMN4WFK8QTMHD96XSERJV9MKYMMZMQH2VG"
SPARK = "sp1pgssyvyrkg25x5swadve6s7vla0vz4p2nznq44wx72dt5qx8kew6kczk5gam56"
NPUB_CASH = "npub1sg6plzptd64u62a878hep2kev88swjh3tw00gjsfl8f237lmu63q0uf63m@npub.cash"
NWC = ("nostr+walletconnect://" + "ab" * 32
       + "?relay=wss://relay.example.com&secret=" + "cd" * 32 + "&lud16=" + LN_ADDRESS)


class TestDescribe(unittest.TestCase):

    def test_recognises_common_codes(self):
        cases = [
            (NWC, "a Nostr Wallet Connect link"),
            ("nsec1" + "q" * 58, "a Nostr key"),
            ("npub1" + "q" * 58, "a Nostr key"),
            (P2WPKH, "a Bitcoin address"),
            (P2PKH, "a Bitcoin address"),
            ("bitcoin:" + P2WPKH + "?amount=0.001", "a one-time payment request"),
            ("bitcoin:" + P2WPKH + "?label=piggy", "a Bitcoin address"),
            (XPUB, "an xpub"),
            (ZPUB, "an xpub"),
            (BOLT11, "a one-time Lightning invoice"),
            ("lightning:" + BOLT11, "a one-time Lightning invoice"),
            (LNURL, "an LNURL"),
            (LN_ADDRESS, "a Lightning Address"),
            ("lightning:" + LN_ADDRESS, "a Lightning Address"),
            ("https://demo.lnbits.com", "a web address"),
            ("wss://relay.example.com", "a relay address"),
            (READ_KEY, "an LNbits key"),
            ("ab" * 32, "a 64-character key"),
        ]
        for text, expected in cases:
            self.assertEqual(checks.describe(text), expected, text)

    def test_unknown_text(self):
        self.assertIsNone(checks.describe("hello world"))
        self.assertIsNone(checks.describe(""))
        self.assertIsNone(checks.describe(None))


class TestLightningAddress(unittest.TestCase):

    def test_accepts(self):
        for text in (LN_ADDRESS, "Piggy@Example.com", "lightning:" + LN_ADDRESS,
                     "LIGHTNING:" + LN_ADDRESS, "first.last+tag@sub.example.org",
                     LNURL, LNURL.lower(), "lightning:" + LNURL,
                     "lnurlp://example.com/.well-known/lnurlp/piggy"):
            self.assertIs(checks.check_lightning_address(text), True, text)

    def test_wrong_code_names_what_was_scanned(self):
        msg = checks.check_lightning_address(P2WPKH)
        self.assertEqual(msg, "This QR code looks like a Bitcoin address, not a Lightning Address. " + HINT)
        self.assertIn("one-time Lightning invoice", checks.check_lightning_address(BOLT11))
        self.assertIn("Nostr Wallet Connect link", checks.check_lightning_address(NWC))

    def test_damaged_address(self):
        msg = checks.check_lightning_address("piggy@example")
        self.assertEqual(msg, "This doesn't look like a Lightning Address. " + HINT)
        self.assertIn("missing or wrong", checks.check_lightning_address("lightning:lnurl1short"))

    def test_mixed_case_lnurl_rejected(self):
        self.assertIsNot(checks.check_lightning_address("LNURL1" + LNURL[6:].lower()), True)


class TestReviewCases(unittest.TestCase):
    """Real-world codes found in review: right QR codes must not be told
    they are wrong, and wrong ones must be named correctly."""

    def test_static_lightning_codes_accepted(self):
        for text in (BOLT12, "lightning:" + BOLT12, BOLT12.upper(), NPUB_CASH,
                     "bitcoin:" + P2WPKH + "?lightning=" + LNURL,
                     "BITCOIN:" + P2WPKH.upper() + "?LIGHTNING=" + LNURL,
                     "bitcoin:" + P2WPKH + "?lno=" + BOLT12,
                     "https://pay.example.com/?lightning=" + LNURL):
            self.assertIs(checks.check_lightning_address(text), True, text)

    def test_unified_qr_with_invoice_still_warns(self):
        self.assertIsNot(checks.check_lightning_address("bitcoin:" + P2WPKH + "?lightning=" + BOLT11), True)
        self.assertIsNot(checks.check_lightning_address("bitcoin:" + P2WPKH), True)

    def test_withdraw_link_is_named(self):
        msg = checks.check_lightning_address("lnurlw://example.com/withdraw/abc")
        self.assertIn("looks like an LNURL withdraw link, not a Lightning Address", msg)

    def test_npub_cash_and_nostr_links_named(self):
        self.assertEqual(checks.describe(NPUB_CASH), "a Lightning Address")
        self.assertEqual(checks.describe("nostr:note1" + "q" * 58), "a Nostr post link")
        self.assertEqual(checks.describe("nostr:nprofile1" + "q" * 58), "a Nostr key")
        self.assertIn("looks like a Lightning Address, not a Nostr Wallet Connect link",
                      checks.check_nwc_url(NPUB_CASH))

    def test_silent_payment_and_bip321_fixed_address(self):
        for text in (SILENT, "bitcoin:" + SILENT, "bitcoin:?sp=" + SILENT,
                     "bitcoin:?lno=" + BOLT12, "bitcoin:?lightning=" + LNURL):
            self.assertIs(checks.check_bitcoin_address(text), True, text)
        self.assertIn("looks like a silent payment address, not an xpub or Bitcoin address",
                      checks.check_xpub_or_address(SILENT))

    def test_bitcoin_link_without_address_named_by_payload(self):
        msg = checks.check_xpub_or_address("bitcoin:?lightning=" + BOLT11)
        self.assertIn("looks like a one-time payment request", msg)
        msg = checks.check_bitcoin_address("bitcoin:?lightning=" + BOLT11)
        self.assertIn("one-time payment request", msg)
        self.assertEqual(checks.describe("bitcoin:?lno=" + BOLT12), "a BOLT12 offer")

    def test_surrounding_spaces_flagged_where_wallet_keeps_them(self):
        for check, good in ((checks.check_nwc_url, NWC),
                            (checks.check_lnbits_url, "https://demo.lnbits.com"),
                            (checks.check_lnbits_readkey, READ_KEY),
                            (checks.check_blockbook_url, "https://btc1.trezor.io")):
            self.assertIs(check(good), True)
            self.assertIn("spaces at the start or end", check(good + " "))
            self.assertIn("spaces at the start or end", check(" " + good))

    def test_lnurl_withdraw_and_login_codes_rejected(self):
        self.assertIn("looks like an LNURL withdraw link, not a Lightning Address",
                      checks.check_lightning_address(LNURL_WITHDRAW))
        self.assertIn("looks like an LNURL withdraw link",
                      checks.check_lightning_address("lightning:" + LNURL_WITHDRAW.lower()))
        self.assertIn("looks like an LNURL login code",
                      checks.check_lightning_address(LNURL_LOGIN))
        self.assertIsNot(checks.check_lightning_address("https://x.com/?lightning=" + LNURL_WITHDRAW), True)
        self.assertIs(checks.check_lightning_address(LNURL_PAY_WITHDRAWBOB), True)

    def test_spark_address_is_not_a_silent_payment_address(self):
        self.assertIsNot(checks.check_bitcoin_address(SPARK), True)
        self.assertIsNot(checks.check_bitcoin_address("bitcoin:?sp=" + SPARK), True)
        self.assertNotEqual(checks.describe(SPARK), "a silent payment address")

    def test_one_time_payment_request_in_fixed_address(self):
        for text in ("bitcoin:" + P2WPKH + "?amount=0.0001",
                     "bitcoin:" + P2WPKH + "?amount=0.0001&lightning=" + BOLT11,
                     "bitcoin:" + P2WPKH + "?lightning=" + BOLT11):
            self.assertIn("one-time payment request", checks.check_bitcoin_address(text), text)
        self.assertIn("Scan your Lightning Address or another reusable receive code instead",
                      checks.check_lightning_address("bitcoin:" + P2WPKH + "?amount=1&lightning=" + BOLT11))

    def test_marker_lookalikes_are_still_pay_codes(self):
        # Pay links whose username, host or query only resemble a withdraw
        # or login marker.
        for code in ("LNURL1DP68GURN8GHJ7EM9W3SKCCNE9E3K7MF09EMK2MRV944KUMMHDCHKCMN4WFK8QTMVDE6HYMRHV9KXCET5VHWVJ5",
                     "LNURL1DP68GURN8GHJ7MRWW4EXCAEWV4UXZMTSD3JJUCM0D5HKCMN4WFK8QTMPVF3SW9WM3K",
                     "LNURL1DP68GURN8GHJ7URP0YHX27RPD4CXCEFWVDHK6TMVDE6HYMRS9ASKYCELW3SKW0TVDANKJMNZDAH82UCDZ8W8L"):
            self.assertIs(checks.check_lightning_address(code), True, code)

    def test_pathless_login_and_withdraw_lnurls(self):
        # LUD-04's own example form: host and query, no path.
        self.assertIn("looks like an LNURL login code",
                      checks.check_lightning_address("LNURL1DP68GURN8GHJ7UMFW3JJUCM0D5LHGCT884KX7EMFDCNXKVFAV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZCNPVFSKYCTZV93XZC3XV93HG6T0DC7KCMM8D9HQQ98YMS"))
        self.assertIn("looks like an LNURL withdraw link",
                      checks.check_lightning_address("LNURL1DP68GURN8GHJ7UMFW3JJUCM0D5LHGCT884MKJARGV3EXZA6JV4CH2ETNWSNXKVFAXY6ZAGDD"))

    def test_bip321_query_address_in_xpub_field(self):
        msg = checks.check_xpub_or_address("bitcoin:?bc=" + P2WPKH)
        self.assertIn("Enter just the address, the part that starts with bc1q.", msg)

    def test_withdraw_in_https_fallback_is_named(self):
        msg = checks.check_lightning_address("https://legend.lnbits.com/?lightning=" + LNURL_WITHDRAW)
        self.assertIn("looks like an LNURL withdraw link", msg)

    def test_one_time_requests_without_address(self):
        for text in ("bitcoin:?sp=" + SILENT + "&amount=0.001",
                     "bitcoin:?amount=0.001&lno=" + BOLT12,
                     "bitcoin:?lightning=" + BOLT11 + "&lno=" + BOLT12):
            self.assertIn("one-time payment request", checks.check_bitcoin_address(text), text)
            self.assertEqual(checks.describe(text), "a one-time payment request", text)

    def test_unified_one_time_request_in_lightning_field(self):
        for text in ("bitcoin:" + P2WPKH + "?amount=0.01&lightning=" + LNURL,
                     "bitcoin:" + P2WPKH + "?lightning=" + BOLT11 + "&lno=" + BOLT12):
            self.assertIn("one-time payment request", checks.check_lightning_address(text), text)

    def test_bip321_address_in_query(self):
        for text in ("bitcoin:?bc=" + P2WPKH, "bitcoin:?BC=" + P2WPKH.upper()):
            self.assertIs(checks.check_bitcoin_address(text), True, text)
            self.assertEqual(checks.describe(text), "a Bitcoin address", text)

    def test_descriptor_wrapped_xpub(self):
        msg = checks.check_xpub_or_address("[73c5da0a/84h/0h/0h]" + ZPUB)
        self.assertEqual(msg, "This has extra text around the key. Enter just the part that starts with zpub.")
        self.assertIn("starts with xpub", checks.check_xpub_or_address("wpkh([73c5da0a/84h/0h/0h]" + XPUB + "/0/*)"))


class TestLnbits(unittest.TestCase):

    def test_url(self):
        for text in ("https://demo.lnbits.com", "https://demo.lnbits.com/",
                     "http://192.168.1.10:5000", "https://example.com/lnbits"):
            self.assertIs(checks.check_lnbits_url(text), True, text)
        self.assertIn("looks like an LNbits key", checks.check_lnbits_url(READ_KEY))
        self.assertIn("missing or wrong", checks.check_lnbits_url("https://"))

    def test_url_with_query_is_flagged(self):
        msg = checks.check_lnbits_url("https://demo.lnbits.com/wallet?usr=abc&wal=def")
        self.assertIn("Enter only the server address, like https://demo.lnbits.com", msg)

    def test_read_key(self):
        self.assertIs(checks.check_lnbits_readkey(READ_KEY), True)
        self.assertIs(checks.check_lnbits_readkey(READ_KEY.upper()), True)
        self.assertIn("looks like a web address, not an LNbits read key",
                      checks.check_lnbits_readkey("https://demo.lnbits.com"))
        self.assertEqual(checks.check_lnbits_readkey(READ_KEY[:-1]),
                         "This doesn't look like an LNbits read key. " + HINT)


class TestNwc(unittest.TestCase):

    def test_accepts_what_the_wallet_parser_accepts(self):
        self.assertIs(checks.check_nwc_url(NWC), True)
        self.assertIs(checks.check_nwc_url("nwc:" + NWC[22:]), True)

    def test_wrong_code(self):
        self.assertIn("looks like a Lightning Address, not a Nostr Wallet Connect link",
                      checks.check_nwc_url(LN_ADDRESS))

    def test_incomplete_link(self):
        no_secret = "nostr+walletconnect://" + "ab" * 32 + "?relay=wss://relay.example.com"
        self.assertIn("missing or wrong", checks.check_nwc_url(no_secret))

    def test_agrees_with_wallet_parser(self):
        samples = [NWC, "nwc:" + NWC[22:], NWC.replace("secret=", "secrex="),
                   NWC.replace("ab" * 32, "AB" * 32), "nostr+walletconnect://", LN_ADDRESS, ""]
        for text in samples:
            try:
                NWCWallet.parse_nwc_url(None, text)
                parses = True
            except Exception:
                parses = False
            self.assertEqual(checks.check_nwc_url(text) is True, parses, text)


class TestOnchain(unittest.TestCase):

    def test_xpub_field_accepts_keys_and_addresses(self):
        for text in (XPUB, ZPUB, P2WPKH, P2TR, P2PKH, P2SH, P2WPKH.upper()):
            self.assertIs(checks.check_xpub_or_address(text), True, text)

    def test_xpub_field_bitcoin_link(self):
        msg = checks.check_xpub_or_address("bitcoin:" + P2WPKH + "?amount=0.001")
        self.assertIn('Enter just the address', msg)

    def test_xpub_field_wrong_code(self):
        self.assertIn("looks like a Nostr Wallet Connect link, not an xpub or Bitcoin address",
                      checks.check_xpub_or_address(NWC))
        # A typo in an address fails its checksum.
        self.assertIsNot(checks.check_xpub_or_address(P2WPKH[:-1] + "5"), True)

    def test_fixed_receive_address(self):
        for text in (P2WPKH, P2PKH, "bitcoin:" + P2WPKH, "bitcoin:" + P2SH + "?label=piggy"):
            self.assertIs(checks.check_bitcoin_address(text), True, text)
        self.assertIn("looks like a Lightning Address, not a Bitcoin address",
                      checks.check_bitcoin_address(LN_ADDRESS))
        self.assertIn("looks like an xpub, not a Bitcoin address",
                      checks.check_bitcoin_address(XPUB))
        self.assertIn("missing or wrong", checks.check_bitcoin_address("bitcoin:bc1qnope"))

    def test_blockbook_url(self):
        self.assertIs(checks.check_blockbook_url("https://btc1.trezor.io"), True)
        self.assertIn("like https://btc1.trezor.io",
                      checks.check_blockbook_url("https://btc1.trezor.io/?x=1"))
        self.assertIn("looks like a Bitcoin address, not a Blockbook server address",
                      checks.check_blockbook_url(P2WPKH))


class TestAddScanChecks(unittest.TestCase):

    def _settings(self, suffix):
        keys = ["wallet_type", "lnbits_url", "lnbits_readkey", "lnbits_static_receive_code",
                "nwc_url", "nwc_static_receive_code", "onchain_xpub",
                "onchain_blockbook_url", "onchain_static_receive_code"]
        return [{"title": k, "key": k + suffix} for k in keys]

    def _check_all(self, suffix):
        settings = self._settings(suffix)
        checks.add_scan_checks(settings, suffix)
        by_key = {s["key"][:len(s["key"]) - len(suffix)]: s for s in settings}
        self.assertFalse("scan_check" in by_key["wallet_type"])
        for key, check in checks.SCAN_CHECKS.items():
            self.assertIs(by_key[key]["scan_check"], check, key)

    def test_slot_one(self):
        self._check_all("")

    def test_slot_two_suffix(self):
        self._check_all("_2")

    def test_other_slot_keys_untouched(self):
        settings = [{"title": "x", "key": "lnbits_url"}]
        checks.add_scan_checks(settings, "_2")
        self.assertFalse("scan_check" in settings[0])


if __name__ == "__main__":
    unittest.main()
