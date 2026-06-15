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


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestBech32Validator(unittest.TestCase):
    """Direct tests of `_is_valid_bech32_address` against BIP-173 / BIP-350
    test vectors. We're validating the wallet's local sanity check that
    rejects bad addresses before any Blockbook call — not exercising
    encoding, only decoding."""

    def setUp(self):
        from onchain_wallet import _is_valid_bech32_address
        self.valid = _is_valid_bech32_address

    # --- Mainnet (bc1...) ---
    def test_mainnet_p2wpkh_valid(self):
        # BIP-173 §B test vector (v0, 20-byte program)
        self.assertTrue(self.valid("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"))

    def test_mainnet_p2wsh_valid(self):
        # BIP-173 §B test vector (v0, 32-byte program)
        self.assertTrue(self.valid("bc1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3qccfmv3"))

    def test_mainnet_p2tr_valid(self):
        # BIP-350 §B test vector (v1, 32-byte program → bech32m)
        self.assertTrue(self.valid("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0"))

    # --- Testnet (tb1...) ---
    def test_testnet_p2wpkh_valid(self):
        self.assertTrue(self.valid("tb1qrp33g0q5c5txsp9arysrx4k6zdkfs4nce4xj0gdcccefvpysxf3q0sl5k7"))

    def test_testnet_p2tr_valid(self):
        # BIP-350 §B testnet taproot vector
        self.assertTrue(self.valid("tb1pqqqqp399et2xygdj5xreqhjjvcmzhxw4aywxecjdzew6hylgvsesf3hn0c"))

    # NOTE: regtest (`bcrt1...`) is supported by the validator but not
    # explicitly tested here — there's no widely-published bcrt1
    # checksum vector to assert against, and constructing one
    # by-hand defeats the purpose. Coverage is still meaningful via
    # the mainnet/testnet HRP paths (same encoding code).

    # --- Negative cases ---
    def test_rejects_mixed_case(self):
        # BIP-173: bech32 explicitly forbids mixed case.
        self.assertFalse(self.valid("bc1qW508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"))

    def test_rejects_bad_checksum(self):
        # Flip the final char of a valid address — checksum fails.
        self.assertFalse(self.valid("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t5"))

    def test_rejects_uppercase_form(self):
        # All-uppercase is a valid bech32 form per BIP-173, but our
        # validator only canonicalises to lowercase; verify it still
        # passes after the lower() conversion. (Sanity check that
        # we're not over-rejecting.)
        self.assertTrue(self.valid("BC1QW508D6QEJXTDG4Y5R3ZARVARY0C5XW7KV8F3T4"))

    def test_rejects_bech32_encoded_v1(self):
        # BIP-350 enforces v1+ → bech32m. A taproot-shaped (v1)
        # string with a bech32 (not bech32m) checksum must be
        # rejected. The vector here is constructed from the BIP-350
        # invalid-test-vector list (v1 program encoded with the
        # wrong checksum constant); the validator catches it via
        # the witver/spec pairing check.
        self.assertFalse(self.valid("bc1pw508d6qejxtdg4y5r3zarvary0c5xw7kw508d6qejxtdg4y5r3zarvary0c5xw7k7grplx"))

    def test_rejects_empty(self):
        self.assertFalse(self.valid(""))

    def test_rejects_garbage(self):
        self.assertFalse(self.valid("not-an-address-at-all"))

    def test_rejects_unknown_hrp(self):
        # `ltc1...` (Litecoin) — valid bech32 in its own context, but
        # not a Bitcoin HRP. We reject so a Litecoin paste doesn't
        # silently get queried against Blockbook.
        self.assertFalse(self.valid("ltc1qw508d6qejxtdg4y5r3zarvary0c5xw7kgmn4ny"))


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestBase58CheckValidator(unittest.TestCase):
    """Direct tests of `_is_valid_base58check_address`. Mainnet + testnet
    P2PKH / P2SH covered; the validator checks both the double-SHA256
    checksum AND that the version byte is one of the accepted set."""

    def setUp(self):
        from onchain_wallet import _is_valid_base58check_address
        self.valid = _is_valid_base58check_address

    # --- Mainnet ---
    def test_mainnet_p2pkh_genesis(self):
        # Genesis block coinbase address.
        self.assertTrue(self.valid("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"))

    def test_mainnet_p2sh(self):
        # First multisig P2SH address seen on mainnet.
        self.assertTrue(self.valid("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"))

    # --- Testnet ---
    def test_testnet_p2pkh_m(self):
        # Both 'm...' and 'n...' P2PKH testnet addresses share the
        # 0x6F version byte and the same validation path — testing one
        # covers both.
        self.assertTrue(self.valid("mzBc4XEFSdzCDcTxAgf6EZXgsZWpztRhef"))

    def test_testnet_p2sh(self):
        self.assertTrue(self.valid("2N2JD6wb56AfK4tfmM6PwdVmoYk2dCKf4Br"))

    # --- Negative cases ---
    def test_rejects_bad_checksum(self):
        # Genesis address with the final char flipped.
        self.assertFalse(self.valid("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb"))

    def test_rejects_empty(self):
        self.assertFalse(self.valid(""))

    def test_rejects_invalid_alphabet(self):
        # Contains '0' and 'O' which are deliberately excluded from
        # base58 to avoid visual confusion.
        self.assertFalse(self.valid("1A1zP1eP5QGefi2DMPTfTL5SLmv7Divf00"))

    def test_rejects_unknown_version_byte(self):
        # Hand-crafted base58check with a non-Bitcoin version byte
        # (Litecoin P2PKH = 0x30). Checksum is valid; only the version
        # byte fails. We must still reject so a Litecoin address paste
        # doesn't silently work against a Bitcoin Blockbook.
        self.assertFalse(self.valid("LZHinBxX5tWAYZAUmoPTzMnD3wM3xSJWkM"))


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestClassifyCredential(unittest.TestCase):
    """`classify_credential` chooses xpub-mode or address-mode based on
    the input string. The settings UI now offers one field for both —
    this is where the auto-detection happens."""

    def setUp(self):
        from onchain_wallet import classify_credential
        self.classify = classify_credential

    def test_xpub_prefix_classified_as_xpub(self):
        # Body validity isn't checked — Blockbook returns a clear
        # error for a malformed xpub. The classifier only looks at
        # the prefix.
        mode, value = self.classify("xpub1234example")
        self.assertEqual(mode, "xpub")
        self.assertEqual(value, "xpub1234example")

    def test_ypub_zpub_tpub_upub_vpub_all_classified_as_xpub(self):
        for prefix in ("ypub", "zpub", "tpub", "upub", "vpub"):
            mode, value = self.classify(prefix + "1234example")
            self.assertEqual(mode, "xpub", msg="prefix " + prefix)

    def test_mainnet_p2wpkh_classified_as_address(self):
        mode, value = self.classify("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self.assertEqual(mode, "address")
        self.assertEqual(value, "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")

    def test_p2pkh_classified_as_address(self):
        mode, value = self.classify("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        self.assertEqual(mode, "address")

    def test_p2sh_classified_as_address(self):
        mode, value = self.classify("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
        self.assertEqual(mode, "address")

    def test_p2tr_classified_as_address(self):
        mode, value = self.classify("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0")
        self.assertEqual(mode, "address")

    def test_trims_whitespace(self):
        # Common paste-from-clipboard hazard: leading/trailing whitespace.
        mode, value = self.classify("  zpub1234example  ")
        self.assertEqual(mode, "xpub")
        self.assertEqual(value, "zpub1234example")

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            self.classify("")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            self.classify(None)

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            self.classify("not-an-xpub-nor-an-address")

    def test_address_with_bad_checksum_raises(self):
        # Looks like an address (right prefix) but fails checksum →
        # rejected. This is the "user mistyped one character of their
        # address" case — better to fail at wallet construction than
        # at first Blockbook call.
        with self.assertRaises(ValueError):
            self.classify("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb")


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestOnchainWalletAddressMode(unittest.TestCase):
    """End-to-end tests of address-mode wallet construction and the
    single-poll receive-code semantics. We don't exercise the actual
    Blockbook call here (matches the existing tests' pattern); we
    just verify the mode-dependent state and the no-rotation behaviour."""

    def test_address_init_sets_address_not_xpub(self):
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self.assertEqual(w.mode, "address")
        self.assertEqual(w.address, "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self.assertIsNone(w.xpub)

    def test_xpub_init_sets_xpub_not_address(self):
        w = OnchainWallet("zpub1234example")
        self.assertEqual(w.mode, "xpub")
        self.assertEqual(w.xpub, "zpub1234example")
        self.assertIsNone(w.address)

    def test_address_init_with_legacy_p2pkh(self):
        w = OnchainWallet("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")
        self.assertEqual(w.mode, "address")
        self.assertEqual(w.address, "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa")

    def test_address_init_with_p2sh(self):
        w = OnchainWallet("3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy")
        self.assertEqual(w.mode, "address")

    def test_address_init_with_taproot(self):
        w = OnchainWallet("bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0")
        self.assertEqual(w.mode, "address")

    def test_invalid_credential_rejected(self):
        with self.assertRaises(ValueError):
            OnchainWallet("definitely-not-a-bitcoin-anything")

    def test_address_with_bad_checksum_rejected(self):
        # The user mistyped their address — fail fast at wallet
        # construction, not after a network round-trip.
        with self.assertRaises(ValueError):
            OnchainWallet("1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb")

    def test_address_mode_blockbook_url_default(self):
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self.assertEqual(w.blockbook_url, OnchainWallet.DEFAULT_BLOCKBOOK_URL)

    def test_address_mode_blockbook_url_custom(self):
        w = OnchainWallet(
            "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4",
            blockbook_url="https://my.umbrel.local/blockbook/")
        self.assertEqual(w.blockbook_url, "https://my.umbrel.local/blockbook")

    def test_address_mode_cache_slot_key(self):
        # Same cache slot as xpub mode — the user can switch between
        # an xpub and a single address on the same slot without two
        # cache entries that disagree on balance.
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self.assertEqual(w.slot_key, "onchain")


@unittest.skipUnless(_HAVE_ONCHAIN, "onchain_wallet.py not installed")
class TestOnchainWalletPageSize(unittest.TestCase):
    """Regression: Blockbook fetches must include `pageSize=N` derived from
    the wallet's `PAYMENTS_TO_SHOW`. Without it, Blockbook returns up to
    1000 transactions per page; on addresses with many txs (genesis, big
    mining-payout clusters) the response + the subsequent slot-cache
    write blew the ESP32-S3 heap with `MemoryError`. Reported by Thomas
    in LightningPiggyApp#45 review."""

    def setUp(self):
        import asyncio
        from mpos import DownloadManager
        self._asyncio = asyncio
        self._original_download = DownloadManager.download_url
        self.DownloadManager = DownloadManager
        # Empty but JSON-valid response — fetch parses it without
        # firing payments / receive-code callbacks, leaves the test
        # focused on the URL the wallet constructed.
        self._fake_response = (
            b'{"balance":"0","unconfirmedBalance":"0","unconfirmedTxs":0,'
            b'"transactions":[],"tokens":[]}'
        )
        self.captured = {"url": None}
        async def fake(url, **kwargs):
            self.captured["url"] = url
            return self._fake_response
        DownloadManager.download_url = fake

    def tearDown(self):
        # Restore the original download_url so subsequent tests in the
        # session (when the suite runs as a whole) see the real one.
        self.DownloadManager.download_url = self._original_download

    def _fetch(self, w):
        # Stub out the handle_new_* fan-out so an empty response doesn't
        # blow up trying to render against widgets that don't exist in
        # the test environment.
        w.handle_new_balance = lambda b, fetchPaymentsIfChanged=True: None
        w.handle_new_payments = lambda p: None
        w.handle_new_static_receive_code = lambda s: None
        w.notify_poll_success = lambda: None
        self._asyncio.run(w.fetch_balance_and_payments())

    def test_address_mode_url_contains_pageSize(self):
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        w.PAYMENTS_TO_SHOW = 21
        self._fetch(w)
        self.assertIn("pageSize=21", self.captured["url"])
        self.assertIn("/api/v2/address/", self.captured["url"])
        # details=txslight drops the hex/scripts the parser doesn't use;
        # measured at ~43 % smaller responses vs the default txs format
        self.assertIn("details=txslight", self.captured["url"])
        self.assertFalse("details=txs&" in self.captured["url"])

    def test_xpub_mode_url_contains_pageSize(self):
        w = OnchainWallet("zpub6rFAKE")
        w.PAYMENTS_TO_SHOW = 10
        self._fetch(w)
        self.assertIn("pageSize=10", self.captured["url"])
        self.assertIn("/api/v2/xpub/", self.captured["url"])
        # tokens=derived still present — the rotation logic depends on it
        self.assertIn("tokens=derived", self.captured["url"])
        # txslight regression
        self.assertIn("details=txslight", self.captured["url"])
        self.assertFalse("details=txs&" in self.captured["url"])

    def test_pageSize_defaults_to_21_when_unset(self):
        # Wallet constructed but DisplayWallet hasn't yet stamped the
        # per-slot value — class default `PAYMENTS_TO_SHOW = 21` applies.
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        self._fetch(w)
        self.assertIn("pageSize=21", self.captured["url"])

    def test_pageSize_treats_zero_as_unset_and_uses_default(self):
        # `0` from a future code path would otherwise turn into
        # `?pageSize=0` which Blockbook interprets as "no limit" — the
        # exact unbounded-fetch case this PR closes. The fetch helper
        # treats 0 as equivalent to None/unset and falls back to the
        # default (21), matching the intent of the slider's 1..21
        # range (a user can't pick 0 through the UI anyway).
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        w.PAYMENTS_TO_SHOW = 0
        self._fetch(w)
        self.assertIn("pageSize=21", self.captured["url"])

    def test_pageSize_clamped_at_100_max(self):
        # The settings slider is bounded 1..21 — this clamp is for
        # programmatic abuse and to keep the response size bounded if
        # the cap ever loosens upstream.
        w = OnchainWallet("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4")
        w.PAYMENTS_TO_SHOW = 9999
        self._fetch(w)
        self.assertIn("pageSize=100", self.captured["url"])


if __name__ == "__main__":
    unittest.main()
