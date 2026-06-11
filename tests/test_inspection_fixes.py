"""
Regression tests for the 2026-06 code-inspection fixes:

  Batch A (user-visible):
    - NWC list_transactions honours PAYMENTS_TO_SHOW (was hardcoded 6)
    - LNBits websocket on_message survives a missing wallet_balance
      (was: NameError on unbound new_balance, notification dropped)
    - LNBits extra.comment list handling (was: rendered "['yes']");
      extra without comment no longer wipes the memo

  Batch B (robustness):
    - Wallet.__str__ returns the subclass name (was: NameError on
      un-imported class references)
    - UniqueSortedList == None is False, not TypeError
    - NWC list_transactions outgoing amounts render negative

  Batch C (ESP32 longevity):
    - UniqueSortedList caps retained items at MAX_ITEMS (oldest dropped)
    - wallet_cache rate-limits timestamp-only writes (flash wear)

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_inspection_fixes.py
"""

import json
import sys
import unittest

from payment import Payment
from unique_sorted_list import UniqueSortedList
from lnbits_wallet import LNBitsWallet
from onchain_wallet import OnchainWallet
import wallet_cache

# The MPOS nostr app (com.micropythonos.nostr) registers a boot_completed
# service whose entrypoint is ITS copy of nostr_service.py — when the test
# harness runs main.py, that copy wins the sys.modules["nostr_service"]
# slot and shadows LP's. Purge both modules so the imports below resolve
# LP's copies from the assets dir (which IS on sys.path); apps/… is not,
# so a fresh import can't find the MPOS copy.
for _m in ("nostr_service", "nwc_wallet"):
    if _m in sys.modules:
        del sys.modules[_m]

try:
    from nwc_wallet import NWCWallet
    from nostr_service import NostrManager
    _HAVE_NWC = True
except ImportError:
    # nostr lib not frozen into this build — skip the NWC-specific tests.
    _HAVE_NWC = False


# A syntactically valid NWC URL (parse-only; never used for network I/O).
_FAKE_NWC_URL = ("nostr+walletconnect://" + "a" * 64
                 + "?relay=wss://relay.example.com&secret=" + "b" * 64)


class TestLNBitsCommentParsing(unittest.TestCase):
    """parseLNBitsPayment's extra.comment handling across LNBits versions."""

    def setUp(self):
        self.w = LNBitsWallet("https://demo.example.com", "fakekey")

    def _tx(self, extra=None):
        tx = {"amount": 21000, "memo": "the memo", "time": 1767713767}
        if extra is not None:
            tx["extra"] = extra
        return tx

    def test_no_extra_uses_memo(self):
        p = self.w.parseLNBitsPayment(self._tx())
        self.assertEqual(p.comment, "the memo")

    def test_extra_with_string_comment(self):
        p = self.w.parseLNBitsPayment(self._tx({"comment": "from extra"}))
        self.assertEqual(p.comment, "from extra")

    def test_extra_with_list_comment_takes_first(self):
        # LNBits 0.x returns a list here. The old code did comment.get(0)
        # (lists have no .get) so the comment rendered as "['yes']".
        p = self.w.parseLNBitsPayment(self._tx({"comment": ["yes", "no"]}))
        self.assertEqual(p.comment, "yes")

    def test_extra_with_empty_list_keeps_memo(self):
        p = self.w.parseLNBitsPayment(self._tx({"comment": []}))
        self.assertEqual(p.comment, "the memo")

    def test_extra_without_comment_keeps_memo(self):
        # The old code overwrote the memo with extra.get("comment") → None
        # whenever extra existed at all.
        p = self.w.parseLNBitsPayment(self._tx({"tag": "lnurlp"}))
        self.assertEqual(p.comment, "the memo")

    def test_amount_msat_to_sat(self):
        p = self.w.parseLNBitsPayment(self._tx())
        self.assertEqual(p.amount_sats, 21)


class TestLNBitsOnMessage(unittest.TestCase):
    """Websocket notification parsing — the unbound-new_balance regression."""

    def setUp(self):
        self.w = LNBitsWallet("https://demo.example.com", "fakekey")

    def test_full_notification_processed(self):
        msg = json.dumps({
            "wallet_balance": 5000,
            "payment": {"amount": 1000000, "memo": "zap", "time": 1711226003},
        })
        self.w.on_message(None, msg)
        self.assertEqual(self.w.last_known_balance, 5000)
        self.assertEqual(len(self.w.payment_list), 1)

    def test_missing_balance_does_not_crash(self):
        # Pre-fix: int(None) raised inside the inner try, new_balance was
        # never bound, and `if new_balance:` raised NameError — swallowed
        # by the outer except, silently dropping the notification.
        msg = json.dumps({"payment": {"amount": 1000, "memo": "x", "time": 1}})
        self.w.on_message(None, msg)  # must not raise
        self.assertIsNone(self.w.last_known_balance)
        self.assertEqual(len(self.w.payment_list), 0)


class TestWalletStr(unittest.TestCase):
    """str(wallet) returns the class name (was NameError)."""

    def test_lnbits(self):
        self.assertEqual(str(LNBitsWallet("https://x.example.com", "k")), "LNBitsWallet")

    def test_onchain(self):
        self.assertEqual(str(OnchainWallet("zpub1234example")), "OnchainWallet")

    def test_nwc(self):
        if not _HAVE_NWC:
            return
        self.assertEqual(str(NWCWallet(_FAKE_NWC_URL)), "NWCWallet")


