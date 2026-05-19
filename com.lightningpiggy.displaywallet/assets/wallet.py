from mpos import TaskManager

from unique_sorted_list import UniqueSortedList
import wallet_cache

class Wallet:

    # Public variables
    last_known_balance = None
    payment_list = None
    static_receive_code = None

    # Variables
    keep_running = True
    # Whether the wallet's async resources (sockets, etc.) have finished
    # releasing. True by default because the base class holds no resources;
    # subclasses with network state (e.g. NWCWallet) set this False while a
    # teardown task is in flight and back to True when it completes.
    _cleanup_done = True

    # Cache identity — subclasses set these in their __init__ so handle_new_*
    # can tag writes to wallet_cache with the right slot + fingerprints.
    # `slot_key` is the cache slot this wallet writes to ("lnbits", "nwc").
    # `creds_fingerprint` guards balance + payments (URL/readkey/NWC-string).
    # `qr_fingerprint` guards static_receive_code (adds the LN-address override).
    slot_key = None
    creds_fingerprint = None
    qr_fingerprint = None

    # Callbacks:
    balance_updated_cb = None
    payments_updated_cb = None
    static_receive_code_updated_cb = None
    error_cb = None
    # Fires on every successful fetch, regardless of whether the data
    # changed. Required for the stale-data indicator — balance/payments
    # callbacks only fire on *change*, so an otherwise-healthy wallet
    # whose balance never moves would look indistinguishable from an
    # offline one. DisplayWallet wires this to _note_successful_update
    # after start() (see went_online).
    poll_success_cb = None

    def __init__(self):
        self.last_known_balance = None
        self.payment_list = UniqueSortedList()

    def __str__(self):
        if isinstance(self, LNBitsWallet):
            return "LNBitsWallet"
        elif isinstance(self, NWCWallet):
            return "NWCWallet"
        elif isinstance(self, OnchainWallet):
            return "OnchainWallet"

    def notify_poll_success(self):
        """Subclasses call this after any successful fetch (balance OR
        payments) so the UI can distinguish a healthy-but-quiet wallet
        from one that's failing. Also bumps the cache's last_updated
        without writing any data field."""
        if not self.keep_running:
            return
        # Refresh last_updated in the cache so offline-resume shows
        # correct age, without rewriting balance/payments/QR.
        self._save_cache()
        if self.poll_success_cb:
            self.poll_success_cb()

    def _save_cache(self, **kwargs):
        """Route handle_new_* writes through the slot API. No-op if the
        subclass didn't set slot_key (base Wallet is never instantiated
        directly, but the guard keeps unit tests of bare mocks safe)."""
        if not self.slot_key:
            return
        wallet_cache.save_slot(
            self.slot_key,
            creds_fp=self.creds_fingerprint,
            qr_fp=self.qr_fingerprint,
            **kwargs,
        )

    def handle_new_balance(self, new_balance, fetchPaymentsIfChanged=True):
        if not self.keep_running or new_balance is None:
            return

        # First balance we ever got: update UI even if it's 0
        if self.last_known_balance is None:
            self.last_known_balance = new_balance
            print("First balance received")
            self._save_cache(balance=new_balance)
            if self.balance_updated_cb:
                self.balance_updated_cb(0)
            # optional: fetch payments once on initial connect
            if fetchPaymentsIfChanged:
                TaskManager.create_task(self.fetch_payments())
            return

        sats_added = new_balance - self.last_known_balance
        if new_balance != self.last_known_balance:
            print("Balance changed!")
            self.last_known_balance = new_balance
            self._save_cache(balance=new_balance)
            print("Calling balance_updated_cb")
            if self.balance_updated_cb:
                self.balance_updated_cb(sats_added)
            if fetchPaymentsIfChanged:
                print("Refreshing payments...")
                TaskManager.create_task(self.fetch_payments())


    def handle_new_payment(self, new_payment):
        if not self.keep_running:
            return
        print("handle_new_payment")
        self.payment_list.add(new_payment)
        self._save_cache(payments=self.payment_list)
        if self.payments_updated_cb:
            self.payments_updated_cb()

    def handle_new_payments(self, new_payments):
        if not self.keep_running:
            return
        print("handle_new_payments")
        if self.payment_list != new_payments:
            print("new list of payments")
            self.payment_list = new_payments
            self._save_cache(payments=self.payment_list)
            if self.payments_updated_cb:
                self.payments_updated_cb()

    def handle_new_static_receive_code(self, new_static_receive_code):
        print("handle_new_static_receive_code")
        if not self.keep_running or not new_static_receive_code:
            print("not self.keep_running or not new_static_receive_code")
            return
        if self.static_receive_code != new_static_receive_code:
            print("it's really a new static_receive_code")
            self.static_receive_code = new_static_receive_code
            self._save_cache(static_receive_code=new_static_receive_code)
            if self.static_receive_code_updated_cb:
                self.static_receive_code_updated_cb()
        else:
            print(f"self.static_receive_code {self.static_receive_code } == new_static_receive_code {new_static_receive_code}")

    def handle_error(self, e):
        if self.error_cb:
            self.error_cb(e)

    # Maybe also add callbacks for:
    #    - started (so the user can show the UI) 
    #    - stopped (so the user can delete/free it)
    #    - error (so the user can show the error)
    def start(self, balance_updated_cb, payments_updated_cb, static_receive_code_updated_cb = None, error_cb = None):
        self.keep_running = True
        self.balance_updated_cb = balance_updated_cb
        self.payments_updated_cb = payments_updated_cb
        self.static_receive_code_updated_cb = static_receive_code_updated_cb
        self.error_cb = error_cb
        TaskManager.create_task(self.async_wallet_manager_task())

    def stop(self):
        """Signal the wallet to stop. Subclasses with async resources should
        override to schedule their teardown (see NWCWallet.stop)."""
        self.keep_running = False

    def is_running(self):
        return self.keep_running

    def is_stopped(self):
        """True once stop() has been called AND any async teardown has
        completed (sockets released, etc.). Callers about to start a
        replacement wallet should poll this before doing so — on ESP32 the
        TCP socket pool is small and opening new relays before the old ones
        fully close can fail with socket exhaustion."""
        return (not self.keep_running) and self._cleanup_done

    # Decode something like:
    # {"id": "d410....6e9", "content": "zap zap emoji", "pubkey":"e9f...f50", "created_at": 1767713767, "kind": 9734, "tags":[["p","06ff...4f42"], ["amount", "21000"], ["e", "c1c9...0e92"], ["relays", "wss://relay.nostr.band"]], "sig": "48a...4fd"}
    def try_parse_as_zap(self, comment):
        try:
            import json
            json_comment = json.loads(comment)
            content = json_comment.get("content")
            if content:
                return "zapped - " + content
        except Exception as e:
            print(f"Info: try_parse_as_zap of comment '{comment}' got exception while trying to decode as JSON. This is probably fine, using as-is ({e})")
        return comment
