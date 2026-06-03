# nwc_wallet.py — NWCWallet thin wrapper around NostrManager.
# The relay connection, event loop, and NWC polling are handled by
# NostrManager (a boot-service singleton in nostr_service.py).
# This class keeps the Wallet base-class interface (callbacks, cache,
# balance/payment tracking) so DisplayWallet can treat it identically
# to LNBitsWallet.

import json

from mpos.util import urldecode

from nostr_service import NostrManager

from wallet import Wallet
from payment import Payment
from unique_sorted_list import UniqueSortedList


class NWCWallet(Wallet):

    PAYMENTS_TO_SHOW = 6

    relays = []
    secret = None
    wallet_pubkey = None

    def __init__(self, nwc_url):
        super().__init__()
        self.nwc_url = nwc_url
        if not nwc_url:
            raise ValueError("NWC URL is not set.")
        self.slot_key = "nwc"
        self.relays, self.wallet_pubkey, self.secret, self.lud16 = self.parse_nwc_url(self.nwc_url)
        if not self.relays:
            raise ValueError("Missing relay in NWC URL.")
        if not self.wallet_pubkey:
            raise ValueError("Missing public key in NWC URL.")
        if not self.secret:
            raise ValueError('Missing "secret" in NWC URL.')

    def start(self, balance_updated_cb, payments_updated_cb,
              static_receive_code_updated_cb=None, error_cb=None):
        self.keep_running = True
        self.balance_updated_cb = balance_updated_cb
        self.payments_updated_cb = payments_updated_cb
        self.static_receive_code_updated_cb = static_receive_code_updated_cb
        self.error_cb = error_cb

        mgr = NostrManager.get_instance()
        if not mgr.is_running():
            mgr.start()

        mgr.set_nwc_callbacks(
            balance_cb=self._mgr_balance_cb,
            payments_cb=self._mgr_payments_cb,
            notification_cb=self._mgr_notification_cb,
        )

        try:
            mgr.configure_nwc(self.nwc_url)
        except Exception as e:
            self.handle_error("Couldn't configure NWC: {}".format(e))
            import sys
            sys.print_exception(e)

    def _mgr_balance_cb(self, new_balance):
        self.handle_new_balance(new_balance)
        self.notify_poll_success()

    def _mgr_payments_cb(self, transactions):
        new_payment_list = UniqueSortedList()
        for transaction in transactions:
            amount = round(transaction["amount"] / 1000)
            comment = self.getCommentFromTransaction(transaction)
            epoch_time = transaction["created_at"]
            payment_obj = Payment(epoch_time, amount, comment)
            new_payment_list.add(payment_obj)
        if len(new_payment_list) > 0:
            self.handle_new_payments(new_payment_list)
        self.notify_poll_success()

    def _mgr_notification_cb(self, notification):
        if "static_receive_code" in notification:
            self.handle_new_static_receive_code(notification["static_receive_code"])
            return
        amount = round(notification["amount"] / 1000)
        ntype = notification["type"]
        if ntype == "outgoing":
            amount = -amount
            self.notify_poll_success()
        elif ntype == "incoming":
            new_balance = self.last_known_balance + amount if self.last_known_balance is not None else amount
            self.handle_new_balance(new_balance, False)
            epoch_time = notification["created_at"]
            comment = self.getCommentFromTransaction(notification)
            payment_obj = Payment(epoch_time, amount, comment)
            self.handle_new_payment(payment_obj)
        else:
            print("NWCWallet: invalid notification type {}, ignoring.".format(ntype))

    def stop(self):
        super().stop()
        mgr = NostrManager.get_instance()
        mgr.set_nwc_callbacks()

    async def fetch_balance(self):
        NostrManager.get_instance().nwc_fetch_balance()

    async def fetch_payments(self):
        NostrManager.get_instance().nwc_fetch_payments()

    def getCommentFromTransaction(self, transaction):
        comment = ""
        try:
            comment = transaction["description"]
            if comment is None:
                return comment
            json_comment = json.loads(comment)
            for field in json_comment:
                if field[0] == "text/plain":
                    comment = field[1]
                    break
            else:
                print("text/plain field is missing from JSON description")
        except Exception as e:
            print("Info: comment {} is not JSON, using as-is ({})".format(comment, e))
        comment = super().try_parse_as_zap(comment)
        return comment

    def parse_nwc_url(self, nwc_url):
        print("DEBUG: Starting to parse NWC URL")
        try:
            if nwc_url.startswith("nostr+walletconnect://"):
                nwc_url = nwc_url[22:]
            elif nwc_url.startswith("nwc:"):
                nwc_url = nwc_url[4:]
            else:
                raise ValueError("Invalid NWC URL: missing 'nostr+walletconnect://' or 'nwc:' prefix")
            nwc_url = urldecode(nwc_url)
            parts = nwc_url.split("?")
            pubkey = parts[0]
            print("DEBUG: Extracted pubkey (content redacted)")
            if len(pubkey) != 64 or not all(c in "0123456789abcdef" for c in pubkey):
                raise ValueError("Invalid NWC URL: pubkey must be 64 hex characters")
            relays = []
            lud16 = None
            secret = None
            if len(parts) > 1:
                print("DEBUG: Query parameters found")
                params = parts[1].split("&")
                for param in params:
                    if param.startswith("relay="):
                        relay = param[6:]
                        print("DEBUG: Extracted relay: {}".format(relay))
                        relays.append(relay)
                    elif param.startswith("secret="):
                        secret = param[7:]
                        print("DEBUG: Extracted secret (content redacted)")
                    elif param.startswith("lud16="):
                        lud16 = param[6:]
                        print("DEBUG: Extracted lud16: {}".format(lud16))
            if not pubkey or not len(relays) > 0 or not secret:
                raise ValueError("Invalid NWC URL: missing required fields (pubkey, relay, or secret)")
            if len(secret) != 64 or not all(c in "0123456789abcdef" for c in secret):
                raise ValueError("Invalid NWC URL: secret must be 64 hex characters")
            print("DEBUG: Parsed NWC data - Relays: {}, lud16: {}".format(relays, lud16))
            return relays, pubkey, secret, lud16
        except Exception as e:
            raise RuntimeError("Exception parsing NWC URL: {}".format(e))
