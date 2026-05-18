"""Per-wallet-type on-disk cache of balance, payments and static-receive-code.

Cache layout (cache.json):
    {
      "version": 2,
      "slots": {
        "<slot_key>": {
          "creds_fp": "<hash>",     # fingerprint guarding balance + payments
          "qr_fp":    "<hash>",     # fingerprint guarding static_receive_code
          "balance":              3113,              # optional
          "payments":              [ {epoch_time, amount_sats, comment}, ... ],
          "static_receive_code":   "lightning:..."
        },
        ...
      }
    }

Fields are guarded independently — changing the LN-address override only
invalidates `static_receive_code` (qr_fp mismatch); changing URL/readkey/
NWC-string invalidates everything (creds_fp mismatch). Load-side: each
field comes back only if its fingerprint matches; otherwise it's None and
the caller shows a spinner / fetches fresh.

v1 caches (no `version` key, flat {balance, payments, static_receive_code})
are silently discarded on first load; the next successful fetch writes v2.
"""
import hashlib
import time

from mpos import SharedPreferences
from payment import Payment
from unique_sorted_list import UniqueSortedList

_CACHE_VERSION = 2

_cache = SharedPreferences("com.lightningpiggy.displaywallet", filename="cache.json")


def _fingerprint(*parts):
    """Short hex digest over the concatenation of the given strings. Used as
    an opaque identifier for cache invalidation — we don't store the raw
    credentials in the cache file so a reader of cache.json can't recover
    the LNBits readkey or NWC secret from it."""
    h = hashlib.sha256()
    for p in parts:
        if p is None:
            p = ""
        h.update(p.encode("utf-8") if isinstance(p, str) else p)
    # 16 hex chars = 64 bits of collision resistance; more than enough for
    # a local single-user cache guard.
    return h.digest()[:8].hex()


def compute_fingerprints(wallet_type, prefs):
    """Return (creds_fp, qr_fp) for the currently-configured wallet of
    `wallet_type`, derived from `prefs` (a SharedPreferences instance).
    Returns (None, None) for unknown wallet types."""
    if wallet_type == "lnbits":
        url = prefs.get_string("lnbits_url") or ""
        readkey = prefs.get_string("lnbits_readkey") or ""
        override = prefs.get_string("lnbits_static_receive_code") or ""
        creds_fp = _fingerprint("lnbits", url, readkey)
        qr_fp = _fingerprint("lnbits", url, readkey, override)
        return creds_fp, qr_fp
    if wallet_type == "nwc":
        nwc_url = prefs.get_string("nwc_url") or ""
        override = prefs.get_string("nwc_static_receive_code") or ""
        creds_fp = _fingerprint("nwc", nwc_url)
        qr_fp = _fingerprint("nwc", nwc_url, override)
        return creds_fp, qr_fp
    if wallet_type == "onchain":
        xpub = prefs.get_string("onchain_xpub") or ""
        blockbook_url = prefs.get_string("onchain_blockbook_url") or ""
        override = prefs.get_string("onchain_static_receive_code") or ""
        # Both xpub and the indexer URL participate: pointing the same
        # xpub at a different Blockbook is a valid config change and must
        # invalidate cached balance + payments.
        creds_fp = _fingerprint("onchain", xpub, blockbook_url)
        qr_fp = _fingerprint("onchain", xpub, blockbook_url, override)
        return creds_fp, qr_fp
    return None, None


def _load_slots():
    """Return the slots dict from disk, discarding v1 caches silently."""
    if _cache.get_int("version", 0) != _CACHE_VERSION:
        return {}
    return _cache.get_dict("slots") or {}


def save_slot(slot_key, creds_fp=None, qr_fp=None,
              balance=None, payments=None, static_receive_code=None):
    """Write one or more fields into the slot for `slot_key`.

    Only the fields you pass are updated. Fingerprints are stamped on the
    slot so a later `load_slot` can decide which fields are still valid
    after a config change. Pass the fingerprint corresponding to the
    field you're updating (creds_fp when writing balance/payments, qr_fp
    when writing static_receive_code).

    Every write bumps `last_updated` so the stale-data indicator can
    compute time-since-last-success across app restarts.
    """
    slots = _load_slots()
    slot = slots.get(slot_key, {})
    if balance is not None:
        slot["balance"] = int(balance)
        if creds_fp is not None:
            slot["creds_fp"] = creds_fp
    if payments is not None:
        slot["payments"] = [
            {"epoch_time": p.epoch_time, "amount_sats": p.amount_sats, "comment": p.comment}
            for p in payments
        ]
        if creds_fp is not None:
            slot["creds_fp"] = creds_fp
    if static_receive_code is not None:
        slot["static_receive_code"] = static_receive_code
        if qr_fp is not None:
            slot["qr_fp"] = qr_fp
    slot["last_updated"] = int(time.time())
    slots[slot_key] = slot
    editor = _cache.edit()
    editor.put_int("version", _CACHE_VERSION)
    editor.put_dict("slots", slots)
    editor.commit()
    print("Cache: saved slot '{}'".format(slot_key))


def load_slot(slot_key, expected_creds_fp, expected_qr_fp):
    """Return a dict of cached fields for `slot_key`, with any field whose
    fingerprint doesn't match the expected value returned as None.

    Shape:
        {"balance": int|None,
         "payments": UniqueSortedList|None,
         "static_receive_code": str|None,
         "last_updated": int|None}  # unix timestamp of the most recent
                                     # successful write to this slot
    """
    slots = _load_slots()
    slot = slots.get(slot_key)
    result = {"balance": None, "payments": None, "static_receive_code": None,
              "last_updated": None}
    if not slot:
        return result
    creds_ok = (slot.get("creds_fp") == expected_creds_fp
                and expected_creds_fp is not None)
    qr_ok = (slot.get("qr_fp") == expected_qr_fp
             and expected_qr_fp is not None)
    if creds_ok:
        if "balance" in slot:
            try:
                result["balance"] = int(slot["balance"])
            except (TypeError, ValueError):
                pass
        raw_payments = slot.get("payments")
        if raw_payments:
            payment_list = UniqueSortedList()
            for p in raw_payments:
                try:
                    payment_list.add(Payment(p["epoch_time"], p["amount_sats"], p["comment"]))
                except Exception:
                    pass
            if len(payment_list) > 0:
                result["payments"] = payment_list
    if qr_ok:
        src = slot.get("static_receive_code")
        if src:
            result["static_receive_code"] = src
    # last_updated is only meaningful if the slot is still valid (at least
    # the credentials fingerprint matches); an invalidated slot's timestamp
    # would be misleading.
    if creds_ok or qr_ok:
        try:
            lu = slot.get("last_updated")
            if lu is not None:
                result["last_updated"] = int(lu)
        except (TypeError, ValueError):
            pass
    return result
