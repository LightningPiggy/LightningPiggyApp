import asyncio
import _thread
import requests
import json
import ssl
import time

from nostr.relay_manager import RelayManager
from nostr.message_type import ClientMessageType
from nostr.filter import Filter, Filters
from nostr.event import EncryptedDirectMessage
from nostr.key import PrivateKey

from websocket import WebSocketApp

import mpos.apps
import mpos.time
import mpos.util

# keeps a list of items
# The .add() method ensures the list remains unique (via __eq__)
# and sorted (via __lt__) by inserting new items in the correct position.
class UniqueSortedList:
    def __init__(self):
        self._items = []

    def add(self, item):
        #print(f"before add: {str(self)}")
        # Check if item already exists (using __eq__)
        if item not in self._items:
            # Insert item in sorted position for descending order (using __gt__)
            for i, existing_item in enumerate(self._items):
                if item > existing_item:
                    self._items.insert(i, item)
                    return
            # If item is smaller than all existing items, append it
            self._items.append(item)
        #print(f"after add: {str(self)}")

    def __iter__(self):
        # Return iterator for the internal list
        return iter(self._items)

    def get(self, index_nr):
        # Retrieve item at given index, raise IndexError if invalid
        try:
            return self._items[index_nr]
        except IndexError:
            raise IndexError("Index out of range")

    def __len__(self):
        # Return the number of items for len() calls
        return len(self._items)

    def __str__(self):
        #print("UniqueSortedList tostring called")
        return "\n".join(str(item) for item in self._items)

    def __eq__(self, other):
        if len(self._items) != len(other):
            return False
        return all(p1 == p2 for p1, p2 in zip(self._items, other))

# Payment class remains unchanged
class Payment:
    def __init__(self, epoch_time, amount_sats, comment):
        self.epoch_time = epoch_time
        self.amount_sats = amount_sats
        self.comment = comment

    def __str__(self):
        sattext = "sats"
        if self.amount_sats == 1:
            sattext = "sat"
        #return f"{self.amount_sats} {sattext} @ {self.epoch_time}: {self.comment}"
        return f"{self.amount_sats} {sattext}: {self.comment}"

    def __eq__(self, other):
        if not isinstance(other, Payment):
            return False
        return self.epoch_time == other.epoch_time and self.amount_sats == other.amount_sats and self.comment == other.comment

    def __lt__(self, other):
        if not isinstance(other, Payment):
            return NotImplemented
        return (self.epoch_time, self.amount_sats, self.comment) < (other.epoch_time, other.amount_sats, other.comment)

    def __le__(self, other):
        if not isinstance(other, Payment):
            return NotImplemented
        return (self.epoch_time, self.amount_sats, self.comment) <= (other.epoch_time, other.amount_sats, other.comment)

    def __gt__(self, other):
        if not isinstance(other, Payment):
            return NotImplemented
        return (self.epoch_time, self.amount_sats, self.comment) > (other.epoch_time, other.amount_sats, other.comment)

    def __ge__(self, other):
        if not isinstance(other, Payment):
            return NotImplemented
        return (self.epoch_time, self.amount_sats, self.comment) >= (other.epoch_time, other.amount_sats, other.comment)

class Wallet:

    # Public variables
    # These values could be loading from a cache.json file at __init__
    last_known_balance = -1
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
        _thread.stack_size(mpos.apps.good_stack_size())
        _thread.start_new_thread(self.wallet_manager_thread, ())

    # Currently, there's no mechanism for this thread to signal fatal errors, like typos in the URLs.
    def wallet_manager_thread(self):
        try:
            asyncio.run(self.async_wallet_manager_task())
        except Exception as e:
            print(f"[FATAL] Wallet manager crashed: {e}")
            import sys
            sys.print_exception(e)  # Full traceback on MicroPython
            self.handle_error(e)

    def stop(self):
        self.keep_running = False
        # idea: do a "close connections" call here instead of waiting for polling sub-tasks to notice the change

    def is_running(self):
        return self.keep_running






