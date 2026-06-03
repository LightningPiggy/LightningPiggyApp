import ssl
import json
import time

from mpos.util import urldecode
from mpos import TaskManager

from nostr.relay_manager import RelayManager
from nostr.message_type import ClientMessageType
from nostr.filter import Filter, Filters
from nostr.event import EncryptedDirectMessage
from nostr.key import PrivateKey

from wallet import Wallet, ensure_lightning_prefix
from payment import Payment
from unique_sorted_list import UniqueSortedList

# TEMPORARY DIAGNOSTIC — monkey-patch nostr.relay.Relay._on_error to include
# the exception detail + URL in its log output. The upstream library only
# prints a bare "relay.py got error" (fixed in micropython-nostr PR #1 but
# that's not yet shipping in a MicroPythonOS release). We patch it at
# runtime here so a failing NWC connect surfaces the actual cause in logs.
# Remove this block once the upstream fix is in the frozen nostr module.
try:
    import nostr.relay as _nostr_relay
    _orig_relay_on_error = _nostr_relay.Relay._on_error
    def _patched_relay_on_error(self, class_obj, error):
        try:
            print("relay.py got error for {}: {!r}".format(self.url, error))
        except Exception:
            pass
        return _orig_relay_on_error(self, class_obj, error)
    _nostr_relay.Relay._on_error = _patched_relay_on_error
except Exception as _e:
    print("Failed to patch Relay._on_error for diagnostics:", _e)

