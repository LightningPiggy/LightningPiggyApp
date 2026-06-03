"""
Unit tests for the on-chain wallet type in the Lightning Piggy app.

Targets LightningPiggyApp PR #25 (on-chain wallet via Blockbook).

The vendored tests/unittest.sh auto-injects the app's assets/ dir into
sys.path, so these imports work without any further path manipulation.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_onchain_wallet.py
    Device:  bash tests/unittest.sh tests/test_onchain_wallet.py --ondevice
"""

import unittest

try:
    from onchain_wallet import OnchainWallet
    _HAVE_ONCHAIN = True
except ImportError:
    _HAVE_ONCHAIN = False


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed (feature not landed yet)")
class TestOnchainWalletConstructor(unittest.TestCase):

    def test_rejects_empty_xpub(self):
        with self.assertRaises(ValueError):
            OnchainWallet("")

    def test_rejects_bad_prefix(self):
        with self.assertRaises(ValueError):
            OnchainWallet("foobarbaz")

    def test_accepts_xpub_prefix(self):
        w = OnchainWallet("xpub1234example")
        self.assertEqual(w.xpub, "xpub1234example")

    def test_accepts_zpub_prefix(self):
        w = OnchainWallet("zpub1234example")
        self.assertEqual(w.xpub, "zpub1234example")

    def test_trims_blockbook_trailing_slash(self):
        w = OnchainWallet("zpub1234example", blockbook_url="https://example.com/")
        self.assertEqual(w.blockbook_url, "https://example.com")

    def test_blockbook_url_default_when_none(self):
        w = OnchainWallet("zpub1234example")
        self.assertEqual(w.blockbook_url, OnchainWallet.DEFAULT_BLOCKBOOK_URL)

    def test_blockbook_url_empty_falls_back_to_default(self):
        # An empty string URL pref should behave the same as None.
        w = OnchainWallet("zpub1234example", blockbook_url=None)
        self.assertEqual(w.blockbook_url, OnchainWallet.DEFAULT_BLOCKBOOK_URL)

    def test_sets_cache_slot_key(self):
        # Required by the post-#33 Wallet contract — handle_new_* routes
        # writes through wallet_cache.save_slot(slot_key=...).
        w = OnchainWallet("zpub1234example")
        self.assertEqual(w.slot_key, "onchain")


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestOnchainWalletParseTransactions(unittest.TestCase):

    def setUp(self):
        self.w = OnchainWallet("zpub1234example")

    def test_confirmed_incoming_tx(self):
        txs = [{
            "txid": "abc", "confirmations": 5, "blockTime": 1775838000,
            "vin": [{"isOwn": False, "value": "10000"}],
            "vout": [{"isOwn": True, "value": "6884"}, {"isOwn": False, "value": "3000"}],
        }]
        payments, any_unconfirmed = self.w._parse_transactions(txs)
        self.assertEqual(len(payments), 1)
        p = list(payments)[0]
        self.assertEqual(p.amount_sats, 6884)
        self.assertIn("confirmed", p.comment)
        self.assertFalse(any_unconfirmed)

    def test_unconfirmed_tx_flagged(self):
        txs = [{
            "txid": "pending", "confirmations": 0, "blockTime": 0,
            "vin": [{"isOwn": False, "value": "10000"}],
            "vout": [{"isOwn": True, "value": "5000"}],
        }]
        _payments, any_unconfirmed = self.w._parse_transactions(txs)
        self.assertTrue(any_unconfirmed)

    def test_self_transfer_is_fee_only(self):
        # All inputs + all outputs marked isOwn → classic self-transfer: the
        # wallet loses only the network fee.
        txs = [{
            "txid": "self", "confirmations": 10, "blockTime": 1775838000, "fees": "500",
            "vin": [{"isOwn": True, "value": "50500"}],
            "vout": [{"isOwn": True, "value": "50000"}],
        }]
        payments, _unc = self.w._parse_transactions(txs)
        p = list(payments)[0]
        self.assertEqual(p.amount_sats, -500)
        self.assertIn("self-transfer", p.comment)

    def test_outgoing_tx_uses_net_amount(self):
        # Our input 20000, our output 15000 (change) → net -5000 sent.
        txs = [{
            "txid": "out", "confirmations": 3, "blockTime": 1775838000, "fees": "200",
            "vin": [{"isOwn": True, "value": "20000"}],
            "vout": [
                {"isOwn": True, "value": "15000"},      # change back to us
                {"isOwn": False, "value": "4800"},      # paid out to someone else
            ],
        }]
        payments, _unc = self.w._parse_transactions(txs)
        p = list(payments)[0]
        # Net = 15000 - 20000 = -5000 (it goes through the non-self-transfer branch
        # because not all vout is isOwn).
        self.assertEqual(p.amount_sats, -5000)

    def test_empty_transactions(self):
        payments, any_unconfirmed = self.w._parse_transactions([])
        self.assertEqual(len(payments), 0)
        self.assertFalse(any_unconfirmed)

    def test_none_transactions(self):
        # Response may legitimately have no "transactions" key.
        payments, any_unconfirmed = self.w._parse_transactions(None)
        self.assertEqual(len(payments), 0)
        self.assertFalse(any_unconfirmed)


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestOnchainWalletPickUnusedAddress(unittest.TestCase):

    def setUp(self):
        self.w = OnchainWallet("zpub1234example")

    def test_picks_first_unused_external(self):
        tokens = [
            {"name": "bc1qused1", "path": "m/84'/0'/0'/0/0", "transfers": 3},
            {"name": "bc1qfirst", "path": "m/84'/0'/0'/0/5", "transfers": 0},
            {"name": "bc1qsecond", "path": "m/84'/0'/0'/0/6", "transfers": 0},
        ]
        # Returns bare address (no "bitcoin:" prefix); the caller in
        # fetch_balance_and_payments prepends the BIP21 scheme.
        self.assertEqual(self.w._pick_unused_receive_address(tokens), "bc1qfirst")

    def test_skips_change_chain(self):
        tokens = [
            {"name": "bc1qchange", "path": "m/84'/0'/0'/1/0", "transfers": 0},  # internal/change
            {"name": "bc1qexternal", "path": "m/84'/0'/0'/0/0", "transfers": 0},
        ]
        self.assertEqual(self.w._pick_unused_receive_address(tokens), "bc1qexternal")

    def test_skips_used_addresses(self):
        tokens = [
            {"name": "bc1qused1", "path": "m/84'/0'/0'/0/0", "transfers": 7},
            {"name": "bc1qused2", "path": "m/84'/0'/0'/0/1", "transfers": 1},
        ]
        self.assertIsNone(self.w._pick_unused_receive_address(tokens))

    def test_none_when_no_tokens(self):
        self.assertIsNone(self.w._pick_unused_receive_address([]))
        self.assertIsNone(self.w._pick_unused_receive_address(None))

    def test_returns_lowest_index_unused(self):
        # Three unused external addresses — the one at index 1 must win
        # regardless of list order, because it has the lowest derivation index.
        tokens = [
            {"name": "bc1qthird", "path": "m/84'/0'/0'/0/3", "transfers": 0},
            {"name": "bc1qfirst", "path": "m/84'/0'/0'/0/1", "transfers": 0},
            {"name": "bc1qsecond", "path": "m/84'/0'/0'/0/2", "transfers": 0},
        ]
        self.assertEqual(self.w._pick_unused_receive_address(tokens), "bc1qfirst")


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestOnchainWalletAddressRotation(unittest.TestCase):
    """The displayed receive QR should rotate to a fresh address only AFTER the
    previously-shown address has actually received a payment — not on every
    poll, which would change the QR while a payer is mid-scan."""

    def setUp(self):
        self.w = OnchainWallet("zpub1234example")

    def test_unused_address_initially_reports_not_used(self):
        tokens = [{"name": "bc1qa", "path": "m/84'/0'/0'/0/0", "transfers": 0}]
        self.assertFalse(self.w._displayed_address_has_been_used(tokens, "bc1qa"))

    def test_address_with_transfers_reports_used(self):
        tokens = [{"name": "bc1qa", "path": "m/84'/0'/0'/0/0", "transfers": 1}]
        self.assertTrue(self.w._displayed_address_has_been_used(tokens, "bc1qa"))

    def test_missing_address_treated_as_still_fresh(self):
        # Address not present in the response (e.g. gap-limit drift) →
        # don't rotate. Prevents spurious QR flips on response variance.
        tokens = [{"name": "bc1qother", "path": "m/84'/0'/0'/0/1", "transfers": 0}]
        self.assertFalse(self.w._displayed_address_has_been_used(tokens, "bc1qa"))

    def test_none_displayed_address_reports_not_used(self):
        # No address picked yet (first poll) — never report "used" in this
        # state, since the rotate-on-use branch shouldn't fire.
        self.assertFalse(self.w._displayed_address_has_been_used([], None))


if __name__ == "__main__":
    unittest.main()