class LNBitsWallet(Wallet):

    PAYMENTS_TO_SHOW = 6
    PERIODIC_FETCH_BALANCE_SECONDS = 60 # seconds

    ws = None

    def __init__(self, lnbits_url, lnbits_readkey):
        super().__init__()
        if not lnbits_url:
            raise ValueError('LNBits URL is not set.')
        elif not lnbits_readkey:
            raise ValueError('LNBits Read Key is not set.')
        self.lnbits_url = lnbits_url.rstrip('/')
        self.lnbits_readkey = lnbits_readkey


    def parseLNBitsPayment(self, transaction):
        amount = transaction["amount"]
        amount = round(amount / 1000)
        comment = transaction["memo"]
        epoch_time = transaction["time"]
        try:
            extra = transaction.get("extra")
            if extra:
                comment = extra.get("comment")
                first_from_list = comment.get(0) # some LNBits 0.x versions return a list instead of a string here...
                comment = first_from_list
        except Exception as e:
            pass
        return Payment(epoch_time, amount, comment)

    # Example data: {"wallet_balance": 4936, "payment": {"checking_id": "037c14...56b3", "pending": false, "amount": 1000000, "fee": 0, "memo": "zap2oink", "time": 1711226003, "bolt11": "lnbc10u1pjl70y....qq9renr", "preimage": "0000...000", "payment_hash": "037c1438b20ef4729b1d3dc252c2809dc2a2a2e641c7fb99fe4324e182f356b3", "expiry": 1711226603.0, "extra": {"tag": "lnurlp", "link": "TkjgaB", "extra": "1000000", "comment": ["yes"], "lnaddress": "oink@demo.lnpiggy.com"}, "wallet_id": "c9168...8de4", "webhook": null, "webhook_status": null}}
    def on_message(self, class_obj, message: str):
        print(f"wallet.py _on_message received: {message}")
        try:
            payment_notification = json.loads(message)
            try:
                new_balance = int(payment_notification.get("wallet_balance"))
            except Exception as e:
                print("wallet.py on_message got exception while parsing balance: {e}")
            if new_balance:
                self.handle_new_balance(new_balance, False) # refresh balance on display BUT don't trigger a full fetch_payments
                transaction = payment_notification.get("payment")
                print(f"Got transaction: {transaction}")
                paymentObj = self.parseLNBitsPayment(transaction)
                self.handle_new_payment(paymentObj)
        except Exception as e:
            print(f"websocket on_message got exception: {e}")

    async def async_wallet_manager_task(self):
        websocket_running = False
        while self.keep_running:
            try:
                new_balance = self.fetch_balance()
            except Exception as e:
                print(f"WARNING: wallet_manager_thread got exception: {e}")
                self.handle_error(e)
            if not self.static_receive_code:
                static_receive_code = self.fetch_static_receive_code()
                if static_receive_code:
                    self.handle_new_static_receive_code(static_receive_code)
            if not websocket_running and self.keep_running: # after the other things, listen for incoming payments
                websocket_running = True
                print("Opening websocket for payment notifications...")
                wsurl = self.lnbits_url + "/api/v1/ws/" + self.lnbits_readkey
                wsurl = wsurl.replace("https://", "wss://")
                wsurl = wsurl.replace("http://", "ws://")
                try:
                    self.ws = WebSocketApp(
                        wsurl,
                        on_message=self.on_message,
                    ) # maybe add other callbacks to reconnect when disconnected etc.
                    asyncio.create_task(self.ws.run_forever(),)
                except Exception as e:
                    print(f"Got exception while creating task for LNBitsWallet websocket: {e}")
            print("Sleeping a while before re-fetching balance...")
            for _ in range(self.PERIODIC_FETCH_BALANCE_SECONDS*10):
                await asyncio.sleep(0.1)
                if not self.keep_running:
                    break
        print("LNBitsWallet main() stopping...")
        if self.ws:
            print("LNBitsWallet main() closing websocket connection...")
            await self.ws.close()

    def fetch_balance(self):
        walleturl = self.lnbits_url + "/api/v1/wallet"
        headers = {
            "X-Api-Key": self.lnbits_readkey,
        }
        try:
            print(f"Fetching balance with GET to {walleturl}")
            response = requests.get(walleturl, timeout=10, headers=headers)
        except Exception as e:
            raise RuntimeError(f"fetch_balance: GET request to {walleturl} with header 'X-Api-Key: {self.lnbits_readkey} failed: {e}")
        if response and self.keep_running:
            response_text = response.text
            print(f"Got response text: {response_text}")
            response.close()
            try:
                balance_reply = json.loads(response_text)
            except Exception as e:
                raise RuntimeError(f"Could not parse reponse '{response_text}' as JSON: {e}")
            try:
                balance_msat = int(balance_reply.get("balance"))
            except Exception as e:
                raise RuntimeError(f"Could not parse balance: {e}")
            if balance_msat is not None:
                print(f"balance_msat: {balance_msat}")
                new_balance = round(balance_msat / 1000)
                self.handle_new_balance(new_balance)
            else:
                error = balance_reply.get("detail")
                if error:
                    raise RuntimeError(f"LNBits backend replied: {error}")

    def fetch_payments(self):
        paymentsurl = self.lnbits_url + "/api/v1/payments?limit=" + str(self.PAYMENTS_TO_SHOW)
        headers = {
            "X-Api-Key": self.lnbits_readkey,
        }
        try:
            print(f"Fetching payments with GET to {paymentsurl}")
            response = requests.get(paymentsurl, timeout=10, headers=headers)
        except Exception as e:
            raise RuntimeError(f"fetch_payments: GET request to {paymentsurl} with header 'X-Api-Key: {self.lnbits_readkey} failed: {e}")
        if response and response.status_code == 200 and self.keep_running:
            response_text = response.text
            #print(f"Got response text: {response_text}")
            response.close()
            try:
                payments_reply = json.loads(response_text)
            except Exception as e:
                raise RuntimeError(f"Could not parse reponse '{response_text}' as JSON: {e}")
            print(f"Got payments: {payments_reply}")
            if len(payments_reply) == 0:
                self.handle_new_payment(Payment(1751987292, 0, "Time to Start Stacking!"))
            else:
                new_payment_list = UniqueSortedList()
                for transaction in payments_reply:
                    print(f"Got transaction: {transaction}")
                    paymentObj = self.parseLNBitsPayment(transaction)
                    new_payment_list.add(paymentObj)
                self.handle_new_payments(new_payment_list)

    def fetch_static_receive_code(self):
        url = self.lnbits_url + "/lnurlp/api/v1/links?all_wallets=false"
        headers = {
            "X-Api-Key": self.lnbits_readkey,
        }
        try:
            print(f"Fetching static_receive_code with GET to {url}")
            response = requests.get(url, timeout=10, headers=headers)
        except Exception as e:
            raise RuntimeError(f"fetch_static_receive_code: GET request to {url} with header 'X-Api-Key: {self.lnbits_readkey} failed: {e}")
        if response and response.status_code == 200 and self.keep_running:
            response_text = response.text
            print(f"Got response text: {response_text}")
            response.close()
            try:
                reply_object = json.loads(response_text)
            except Exception as e:
                raise RuntimeError(f"Could not parse reponse '{response_text}' as JSON: {e}")
            print(f"Got links: {reply_object}")
            for link in reply_object:
                print(f"Got link: {link}")
                return link.get("lnurl")
        else:
            print(f"Fetching static receive code got no response or response.status_code {response.status_code} != 200 or not self.keep_running")
            self.handle_error("No static receive code found on server")








