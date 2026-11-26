"""
Cost of the NWC payments callback (NWCWallet._mgr_payments_cb).

On an ESP32-S3 the callback took ~3.3 s for a 21-transaction
list_transactions reply, blocking the event loop and the UI on every
poll. Measured on the board (Waveshare 2", MicroPythonOS 0.22.0):

  - `import json` inside Wallet.try_parse_as_zap ran once per
    transaction. `json` is a builtin that a .py file may shadow, so it
    is not kept in sys.modules and every import searches sys.path on
    flash first: ~133 ms per import, ~2.8 s per poll.
  - json.loads was tried (and failed, with two debug prints) on every
    plain-text description, ~14 ms each.
  - _decode_surrogate_pairs walked every character of every comment.
  - UniqueSortedList.add compared each new item with every stored one,
    although wallets send their transactions newest first.

These tests pin the cheap paths and check that the parsed comments and
the list order stay exactly what they were.

Usage (from the LightningPiggyApp repo root):
    Desktop: bash tests/unittest.sh tests/test_payments_callback_cost.py
"""

import builtins
import json
import sys
import unittest

for _m in ("nostr_service", "nwc_wallet", "wallet", "payment", "unique_sorted_list"):
    if _m in sys.modules:
        del sys.modules[_m]

import wallet
import nwc_wallet
from wallet import Wallet
from nwc_wallet import NWCWallet
from payment import Payment
from unique_sorted_list import UniqueSortedList

NWC_URL = (
    "nostr+walletconnect://" + ("ab" * 32)
    + "?relay=wss://relay.example.com&secret=" + ("cd" * 32)
)


class _FakeTask:
    def done(self):
        return False


class _RecordingTaskManager:
    def create_task(self, coro):
        try:
            coro.close()
        except Exception:
            pass
        return _FakeTask()


class _CountingJson:
    """Stands in for the json module and counts loads() calls."""

    def __init__(self):
        self.loads_calls = 0

    def loads(self, s):
        self.loads_calls += 1
        return json.loads(s)


def _coinos_like_transactions(n=21):
    # Shape of a coinos list_transactions reply (descriptions are short
    # plain strings, newest first).
    out = []
    for i in range(n):
        out.append({
            "type": "incoming",
            "amount": 50000 - i * 1000,
            "created_at": 1792782214 - i * 86400,
            "description": "Braiins Pool mining reward",
            "payment_hash": "00" * 32,
        })
    return out


class _ImportCounter:
    def __init__(self, name):
        self.name = name
        self.count = 0

    def __enter__(self):
        self._orig = builtins.__import__
        orig = self._orig

        def counting_import(name, *args):
            if name == self.name:
                self.count += 1
            return orig(name, *args)

        builtins.__import__ = counting_import
        return self

    def __exit__(self, *exc):
        builtins.__import__ = self._orig
        return False


class _WalletTestCase(unittest.TestCase):

    def setUp(self):
        self._orig_tm = wallet.TaskManager
        wallet.TaskManager = _RecordingTaskManager()
        self.w = NWCWallet(NWC_URL)
        self.w.slot_key = None

    def tearDown(self):
        wallet.TaskManager = self._orig_tm


class TestNoImportPerTransaction(_WalletTestCase):

    def test_try_parse_as_zap_does_not_import_json(self):
        with _ImportCounter("json") as counter:
            for _ in range(5):
                self.w.try_parse_as_zap('{"content": "gm", "kind": 9734}')
                self.w.try_parse_as_zap("Braiins Pool mining reward")
        self.assertEqual(counter.count, 0)

    def test_payments_callback_does_not_import_json(self):
        with _ImportCounter("json") as counter:
            self.w._mgr_payments_cb(_coinos_like_transactions())
        self.assertEqual(counter.count, 0)


class TestJsonOnlyWhenItCanMatter(_WalletTestCase):

    def setUp(self):
        super().setUp()
        self._orig_wallet_json = wallet.json if hasattr(wallet, "json") else None
        self._orig_nwc_json = nwc_wallet.json
        self.wallet_json = _CountingJson()
        self.nwc_json = _CountingJson()
        wallet.json = self.wallet_json
        nwc_wallet.json = self.nwc_json

    def tearDown(self):
        if self._orig_wallet_json is None:
            del wallet.json
        else:
            wallet.json = self._orig_wallet_json
        nwc_wallet.json = self._orig_nwc_json
        super().tearDown()

    def test_plain_description_is_not_parsed_as_json(self):
        comment = self.w.getCommentFromTransaction(
            {"description": "Braiins Pool mining reward"})
        self.assertEqual(comment, "Braiins Pool mining reward")
        self.assertEqual(self.nwc_json.loads_calls, 0)
        self.assertEqual(self.wallet_json.loads_calls, 0)

    def test_zap_request_is_parsed_through_module_json(self):
        comment = self.w.try_parse_as_zap('{"content": "gm", "kind": 9734}')
        self.assertEqual(comment, "zapped - gm")
        self.assertEqual(self.wallet_json.loads_calls, 1)

    def test_metadata_list_is_parsed(self):
        desc = '[["text/plain","Thanks!"]]'
        self.assertEqual(
            self.w.getCommentFromTransaction({"description": desc}), "Thanks!")
        self.assertEqual(self.nwc_json.loads_calls, 1)

    def test_twenty_one_plain_transactions_parse_nothing(self):
        self.w._mgr_payments_cb(_coinos_like_transactions())
        self.assertEqual(len(self.w.payment_list), 21)
        self.assertEqual(self.nwc_json.loads_calls, 0)
        self.assertEqual(self.wallet_json.loads_calls, 0)


