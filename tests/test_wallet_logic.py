"""
Unit tests for the money-path logic in wallet.py and nwc_wallet.py:

  - ensure_lightning_prefix      (QR receive-code prefixing, wallet.py)
  - Wallet.handle_new_balance    (balance state machine + callback deltas)
  - NWCWallet._mgr_notification_cb (live NIP-47 payment notifications)
  - Wallet._decode_surrogate_pairs (emoji tofu fix)
  - Wallet.try_parse_as_zap + NWCWallet.getCommentFromTransaction

All pure logic — no network, no LVGL. TaskManager is swapped for a
recorder that closes coroutines unrun, and wallets get slot_key=None so
wallet_cache writes are no-ops (the base-class guard).

Note: nostr_service intentionally does NOT use ensure_lightning_prefix
anymore (commit 53960e8 — lud16 from an NWC URL is only forwarded when
it looks like a LUD-16, i.e. contains "@"). The function remains the
prefixing helper for displaywallet's QR paths, which is what these
tests pin down.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_wallet_logic.py
"""

import json
import sys
import unittest

# The MPOS nostr app's boot service can pre-load its own (older)
# nostr_service into sys.modules, shadowing Lightning Piggy's copy —
# purge so the imports below resolve to the app's own modules.
for _m in ("nostr_service", "nwc_wallet", "wallet", "payment", "unique_sorted_list"):
    if _m in sys.modules:
        del sys.modules[_m]

import wallet
from wallet import Wallet, ensure_lightning_prefix
from nwc_wallet import NWCWallet

NWC_URL = (
    "nostr+walletconnect://" + ("ab" * 32)
    + "?relay=wss://relay.example.com&secret=" + ("cd" * 32)
)


class _FakeTask:
    def done(self):
        return False


class _RecordingTaskManager:
    """Counts create_task calls and closes the coroutine immediately so
    no wallet task actually runs in the test process."""

    def __init__(self):
        self.created = 0

    def create_task(self, coro):
        self.created += 1
        try:
            coro.close()
        except Exception:
            pass
        return _FakeTask()


class _TestWallet(Wallet):
    """Minimal concrete wallet: only the coroutine factory that
    handle_new_balance schedules has to exist."""

    async def fetch_payments(self):
        pass


class TestEnsureLightningPrefix(unittest.TestCase):

    def test_empty_and_none_pass_through(self):
        self.assertEqual(ensure_lightning_prefix(""), "")
        self.assertEqual(ensure_lightning_prefix(None), None)

    def test_already_prefixed_unchanged(self):
        self.assertEqual(
            ensure_lightning_prefix("lightning:piggy@example.com"),
            "lightning:piggy@example.com")

    def test_prefix_check_is_case_insensitive(self):
        self.assertEqual(
            ensure_lightning_prefix("LIGHTNING:piggy@example.com"),
            "LIGHTNING:piggy@example.com")

    def test_other_uri_schemes_unchanged(self):
        for code in ("bitcoin:bc1qexample", "http://example.com/lnurlp",
                     "https://example.com/.well-known/lnurlp/piggy",
                     "mailto:piggy@example.com"):
            self.assertEqual(ensure_lightning_prefix(code), code)

    def test_lud16_gets_prefixed(self):
        self.assertEqual(
            ensure_lightning_prefix("piggy@example.com"),
            "lightning:piggy@example.com")

    def test_lnurl_bech32_gets_prefixed(self):
        self.assertEqual(
            ensure_lightning_prefix("LNURL1DP68GURN8GHJ7MRWW4EXCTNZD9NHXATW"),
            "lightning:LNURL1DP68GURN8GHJ7MRWW4EXCTNZD9NHXATW")

    def test_bolt11_invoices_get_prefixed(self):
        for inv in ("lnbc210n1example", "lntb210n1example", "lnbcrt210n1example"):
            self.assertEqual(ensure_lightning_prefix(inv), "lightning:" + inv)

    def test_unknown_format_unchanged(self):
        self.assertEqual(ensure_lightning_prefix("foobar"), "foobar")

    def test_whitespace_stripped_before_prefixing(self):
        self.assertEqual(
            ensure_lightning_prefix("  piggy@example.com "),
            "lightning:piggy@example.com")


