import json
import os

from payment import Payment
from unique_sorted_list import UniqueSortedList

CACHE_FILE = "M:cache/wallet_cache.json"
CACHE_DIR = "M:cache"


def _ensure_cache_dir():
    try:
        os.makedirs(CACHE_DIR)
    except OSError:
        pass  # already exists


def load_cache():
    """Load cached wallet data from flash. Returns dict or None."""
    try:
        with open(CACHE_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Cache: could not load ({e})")
        return None


def save_cache(balance=None, static_receive_code=None, payments=None):
    """Save wallet data to flash cache. Only writes provided fields."""
    _ensure_cache_dir()
    # Load existing cache to merge
    existing = load_cache() or {}
    if balance is not None:
        existing["balance"] = balance
    if static_receive_code is not None:
        existing["static_receive_code"] = static_receive_code
    if payments is not None:
        existing["payments"] = [
            {"epoch_time": p.epoch_time, "amount_sats": p.amount_sats, "comment": p.comment}
            for p in payments
        ]
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(existing, f)
        print("Cache: saved")
    except Exception as e:
        print(f"Cache: could not save ({e})")


def load_cached_balance():
    """Returns cached balance (int) or None."""
    data = load_cache()
    if data and "balance" in data:
        return data["balance"]
    return None


def load_cached_static_receive_code():
    """Returns cached static receive code (str) or None."""
    data = load_cache()
    if data and "static_receive_code" in data:
        return data["static_receive_code"]
    return None


def load_cached_payments():
    """Returns cached payments as UniqueSortedList or None."""
    data = load_cache()
    if data and "payments" in data:
        payment_list = UniqueSortedList()
        for p in data["payments"]:
            payment_list.add(Payment(p["epoch_time"], p["amount_sats"], p["comment"]))
        return payment_list
    return None