class TestCommentResultsUnchanged(_WalletTestCase):
    # Inputs whose result used to come out of an exception path or a
    # non-matching JSON type. Expected values are what the code returned
    # before the cheap paths were added.

    CASES = (
        ("Braiins Pool mining reward", "Braiins Pool mining reward"),
        ("", ""),
        ("123", "123"),
        ('"quoted"', '"quoted"'),
        ("true", "true"),
        ("null", "null"),
        ("[broken", "[broken"),
        ("{broken", "{broken"),
        ('["a", "b"]', '["a", "b"]'),
        ('[["text/plain","Thanks!"]]', "Thanks!"),
        ('  [["text/plain","padded"]]', "padded"),
        ('[["text/identifier","x@y"]]', '[["text/identifier","x@y"]]'),
        ('{"content": "gm", "kind": 9734}', "zapped - gm"),
        ('  {"content": "padded zap"}', "zapped - padded zap"),
        ('{"content": ""}', '{"content": ""}'),
        ('{"foo": 1}', '{"foo": 1}'),
        ('[["text/plain","{\\"content\\": \\"inner\\"}"]]', "zapped - inner"),
    )

    def test_descriptions(self):
        for desc, expected in self.CASES:
            self.assertEqual(
                self.w.getCommentFromTransaction({"description": desc}),
                expected, "description %r" % desc)

    def test_non_string_descriptions(self):
        self.assertEqual(self.w.getCommentFromTransaction({"description": None}), None)
        self.assertEqual(self.w.getCommentFromTransaction({}), "")
        self.assertEqual(self.w.getCommentFromTransaction({"description": 42}), 42)

    def test_zap_content_with_escaped_emoji(self):
        desc = '{"content": "gm \\ud83d\\ude42"}'
        self.assertEqual(
            self.w.getCommentFromTransaction({"description": desc}),
            "zapped - gm " + chr(0x1F642))


class TestSurrogateFastPath(unittest.TestCase):

    def _decode(self, text):
        return Wallet._decode_surrogate_pairs(None, text)

    def test_text_without_surrogates_is_returned_as_is(self):
        text = "Braiins Pool mining reward"
        self.assertTrue(self._decode(text) is text)

    def test_non_ascii_without_surrogates_is_returned_as_is(self):
        # Hangul syllables share the 0xED lead byte with surrogates.
        text = "café 한글 " + chr(0x1F642)
        self.assertEqual(self._decode(text), text)

    def test_pair_still_decoded(self):
        text = json.loads('"gm \\ud83d\\ude42!"')
        self.assertEqual(self._decode(text), "gm " + chr(0x1F642) + "!")


class _CountedPayment(Payment):
    comparisons = 0

    def __eq__(self, other):
        _CountedPayment.comparisons += 1
        return Payment.__eq__(self, other)

    def __lt__(self, other):
        _CountedPayment.comparisons += 1
        return Payment.__lt__(self, other)

    def __gt__(self, other):
        _CountedPayment.comparisons += 1
        return Payment.__gt__(self, other)


class TestSortedListAppend(unittest.TestCase):

    def test_newest_first_input_compares_each_item_once(self):
        _CountedPayment.comparisons = 0
        usl = UniqueSortedList()
        for i in range(21):
            usl.add(_CountedPayment(1000 - i, 21, "c"))
        self.assertTrue(_CountedPayment.comparisons <= 21,
                        "comparisons: %d" % _CountedPayment.comparisons)
        self.assertEqual([p.epoch_time for p in usl], [1000 - i for i in range(21)])

    def test_order_and_uniqueness_unchanged(self):
        usl = UniqueSortedList()
        times = [5, 9, 1, 9, 3, 1, 7, 5, 0]
        for t in times:
            usl.add(Payment(t, 1, "c"))
        self.assertEqual([p.epoch_time for p in usl], [9, 7, 5, 3, 1, 0])

    def test_duplicate_of_last_item_not_appended(self):
        usl = UniqueSortedList()
        usl.add(Payment(5, 1, "c"))
        usl.add(Payment(3, 1, "c"))
        usl.add(Payment(3, 1, "c"))
        self.assertEqual(len(usl), 2)

    def test_cap_still_applies(self):
        usl = UniqueSortedList()
        for i in range(UniqueSortedList.MAX_ITEMS + 5):
            usl.add(Payment(10000 - i, 1, "c"))
        self.assertEqual(len(usl), UniqueSortedList.MAX_ITEMS)
        self.assertEqual(usl.get(0).epoch_time, 10000)


if __name__ == "__main__":
    unittest.main()