class TestHandleNewBalance(unittest.TestCase):

    def setUp(self):
        self._orig_tm = wallet.TaskManager
        self.tm = _RecordingTaskManager()
        wallet.TaskManager = self.tm
        self.w = _TestWallet()
        self.deltas = []
        self.w.balance_updated_cb = self.deltas.append

    def tearDown(self):
        wallet.TaskManager = self._orig_tm

    def test_first_balance_fires_with_zero_delta_even_when_zero(self):
        # A brand-new empty wallet must still update the UI (show "0").
        self.w.handle_new_balance(0)
        self.assertEqual(self.deltas, [0])
        self.assertEqual(self.w.last_known_balance, 0)
        self.assertEqual(self.tm.created, 1)  # initial payments fetch

    def test_first_balance_can_skip_payments_fetch(self):
        self.w.handle_new_balance(42, False)
        self.assertEqual(self.deltas, [0])
        self.assertEqual(self.tm.created, 0)

    def test_change_fires_signed_delta(self):
        self.w.handle_new_balance(100)
        self.w.handle_new_balance(121)
        self.w.handle_new_balance(100)
        self.assertEqual(self.deltas, [0, 21, -21])
        self.assertEqual(self.w.last_known_balance, 100)

    def test_unchanged_balance_is_silent(self):
        self.w.handle_new_balance(100)
        created_after_first = self.tm.created
        self.w.handle_new_balance(100)
        self.assertEqual(self.deltas, [0])
        self.assertEqual(self.tm.created, created_after_first)

    def test_none_balance_ignored(self):
        self.w.handle_new_balance(None)
        self.assertEqual(self.deltas, [])
        self.assertEqual(self.w.last_known_balance, None)

    def test_stopped_wallet_ignores_balance(self):
        self.w.keep_running = False
        self.w.handle_new_balance(100)
        self.assertEqual(self.deltas, [])
        self.assertEqual(self.w.last_known_balance, None)


class TestNWCNotifications(unittest.TestCase):

    def setUp(self):
        self._orig_tm = wallet.TaskManager
        self.tm = _RecordingTaskManager()
        wallet.TaskManager = self.tm
        self.w = NWCWallet(NWC_URL)
        self.w.slot_key = None  # keep wallet_cache writes out of unit tests
        self.deltas = []
        self.payment_pings = []
        self.qr_pings = []
        self.polls = []
        self.w.balance_updated_cb = self.deltas.append
        self.w.payments_updated_cb = lambda: self.payment_pings.append(1)
        self.w.static_receive_code_updated_cb = lambda: self.qr_pings.append(1)
        self.w.poll_success_cb = lambda: self.polls.append(1)

    def tearDown(self):
        wallet.TaskManager = self._orig_tm

    def test_incoming_with_no_prior_balance(self):
        self.w._mgr_notification_cb({
            "type": "incoming", "amount": 21000,
            "created_at": 1767713767, "description": "Good",
        })
        self.assertEqual(self.w.last_known_balance, 21)  # 21000 msat -> 21 sats
        self.assertEqual(self.deltas, [0])  # first balance: delta 0
        self.assertEqual(len(self.w.payment_list), 1)
        payment = self.w.payment_list.get(0)
        self.assertEqual(payment.amount_sats, 21)
        self.assertEqual(payment.comment, "Good")
        self.assertEqual(self.payment_pings, [1])
        # incoming path must NOT schedule a payments refetch — the
        # notification itself carries the payment.
        self.assertEqual(self.tm.created, 0)

    def test_incoming_adds_to_known_balance(self):
        self.w.last_known_balance = 100
        self.w._mgr_notification_cb({
            "type": "incoming", "amount": 21000,
            "created_at": 1767713767, "description": "tip",
        })
        self.assertEqual(self.w.last_known_balance, 121)
        self.assertEqual(self.deltas, [21])

    def test_msat_rounding(self):
        self.w._mgr_notification_cb({
            "type": "incoming", "amount": 1499,
            "created_at": 1767713767, "description": "",
        })
        self.assertEqual(self.w.last_known_balance, 1)  # round(1.499)

    def test_outgoing_applies_immediately_as_negative(self):
        # Since the 0.5.1 outgoing fix, a send mirrors the incoming
        # branch with a negative amount: balance and list update
        # immediately instead of waiting for the next poll.
        self.w.last_known_balance = 100
        self.w._mgr_notification_cb({
            "type": "outgoing", "amount": 5000,
            "created_at": 1767713767, "description": "",
        })
        self.assertEqual(self.w.last_known_balance, 95)
        self.assertEqual(self.deltas, [-5])
        self.assertEqual(len(self.w.payment_list), 1)
        self.assertEqual(self.w.payment_list.get(0).amount_sats, -5)
        self.assertEqual(self.polls, [1])

    def test_outgoing_without_prior_balance_skips_balance_math(self):
        # No baseline to subtract from — balance stays unknown rather
        # than going negative, but the payment still lands in the list.
        self.w._mgr_notification_cb({
            "type": "outgoing", "amount": 5000,
            "created_at": 1767713767, "description": "",
        })
        self.assertEqual(self.w.last_known_balance, None)
        self.assertEqual(self.deltas, [])
        self.assertEqual(len(self.w.payment_list), 1)
        self.assertEqual(self.w.payment_list.get(0).amount_sats, -5)

    def test_unknown_type_ignored_without_crash(self):
        self.w._mgr_notification_cb({
            "type": "sideways", "amount": 5000,
            "created_at": 1767713767, "description": "",
        })
        self.assertEqual(self.w.last_known_balance, None)
        self.assertEqual(len(self.w.payment_list), 0)

    def test_static_receive_code_notification_routed(self):
        self.w._mgr_notification_cb({"static_receive_code": "piggy@example.com"})
        self.assertEqual(self.w.static_receive_code, "piggy@example.com")
        self.assertEqual(self.qr_pings, [1])
        self.assertEqual(self.deltas, [])  # no balance side effects