class NWCWallet(Wallet):

    PAYMENTS_TO_SHOW = 4 # slowness appeared again, so reducing this...
    PERIODIC_FETCH_BALANCE_SECONDS = 60 # seconds
    
    relays = []
    secret = None
    wallet_pubkey = None

    def __init__(self, nwc_url):
        super().__init__()
        self.nwc_url = nwc_url
        if not nwc_url:
            raise ValueError('NWC URL is not set.')
        self.connected = False
        self.relays, self.wallet_pubkey, self.secret, self.lud16 = self.parse_nwc_url(self.nwc_url)
        if not self.relays:
            raise ValueError('Missing relay in NWC URL.')
        if not self.wallet_pubkey:
            raise ValueError('Missing public key in NWC URL.')
        if not self.secret:
            raise ValueError('Missing "secret" in NWC URL.')
        #if not self.lud16:
        #    raise ValueError('Missing lud16 (= lightning address) in NWC URL.')

    def getCommentFromTransaction(self, transaction):
        comment = ""
        try:
            comment = transaction["description"]
            json_comment = json.loads(comment)
            for field in json_comment:
                if field[0] == "text/plain":
                    comment = field[1]
                    break
            else:
                print("text/plain field is missing from JSON description")
        except Exception as e:
            print(f"Info: could not parse comment as JSON, this is fine, using as-is ({e})")
        return comment

    async def async_wallet_manager_task(self):
        if self.lud16:
            self.handle_new_static_receive_code(self.lud16)

        self.private_key = PrivateKey(bytes.fromhex(self.secret))
        self.relay_manager = RelayManager()
        for relay in self.relays:
            self.relay_manager.add_relay(relay)

        print(f"DEBUG: Opening relay connections")
        await self.relay_manager.open_connections({"cert_reqs": ssl.CERT_NONE})
        self.connected = False
        nrconnected = 0
        for _ in range(100):
            #print("Waiting for relay connections...")
            await asyncio.sleep(0.1)
            nrconnected = self.relay_manager.connected_relays()
            #print(f"nrconnected: {nrconnected}")
            if nrconnected == len(self.relays) or not self.keep_running:
                break
        if nrconnected == 0:
            self.handle_error("Could not connect to any Nostr Wallet Connect relays.")
            return
        if not self.keep_running:
            print(f"async_wallet_manager_task does not have self.keep_running, returning...")
            return

        print(f"{nrconnected} relays connected")

        # Set up subscription to receive response
        self.subscription_id = "micropython_nwc_" + str(round(time.time()))
        print(f"DEBUG: Setting up subscription with ID: {self.subscription_id}")
        self.filters = Filters([Filter(
            #event_ids=[self.subscription_id], would be nice to filter, but not like this
            kinds=[23195, 23196],  # NWC reponses and notifications
            authors=[self.wallet_pubkey],
            pubkey_refs=[self.private_key.public_key.hex()]
        )])
        print(f"DEBUG: Subscription filters: {self.filters.to_json_array()}")
        self.relay_manager.add_subscription(self.subscription_id, self.filters)
        print(f"DEBUG: Creating subscription request")
        request_message = [ClientMessageType.REQUEST, self.subscription_id]
        request_message.extend(self.filters.to_json_array())
        print(f"DEBUG: Publishing subscription request")
        self.relay_manager.publish_message(json.dumps(request_message))
        print(f"DEBUG: Published subscription request")

        last_fetch_balance = time.time() - self.PERIODIC_FETCH_BALANCE_SECONDS
        while True: # handle incoming events and do periodic fetch_balance
            #print(f"checking for incoming events...")
            await asyncio.sleep(0.1)
            if not self.keep_running:
                print("NWCWallet: not keep_running, closing connections...")
                await self.relay_manager.close_connections()
                break

            if time.time() - last_fetch_balance >= self.PERIODIC_FETCH_BALANCE_SECONDS:
                last_fetch_balance = time.time()
                try:
                    await self.fetch_balance()
                except Exception as e:
                    print(f"fetch_balance got exception {e}") # fetch_balance got exception 'NoneType' object isn't iterable?!

            start_time = time.ticks_ms()
            if self.relay_manager.message_pool.has_events():
                print(f"DEBUG: Event received from message pool after {time.ticks_ms()-start_time}ms")
                event_msg = self.relay_manager.message_pool.get_event()
                event_created_at = event_msg.event.created_at
                print(f"Received at {time.localtime()} a message with timestamp {event_created_at} after {time.ticks_ms()-start_time}ms")
                try:
                    # This takes a very long time, even for short messages:
                    decrypted_content = self.private_key.decrypt_message(
                        event_msg.event.content,
                        event_msg.event.public_key,
                    )
                    print(f"DEBUG: Decrypted content: {decrypted_content} after {time.ticks_ms()-start_time}ms")
                    response = json.loads(decrypted_content)
                    print(f"DEBUG: Parsed response: {response}")
                    result = response.get("result")
                    if result:
                        if result.get("balance") is not None:
                            new_balance = round(int(result["balance"]) / 1000)
                            print(f"Got balance: {new_balance}")
                            self.handle_new_balance(new_balance)
                        elif result.get("transactions") is not None:
                            print("Response contains transactions!")
                            new_payment_list = UniqueSortedList()
                            for transaction in result["transactions"]:
                                amount = transaction["amount"]
                                amount = round(amount / 1000)
                                comment = self.getCommentFromTransaction(transaction)
                                epoch_time = transaction["created_at"]
                                paymentObj = Payment(epoch_time, amount, comment)
                                new_payment_list.add(paymentObj)
                            if len(new_payment_list) > 0:
                                # do them all in one shot instead of one-by-one because the lv_async() isn't always chronological,
                                # so when a long list of payments is added, it may be overwritten by a short list
                                self.handle_new_payments(new_payment_list)
                    else:
                        notification = response.get("notification")
                        if notification:
                            amount = notification["amount"]
                            amount = round(amount / 1000)
                            type = notification["type"]
                            if type == "outgoing":
                                amount = -amount
                            elif type == "incoming":
                                new_balance = self.last_known_balance + amount
                                self.handle_new_balance(new_balance, False) # don't trigger full fetch because payment info is in notification
                                epoch_time = notification["created_at"]
                                comment = self.getCommentFromTransaction(notification)
                                paymentObj = Payment(epoch_time, amount, comment)
                                self.handle_new_payment(paymentObj)
                            else:
                                print(f"WARNING: invalid notification type {type}, ignoring.")
                        else:
                            print("Unsupported response, ignoring.")
                except Exception as e:
                    print(f"DEBUG: Error processing response: {e}")
                    import sys
                    sys.print_exception(e)  # Full traceback on MicroPython
            else:
                #print(f"pool has no events after {time.ticks_ms()-start_time}ms") # completes in 0-1ms
                pass

    def fetch_balance(self):
        try:
            if not self.keep_running:
                return
            # Create get_balance request
            balance_request = {
                "method": "get_balance",
                "params": {}
            }
            print(f"DEBUG: Created balance request: {balance_request}")
            print(f"DEBUG: Creating encrypted DM to wallet pubkey: {self.wallet_pubkey}")
            dm = EncryptedDirectMessage(
                recipient_pubkey=self.wallet_pubkey,
                cleartext_content=json.dumps(balance_request),
                kind=23194
            )
            print(f"DEBUG: Signing DM {json.dumps(dm)} with private key")
            self.private_key.sign_event(dm) # sign also does encryption if it's a encrypted dm
            print(f"DEBUG: Publishing encrypted DM")
            self.relay_manager.publish_event(dm)
        except Exception as e:
            print(f"inside fetch_balance exception: {e}")

    def fetch_payments(self):
        if not self.keep_running:
            return
        # Create get_balance request
        list_transactions = {
            "method": "list_transactions",
            "params": {
                "limit": self.PAYMENTS_TO_SHOW
            }
        }
        dm = EncryptedDirectMessage(
            recipient_pubkey=self.wallet_pubkey,
            cleartext_content=json.dumps(list_transactions),
            kind=23194
        )
        self.private_key.sign_event(dm) # sign also does encryption if it's a encrypted dm
        print("\nPublishing DM to fetch payments...")
        self.relay_manager.publish_event(dm)

    def parse_nwc_url(self, nwc_url):
        """Parse Nostr Wallet Connect URL to extract pubkey, relays, secret, and lud16."""
        print(f"DEBUG: Starting to parse NWC URL: {nwc_url}")
        try:
            # Remove 'nostr+walletconnect://' or 'nwc:' prefix
            if nwc_url.startswith('nostr+walletconnect://'):
                print(f"DEBUG: Removing 'nostr+walletconnect://' prefix")
                nwc_url = nwc_url[22:]
            elif nwc_url.startswith('nwc:'):
                print(f"DEBUG: Removing 'nwc:' prefix")
                nwc_url = nwc_url[4:]
            else:
                print(f"DEBUG: No recognized prefix found in URL")
                raise ValueError("Invalid NWC URL: missing 'nostr+walletconnect://' or 'nwc:' prefix")
            print(f"DEBUG: URL after prefix removal: {nwc_url}")
            # urldecode because the relay might have %3A%2F%2F etc
            nwc_url = mpos.util.urldecode(nwc_url)
            print(f"after urldecode: {nwc_url}")
            # Split into pubkey and query params
            parts = nwc_url.split('?')
            pubkey = parts[0]
            print(f"DEBUG: Extracted pubkey: {pubkey}")
            # Validate pubkey (should be 64 hex characters)
            if len(pubkey) != 64 or not all(c in '0123456789abcdef' for c in pubkey):
                raise ValueError("Invalid NWC URL: pubkey must be 64 hex characters")
            # Extract relay, secret, and lud16 from query params
            relays = []
            lud16 = None
            secret = None
            if len(parts) > 1:
                print(f"DEBUG: Query parameters found: {parts[1]}")
                params = parts[1].split('&')
                for param in params:
                    if param.startswith('relay='):
                        relay = param[6:]
                        print(f"DEBUG: Extracted relay: {relay}")
                        relays.append(relay)
                    elif param.startswith('secret='):
                        secret = param[7:]
                        print(f"DEBUG: Extracted secret: {secret}")
                    elif param.startswith('lud16='):
                        lud16 = param[6:]
                        print(f"DEBUG: Extracted lud16: {lud16}")
            else:
                print(f"DEBUG: No query parameters found")
            if not pubkey or not len(relays) > 0 or not secret:
                raise ValueError("Invalid NWC URL: missing required fields (pubkey, relay, or secret)")
            # Validate secret (should be 64 hex characters)
            if len(secret) != 64 or not all(c in '0123456789abcdef' for c in secret):
                raise ValueError("Invalid NWC URL: secret must be 64 hex characters")
            print(f"DEBUG: Parsed NWC data - Relay: {relays}, Pubkey: {pubkey}, Secret: {secret}, lud16: {lud16}")
            return relays, pubkey, secret, lud16
        except Exception as e:
            raise RuntimeError(f"Exception parsing NWC URL {nwc_url}: {e}")


