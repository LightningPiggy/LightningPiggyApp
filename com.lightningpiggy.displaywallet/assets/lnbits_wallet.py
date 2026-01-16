import json
import requests

from websocket import WebSocketApp

from mpos import TaskManager

from wallet import Wallet
from payment import Payment
from unique_sorted_list import UniqueSortedList

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
                comment = first_from_list # if the above threw exception, it will catch below
        except Exception as e:
            pass
        comment = super().try_parse_as_zap(comment)
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
                import sys
                sys.print_exception(e)
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
                    TaskManager.create_task(self.ws.run_forever(),)
                except Exception as e:
                    print(f"Got exception while creating task for LNBitsWallet websocket: {e}")
            print("Sleeping a while before re-fetching balance...")
            for _ in range(self.PERIODIC_FETCH_BALANCE_SECONDS*10):
                await TaskManager.sleep(0.1)
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