class TestSurrogatePairDecoding(unittest.TestCase):
    # _decode_surrogate_pairs ignores self -> exercised unbound.

    def _decode(self, text):
        return Wallet._decode_surrogate_pairs(None, text)

    def test_escaped_emoji_decodes_to_single_codepoint(self):
        # Build the input the way it reaches the app: JSON with a
        # 🙂 escape ("slightly smiling face"). Whether the JSON
        # stack keeps surrogates or collapses them, the result after
        # _decode_surrogate_pairs must be the real code point.
        text = json.loads('"\\ud83d\\ude42"')
        self.assertEqual(self._decode(text), chr(0x1F642))

    def test_surrounding_text_preserved(self):
        text = json.loads('"gm \\ud83d\\ude42!"')
        self.assertEqual(self._decode(text), "gm " + chr(0x1F642) + "!")

    def test_plain_ascii_unchanged(self):
        self.assertEqual(self._decode("just sats"), "just sats")

    def test_non_string_input_returned_as_is(self):
        self.assertEqual(self._decode(None), None)
        self.assertEqual(self._decode(42), 42)


class TestCommentParsing(unittest.TestCase):

    def setUp(self):
        self._orig_tm = wallet.TaskManager
        wallet.TaskManager = _RecordingTaskManager()
        self.w = NWCWallet(NWC_URL)
        self.w.slot_key = None

    def tearDown(self):
        wallet.TaskManager = self._orig_tm

    def test_zap_json_extracts_content(self):
        zap = '{"content": "Great piggy!", "kind": 9734, "pubkey": "ee"}'
        self.assertEqual(self.w.try_parse_as_zap(zap), "zapped - Great piggy!")

    def test_plain_comment_passes_through(self):
        self.assertEqual(self.w.try_parse_as_zap("hello"), "hello")

    def test_json_without_content_passes_through(self):
        self.assertEqual(self.w.try_parse_as_zap('{"foo": 1}'), '{"foo": 1}')

    def test_lnurlp_metadata_array_takes_text_plain(self):
        desc = '[["text/identifier","piggy@example.com"],["text/plain","Thanks!"]]'
        comment = self.w.getCommentFromTransaction({"description": desc})
        self.assertEqual(comment, "Thanks!")

    def test_null_description_returns_none(self):
        self.assertEqual(
            self.w.getCommentFromTransaction({"description": None}), None)

    def test_plain_text_description_used_as_is(self):
        self.assertEqual(
            self.w.getCommentFromTransaction({"description": "hello"}), "hello")

    def test_missing_description_yields_empty(self):
        self.assertEqual(self.w.getCommentFromTransaction({}), "")

    def test_zap_description_detected(self):
        desc = '{"content": "gm", "kind": 9734}'
        self.assertEqual(
            self.w.getCommentFromTransaction({"description": desc}),
            "zapped - gm")


if __name__ == "__main__":
    unittest.main()