class NWCWallet(Wallet):

    PAYMENTS_TO_SHOW = 6
    PERIODIC_FETCH_BALANCE_SECONDS = 120 # seconds — NWC pushes cover real-time payments, this poll is a heartbeat / silent-disconnect check

    # Watchdog for the half-broken-relay case: the TCP connection sends fine
    # but receives nothing (one-way packet loss on a weak WiFi signal can
    # leave the socket in this state, and the kernel-level TCP timeout on
    # ESP32 takes a very long time to fire). After this many consecutive
    # poll cycles where we PUBLISH but receive ZERO events back from the
    # relay, force a relay close + reopen + re-subscription. 3 cycles =
    # 6 minutes of silence before reconnect, which is still less than the
    # 10-minute stale-indicator threshold so most users will never see the
    # orange dot for this failure mode.
    RELAY_SILENT_RECONNECT_THRESHOLD = 3

    relays = []
    secret = None
    wallet_pubkey = None

    def __init__(self, nwc_url):
        super().__init__()
        # Per-instance cleanup flag (base class defaults to True; we flip it
        # during stop() while the async close_connections task is in flight).
        self._cleanup_done = True
        self.relay_manager = None
        # Watchdog state: count of poll cycles since the last received
        # event from any relay. Reset to 0 every time an event arrives
        # (success), incremented after each fetch_balance/payments pair.
        self._polls_since_last_event = 0
        self.nwc_url = nwc_url
        if not nwc_url:
            raise ValueError('NWC URL is not set.')
        # Cache slot identity — fingerprints are stamped on by DisplayWallet
        # after construction (they depend on prefs, not just wallet state).
        self.slot_key = "nwc"
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

    def stop(self):
        """Stop the wallet AND eagerly close relay websockets so a quick
        restart (e.g. user changed NWC URL in Settings → came back) doesn't
        race against the old sockets still holding ESP32's limited TCP
        pool. The base Wallet.stop() just flips keep_running=False and
        relies on the main loop to notice and clean up on its next 100ms
        sleep tick, which is too slow — the new wallet can try to open new
        connections before the old ones close, exhausting the socket pool
        and producing 'Could not connect to any Nostr Wallet Connect
        relays' even when the network is fine."""
        super().stop()  # sets keep_running = False
        if self.relay_manager is not None and self._cleanup_done:
            self._cleanup_done = False
            TaskManager.create_task(self._close_relays())

    async def _close_relays(self):
        try:
            await self.relay_manager.close_connections()
        except Exception as e:
            print("NWCWallet: error closing relay connections: {}".format(e))
        self._cleanup_done = True

    def _setup_subscription(self):
        """Register the NIP-47 response/notification subscription with all
        connected relays and publish the REQUEST message. Pulled out of the
        main task body so we can also call it after a watchdog reconnect."""
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
        request_message = [ClientMessageType.REQUEST, self.subscription_id]
        request_message.extend(self.filters.to_json_array())
        print(f"DEBUG: Publishing subscription request")
        self.relay_manager.publish_message(json.dumps(request_message))
        print(f"DEBUG: Published subscription request")

    async def _reconnect_relay(self):
        """Watchdog action: the TCP send-side is working (we keep publishing
        successfully) but no events have come back from the relay for
        RELAY_SILENT_RECONNECT_THRESHOLD consecutive polls. The socket is
        most likely in a half-broken state — kernel-level TCP timeout on
        ESP32 takes minutes-to-hours to fire — so force a fresh connection
        instead of waiting it out.

        Closes the existing relay_manager's connections, builds a fresh
        manager (the connection objects may be in a bad internal state —
        a new instance is safer than reusing), reopens, re-subscribes."""
        print("NWCWallet: watchdog reconnecting relay (silent for {} polls)".format(
            self._polls_since_last_event))
        try:
            await self.relay_manager.close_connections()
        except Exception as e:
            print("NWCWallet: close during reconnect failed (continuing): {}".format(e))
        # Give the ESP32 LWIP stack time to actually release the closed
        # sockets back to the pool before we ask for new ones. Without this
        # pause, back-to-back close+open in a tight watchdog loop can
        # exhaust the limited TCP socket pool and crash the wallet task.
        # 2 s is negligible against the 6-minute reconnect cadence (threshold
        # 3 polls × 120 s) but covers the kernel-side socket-teardown window.
        await TaskManager.sleep(2)
        self.relay_manager = RelayManager()
        for relay in self.relays:
            self.relay_manager.add_relay(relay)
        try:
            await self.relay_manager.open_connections({"cert_reqs": ssl.CERT_NONE})
        except Exception as e:
            print("NWCWallet: open_connections during reconnect failed: {}".format(e))
            # Don't return — fall through and try to re-subscribe; the next
            # iteration of the watchdog will catch repeated failure.
        # Brief wait for at least one relay to come up so add_subscription
        # has a connected target. 5 s is enough for the WebSocket handshake
        # on a healthy link; longer would block the main loop.
        for _ in range(50):
            await TaskManager.sleep(0.1)
            if not self.keep_running:
                return
            if self.relay_manager.connected_or_errored_relays() == len(self.relays):
                break
        self._setup_subscription()
        # Reset the watchdog counter regardless of whether the reconnect
        # actually fixed things — if the relay is still silent we'll just
        # trip the watchdog again N polls later and retry.
        self._polls_since_last_event = 0

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
            print(f"Info: comment {comment} is not JSON, this is fine, using as-is ({e})")
        comment = super().try_parse_as_zap(comment)
        return comment

    async def async_wallet_manager_task(self):
        if self.lud16:
            # Wrap as `lightning:<address>` URI so QR scanners that look for
            # the URI scheme handle the code without relying on lud16
            # pattern-detection (boosts wallet compatibility ~90% → ~95%).
            self.handle_new_static_receive_code(ensure_lightning_prefix(self.lud16))

        self.private_key = PrivateKey(bytes.fromhex(self.secret))
        self.relay_manager = RelayManager()
        for relay in self.relays:
            self.relay_manager.add_relay(relay)

        print(f"DEBUG: Opening relay connections")
        await self.relay_manager.open_connections({"cert_reqs": ssl.CERT_NONE})
        self.connected = False
        nrconnected = 0
        # Up to 30 s wait. The first connect attempt can fail fast
        # (ECONNABORTED during a WiFi blip), then the relay's own
        # auto-reconnect (3 s back-off + fresh TLS handshake) needs ~15 s
        # before on_open actually fires. A 10 s wait here used to time
        # out right before the successful reconnect, causing the wallet
        # task to exit while the websocket quietly came up behind it —
        # leaving the UI with cached data and no further updates until
        # the next app relaunch.
        for _ in range(300):
            await TaskManager.sleep(0.1)
            nrconnected = self.relay_manager.connected_or_errored_relays()
            if nrconnected == len(self.relays) or not self.keep_running:
                break
        if nrconnected == 0:
            self.handle_error("Could not connect to any Nostr Wallet Connect relays.")
            return
        if not self.keep_running:
            print(f"async_wallet_manager_task does not have self.keep_running, returning...")
            return

        print(f"{nrconnected} relays connected")

        self._setup_subscription()

        last_fetch_balance = time.time() - self.PERIODIC_FETCH_BALANCE_SECONDS
        while True: # handle incoming events and do periodic fetch_balance
            #print(f"checking for incoming events...")
            await TaskManager.sleep(0.1)
            if not self.keep_running:
                # Connections are closed by stop() via _close_relays(),
                # which was scheduled the moment stop() was called. Just
                # exit the loop here.
                print("NWCWallet: not keep_running, exiting main loop")
                break

            if time.time() - last_fetch_balance >= self.PERIODIC_FETCH_BALANCE_SECONDS:
                last_fetch_balance = time.time()
                # Watchdog: if the relay has been silent across
                # RELAY_SILENT_RECONNECT_THRESHOLD prior poll cycles
                # (i.e. we published RPCs but no useful responses came
                # back), the WebSocket is most likely in a half-broken
                # state. Force a reconnect BEFORE issuing the next pair
                # of publishes so they go out over a fresh socket. The
                # counter is reset in the response handler below only
                # when a USEFUL response (balance or transactions)
                # arrives — historical events from subscription setup,
                # decryption failures, and push notifications without
                # `result` don't count. This is important: an earlier
                # iteration reset on any `has_events()` and that masked
                # the half-broken state because non-useful chatter kept
                # zeroing the counter.
                if self._polls_since_last_event >= self.RELAY_SILENT_RECONNECT_THRESHOLD:
                    await self._reconnect_relay()
                    if not self.keep_running:
                        break
                self._polls_since_last_event += 1
                try:
                    await self.fetch_balance()
                except Exception as e:
                    print(f"fetch_balance got exception {e}") # fetch_balance got exception 'NoneType' object isn't iterable?!
                # Also poll list_transactions every cycle. handle_new_balance
                # only triggers fetch_payments when the balance changes,
                # which never happens on budgeted NWC connections (e.g.
                # Primal/Spark, where get_balance returns the connection
                # budget — locked at the value chosen during setup). Without
                # this independent poll, list_transactions is fetched once
                # on initial connect and the displayed payments list goes
                # stale forever for that class of wallet.
                try:
                    await self.fetch_payments()
                except Exception as e:
                    print(f"fetch_payments got exception {e}")

            start_time = time.ticks_ms()
            if self.relay_manager.message_pool.has_events():
                # NB: don't reset the watchdog counter here. has_events()
                # also returns True for events that aren't useful NWC
                # responses — historical events from subscription setup,
                # decryption-failure cases, push notifications without
                # a `result` field, etc. Resetting too eagerly masks
                # the half-broken-socket state where the relay sends
                # back chatter but never the actual poll responses.
                # The counter resets only in the branches below that
                # actually deliver fresh balance or transactions data
                # (i.e., the same branches that refresh last_updated
                # via notify_poll_success / handle_new_payments).
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
                            # Signal "we got a response" regardless of whether
                            # the balance actually changed — without this the
                            # stale-data indicator never resets when balance
                            # is unchanged across polls.
                            self.notify_poll_success()
                            # Watchdog reset: a USEFUL response arrived
                            # (balance), so the relay is alive in both
                            # directions for the path we care about. Any
                            # accumulated silence streak is forgiven.
                            if self._polls_since_last_event > 0:
                                print("NWCWallet: watchdog counter reset (was {}, balance arrived)".format(
                                    self._polls_since_last_event))
                            self._polls_since_last_event = 0
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
                            # Watchdog reset: useful response (transactions).
                            if self._polls_since_last_event > 0:
                                print("NWCWallet: watchdog counter reset (was {}, transactions arrived)".format(
                                    self._polls_since_last_event))
                            self._polls_since_last_event = 0
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

    async def fetch_balance(self):
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

    async def fetch_payments(self):
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
        # Don't log the raw URL — the query string contains the secret, which
        # authorises spending. Log only state transitions, not content.
        print("DEBUG: Starting to parse NWC URL")
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
            # (URL after prefix removal is not logged — still contains secret.)
            # urldecode because the relay might have %3A%2F%2F etc
            nwc_url = urldecode(nwc_url)
            # (urldecoded URL also not logged — still contains secret.)
            # Split into pubkey and query params
            parts = nwc_url.split('?')
            pubkey = parts[0]
            # Pubkey is semi-public (identifies the wallet service) but
            # sharing it is still a fingerprint. Don't log the raw value.
            print("DEBUG: Extracted pubkey (content redacted)")
            # Validate pubkey (should be 64 hex characters)
            if len(pubkey) != 64 or not all(c in '0123456789abcdef' for c in pubkey):
                raise ValueError("Invalid NWC URL: pubkey must be 64 hex characters")
            # Extract relay, secret, and lud16 from query params
            relays = []
            lud16 = None
            secret = None
            if len(parts) > 1:
                # The query string contains secret=...; don't log its raw
                # value — only that query params were found.
                print("DEBUG: Query parameters found")
                params = parts[1].split('&')
                for param in params:
                    if param.startswith('relay='):
                        relay = param[6:]
                        print(f"DEBUG: Extracted relay: {relay}")
                        relays.append(relay)
                    elif param.startswith('secret='):
                        secret = param[7:]
                        # Never log the secret itself — it authorises spending.
                        print("DEBUG: Extracted secret (content redacted)")
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
            # Relays + lud16 are not sensitive; pubkey + secret are redacted
            # (pubkey is effectively public once paired, but still fingerprints
            # the user's wallet provider to anyone reading logs; secret
            # authorises spending).
            print(f"DEBUG: Parsed NWC data - Relays: {relays}, lud16: {lud16}")
            return relays, pubkey, secret, lud16
        except Exception as e:
            # Don't include the NWC URL in the error — it contains the secret.
            raise RuntimeError(f"Exception parsing NWC URL: {e}")


