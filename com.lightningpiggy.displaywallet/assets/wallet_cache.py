from mpos import SharedPreferences
from payment import Payment
from unique_sorted_list import UniqueSortedList

_cache = SharedPreferences("com.lightningpiggy.displaywallet", filename="cache.json")


def _key(name, slot):
    """Suffix for per-slot cache keys: '' for slot 1 (back-compat), '_2' for slot 2."""
    if slot == 2 or slot == "2":
        return name + "_2"
    return name


def save_cache(balance=None, static_receive_code=None, payments=None, slot=1):
    """Save wallet data to cache for the given slot. Only writes provided fields."""
    editor = _cache.edit()
    if balance is not None:
        editor.put_int(_key("balance", slot), balance)
    if static_receive_code is not None:
        editor.put_string(_key("static_receive_code", slot), static_receive_code)
    if payments is not None:
        editor.put_list(_key("payments", slot), [
            {"epoch_time": p.epoch_time, "amount_sats": p.amount_sats, "comment": p.comment}
            for p in payments
        ])
    editor.commit()
    print("Cache: saved (slot {})".format(slot))


def load_cached_balance(slot=1):
    """Returns cached balance (int) or None for the given slot."""
    key = _key("balance", slot)
    if key in _cache.data:
        return _cache.get_int(key)
    return None


def load_cached_static_receive_code(slot=1):
    """Returns cached static receive code (str) or None for the given slot."""
    return _cache.get_string(_key("static_receive_code", slot))


def load_cached_payments(slot=1):
    """Returns cached payments as UniqueSortedList or None for the given slot."""
    cached = _cache.get_list(_key("payments", slot))
    if cached and len(cached) > 0:
        payment_list = UniqueSortedList()
        for p in cached:
            payment_list.add(Payment(p["epoch_time"], p["amount_sats"], p["comment"]))
        return payment_list
    return None
