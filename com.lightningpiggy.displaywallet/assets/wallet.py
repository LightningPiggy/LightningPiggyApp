from mpos import TaskManager

from unique_sorted_list import UniqueSortedList

class Wallet:

    # Public variables
    # These values could be loading from a cache.json file at __init__
    last_known_balance = 0
    payment_list = None
    static_receive_code = None

    # Variables
    keep_running = True
    
    # Callbacks:
    balance_updated_cb = None
    payments_updated_cb = None
    static_receive_code_updated_cb = None
    error_cb = None

    def __init__(self):
        self.payment_list = UniqueSortedList()

    def __str__(self):
        if isinstance(self, LNBitsWallet):
            return "LNBitsWallet"
        elif isinstance(self, NWCWallet):
            return "NWCWallet"

    def handle_new_balance(self, new_balance, fetchPaymentsIfChanged=True):
        if not self.keep_running or new_balance is None:
            return
        sats_added = new_balance - self.last_known_balance
        if new_balance != self.last_known_balance:
            print("Balance changed!")
            self.last_known_balance = new_balance
            print("Calling balance_updated_cb")
            self.balance_updated_cb(sats_added)
            if fetchPaymentsIfChanged: # Fetching *all* payments isn't necessary if balance was changed by a payment notification
                print("Refreshing payments...")
                self.fetch_payments() # if the balance changed, then re-list transactions

    def handle_new_payment(self, new_payment):
        if not self.keep_running:
            return
        print("handle_new_payment")
        self.payment_list.add(new_payment)
        self.payments_updated_cb()

    def handle_new_payments(self, new_payments):
        if not self.keep_running:
            return
        print("handle_new_payments")
        if self.payment_list != new_payments:
            print("new list of payments")
            self.payment_list = new_payments
            self.payments_updated_cb()

    def handle_new_static_receive_code(self, new_static_receive_code):
        print("handle_new_static_receive_code")
        if not self.keep_running or not new_static_receive_code:
            print("not self.keep_running or not new_static_receive_code")
            return
        if self.static_receive_code != new_static_receive_code:
            print("it's really a new static_receive_code")
            self.static_receive_code = new_static_receive_code
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
        self.keep_running = False
        # idea: do a "close connections" call here instead of waiting for polling sub-tasks to notice the change

    def is_running(self):
        return self.keep_running

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
