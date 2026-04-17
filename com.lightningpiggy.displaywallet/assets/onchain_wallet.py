import json
import time

from mpos import TaskManager, DownloadManager

from wallet import Wallet
from payment import Payment
from unique_sorted_list import UniqueSortedList


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class OnchainWallet(Wallet):
    """On-chain Bitcoin wallet backed by mempool.space's xpub endpoint.

    Derivation happens server-side — no BIP32/bech32 client code needed.
    The xpub is sent to the mempool.space operator, so privacy-conscious
    users should point at a self-hosted instance via onchain_mempool_url.
    """

    PAYMENTS_TO_SHOW = 6
    PERIODIC_FETCH_SECONDS_UNCONFIRMED = 60   # while any tx is pending
    PERIODIC_FETCH_SECONDS_CONFIRMED = 300    # when everything's confirmed
    DEFAULT_MEMPOOL_URL = "https://mempool.space"

    def __init__(self, xpub, mempool_url=None):
        super().__init__()
        if not xpub:
            raise ValueError('xpub is not set.')
        xpub = xpub.strip()
        if xpub[:4] not in ("xpub", "ypub", "zpub", "tpub", "upub", "vpub"):
            raise ValueError('xpub must start with xpub/ypub/zpub (or testnet variants)')
        self.xpub = xpub
        self.mempool_url = (mempool_url or self.DEFAULT_MEMPOOL_URL).rstrip('/')
        self._any_unconfirmed = True  # first poll uses fast cadence

    def _format_date(self, epoch_time):
        """Format epoch time as 'Apr 16' (month + day)."""
        try:
            t = time.localtime(epoch_time)
            return "{} {}".format(_MONTHS[t[1] - 1], t[2])
        except Exception:
            return ""

    def _parse_transactions(self, response):
        """Parse mempool.space wallet response into a UniqueSortedList of Payments.

        Returns (payments, any_unconfirmed).
        """
        our_addresses = set(response.keys())
        seen_txids = set()
        payments = UniqueSortedList()
        any_unconfirmed = False

        for addr_data in response.values():
            for tx in addr_data.get("transactions", []):
                txid = tx.get("txid")
                if not txid or txid in seen_txids:
                    continue
                seen_txids.add(txid)

                sent = 0
                for vin in tx.get("vin", []):
                    prevout = vin.get("prevout") or {}
                    if prevout.get("scriptpubkey_address") in our_addresses:
                        sent += prevout.get("value", 0)

                received = 0
                for vout in tx.get("vout", []):
                    if vout.get("scriptpubkey_address") in our_addresses:
                        received += vout.get("value", 0)

                net = received - sent

                status = tx.get("status") or {}
                confirmed = bool(status.get("confirmed"))
                if not confirmed:
                    any_unconfirmed = True
                epoch_time = status.get("block_time") or int(time.time())

                date_str = self._format_date(epoch_time)
                status_str = "confirmed" if confirmed else "pending"

                if net == 0:
                    # Self-transfer — show the fee as a negative amount
                    fee = tx.get("fee", 0)
                    comment = "{} self-transfer".format(date_str).strip()
                    payments.add(Payment(epoch_time, -fee, comment))
                else:
                    comment = "{} {}".format(date_str, status_str).strip()
                    payments.add(Payment(epoch_time, net, comment))

        return payments, any_unconfirmed

    def _pick_receive_address(self, response):
        """Return an unused receive address as a BIP21 URI, or None."""
        # Prefer bech32 (bc1.../tb1...) then legacy
        best = None
        for addr, addr_data in response.items():
            cs = addr_data.get("chain_stats") or {}
            ms = addr_data.get("mempool_stats") or {}
            if cs.get("tx_count", 0) == 0 and ms.get("tx_count", 0) == 0:
                if addr.startswith(("bc1", "tb1")):
                    return "bitcoin:" + addr
                if best is None:
                    best = addr
        if best:
            return "bitcoin:" + best
        return None

    async def fetch_balance_and_payments(self):
        """Single mempool.space call that populates balance, payments, and receive code."""
        url = self.mempool_url + "/api/v1/wallet/" + self.xpub
        print("OnchainWallet: fetching " + url)
        try:
            response_bytes = await DownloadManager.download_url(url)
        except Exception as e:
            raise RuntimeError("fetch_balance: GET {} failed: {}".format(url, e))

        try:
            response = json.loads(response_bytes.decode("utf-8"))
        except Exception as e:
            raise RuntimeError("Could not parse mempool.space response as JSON: {}".format(e))

        # Balance: sum across all derived addresses (confirmed + mempool)
        balance = 0
        for addr_data in response.values():
            cs = addr_data.get("chain_stats") or {}
            ms = addr_data.get("mempool_stats") or {}
            balance += cs.get("funded_txo_sum", 0) - cs.get("spent_txo_sum", 0)
            balance += ms.get("funded_txo_sum", 0) - ms.get("spent_txo_sum", 0)

        self.handle_new_balance(balance, fetchPaymentsIfChanged=False)

        # Payments
        payments, any_unconfirmed = self._parse_transactions(response)
        self._any_unconfirmed = any_unconfirmed
        if len(payments) > 0:
            self.handle_new_payments(payments)

        # Receive address — only fetch if user hasn't set one in settings
        if not self.static_receive_code:
            receive = self._pick_receive_address(response)
            if receive:
                self.handle_new_static_receive_code(receive)

    async def fetch_balance(self):
        """Alias for fetch_balance_and_payments (base class compatibility)."""
        await self.fetch_balance_and_payments()

    async def fetch_payments(self):
        """No-op — payments are fetched alongside the balance."""
        pass

    async def async_wallet_manager_task(self):
        while self.keep_running:
            try:
                await self.fetch_balance_and_payments()
            except Exception as e:
                print("WARNING: OnchainWallet got exception: {}".format(e))
                import sys
                sys.print_exception(e)
                self.handle_error(e)

            interval = (self.PERIODIC_FETCH_SECONDS_UNCONFIRMED
                        if self._any_unconfirmed
                        else self.PERIODIC_FETCH_SECONDS_CONFIRMED)
            print("Sleeping {}s before next on-chain fetch...".format(interval))
            for _ in range(interval * 10):
                await TaskManager.sleep(0.1)
                if not self.keep_running:
                    break
        print("OnchainWallet main() stopping...")
