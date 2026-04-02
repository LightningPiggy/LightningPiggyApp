from mpos import SharedPreferences
from payment import Payment
from unique_sorted_list import UniqueSortedList

_cache = SharedPreferences("com.lightningpiggy.displaywallet", filename="cache.json")


def save_cache(balance=None, static_receive_code=None, payments=None):
    """Save wallet data to cache. Only writes provided fields."""
    editor = _cache.edit()
    if balance is not None:
        editor.put_int("balance", balance)
    if static_receive_code is not None:
        editor.put_string("static_receive_code", static_receive_code)
    if payments is not None:
        editor.put_list("payments", [
            {"epoch_time": p.epoch_time, "amount_sats": p.amount_sats, "comment": p.comment}
            for p in payments
        ])
    editor.commit()
    print("Cache: saved")


def load_cached_balance():
    """Returns cached balance (int) or None."""
    if "balance" in _cache.data:
        return _cache.get_int("balance")
    return None


def load_cached_static_receive_code():
    """Returns cached static receive code (str) or None."""
    return _cache.get_string("static_receive_code")


def load_cached_payments():
    """Returns cached payments as UniqueSortedList or None."""
    cached = _cache.get_list("payments")
    if cached and len(cached) > 0:
        payment_list = UniqueSortedList()
        for p in cached:
            payment_list.add(Payment(p["epoch_time"], p["amount_sats"], p["comment"]))
        return payment_list
    return None