class TestUniqueSortedListRobustness(unittest.TestCase):

    def _payments(self, n, start_epoch=1000):
        return [Payment(start_epoch + i, 100 + i, "p{}".format(i)) for i in range(n)]

    def test_eq_none_is_false_not_typeerror(self):
        usl = UniqueSortedList()
        self.assertFalse(usl == None)  # noqa: E711 — the comparison IS the test
        self.assertTrue(usl != None)   # noqa: E711

    def test_eq_other_list(self):
        a = UniqueSortedList()
        b = UniqueSortedList()
        for p in self._payments(3):
            a.add(p)
            b.add(p)
        self.assertTrue(a == b)

    def test_sorted_descending_after_out_of_order_adds(self):
        usl = UniqueSortedList()
        p1, p2, p3 = self._payments(3)
        usl.add(p2)
        usl.add(p1)
        usl.add(p3)
        epochs = [p.epoch_time for p in usl]
        self.assertEqual(epochs, sorted(epochs, reverse=True))

    def test_duplicates_ignored(self):
        usl = UniqueSortedList()
        p = Payment(1, 1, "x")
        usl.add(p)
        usl.add(Payment(1, 1, "x"))
        self.assertEqual(len(usl), 1)

    def test_cap_trims_oldest(self):
        usl = UniqueSortedList()
        usl.MAX_ITEMS = 5  # instance-level override to keep the test small
        for p in self._payments(8):
            usl.add(p)
        self.assertEqual(len(usl), 5)
        # Newest 5 retained (epochs 1003..1007); the oldest 3 dropped.
        epochs = [p.epoch_time for p in usl]
        self.assertEqual(min(epochs), 1003)
        self.assertEqual(max(epochs), 1007)

    def test_default_cap_is_sane(self):
        # Display max is 21 (Transactions Shown slider); the cap has to sit
        # comfortably above it but stay bounded for ESP32 RAM.
        self.assertTrue(21 < UniqueSortedList.MAX_ITEMS <= 200)


class TestNWCListLimit(unittest.TestCase):
    """PAYMENTS_TO_SHOW property forwards the slider value to NostrManager."""

    def test_setter_forwards_to_manager(self):
        if not _HAVE_NWC:
            return
        w = NWCWallet(_FAKE_NWC_URL)
        w.PAYMENTS_TO_SHOW = 21
        self.assertEqual(w.PAYMENTS_TO_SHOW, 21)
        self.assertEqual(NostrManager.get_instance()._nwc_list_limit, 21)

    def test_manager_clamps_garbage(self):
        if not _HAVE_NWC:
            return
        mgr = NostrManager.get_instance()
        mgr.set_nwc_list_limit(9999)
        self.assertEqual(mgr._nwc_list_limit, 100)
        mgr.set_nwc_list_limit(0)
        self.assertEqual(mgr._nwc_list_limit, 1)
        mgr.set_nwc_list_limit("not a number")  # ignored, keeps previous
        self.assertEqual(mgr._nwc_list_limit, 1)
        mgr.set_nwc_list_limit(6)  # restore default for other tests


class TestNWCOutgoingAmounts(unittest.TestCase):
    """NIP-47 list_transactions: outgoing amounts must render negative."""

    def test_payments_cb_negates_outgoing(self):
        if not _HAVE_NWC:
            return
        w = NWCWallet(_FAKE_NWC_URL)
        captured = {}
        w.handle_new_payments = lambda pl: captured.update(pl=pl)
        w.notify_poll_success = lambda: None
        w._mgr_payments_cb([
            {"amount": 21000, "created_at": 100, "type": "incoming",
             "description": "tip"},
            {"amount": 5000, "created_at": 200, "type": "outgoing",
             "description": "spent"},
        ])
        amounts = sorted(p.amount_sats for p in captured["pl"])
        self.assertEqual(amounts, [-5, 21])


class TestCacheRateLimit(unittest.TestCase):
    """Timestamp-only writes are rate-limited; data writes never are."""

    def test_timestamp_only_skipped_within_interval(self):
        sk = "ratelimit_test_1"
        # Data write — always goes through and arms the limiter.
        wallet_cache.save_slot(sk, creds_fp="fp", balance=123)
        # Plant a sentinel last_updated on disk so we can detect rewrites.
        slots = wallet_cache._load_slots()
        slots[sk]["last_updated"] = 1000
        editor = wallet_cache._cache.edit()
        editor.put_dict("slots", slots)
        editor.commit()
        # Timestamp-only write inside the interval → must be skipped.
        wallet_cache.save_slot(sk)
        self.assertEqual(wallet_cache._load_slots()[sk]["last_updated"], 1000)
        # Expire the limiter → the same call must now go through.
        wallet_cache._last_write_time[sk] = 0
        wallet_cache.save_slot(sk)
        self.assertNotEqual(wallet_cache._load_slots()[sk]["last_updated"], 1000)

    def test_data_writes_never_skipped(self):
        sk = "ratelimit_test_2"
        wallet_cache.save_slot(sk, creds_fp="fp", balance=1)
        wallet_cache.save_slot(sk, creds_fp="fp", balance=2)  # immediate
        self.assertEqual(wallet_cache._load_slots()[sk]["balance"], 2)


if __name__ == "__main__":
    unittest.main()
