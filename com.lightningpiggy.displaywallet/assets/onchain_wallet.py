import json
import time

from mpos import TaskManager, DownloadManager

from wallet import Wallet
from payment import Payment
from unique_sorted_list import UniqueSortedList


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _try_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


class OnchainWallet(Wallet):
    """On-chain Bitcoin wallet backed by a Blockbook instance.

    Blockbook (https://github.com/trezor/blockbook) does server-side
    derivation from the xpub/ypub/zpub and returns balance, transactions,
    and derived addresses in a single call. The default points at Trezor's
    hosted instance; privacy-conscious users can set a self-hosted Blockbook
    URL (Umbrel, Start9, BTCPay Server, Sparrow Server, etc.) via the
    onchain_blockbook_url setting.
    """

    PAYMENTS_TO_SHOW = 6
    PERIODIC_FETCH_SECONDS_UNCONFIRMED = 60   # while any tx is pending
    PERIODIC_FETCH_SECONDS_CONFIRMED = 300    # when everything's confirmed
    DEFAULT_BLOCKBOOK_URL = "https://btc1.trezor.io"
    # Trezor's hosted Blockbook is Cloudflare-proxied; a browser UA avoids 403.
    _USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122 Safari/537.36")

    def __init__(self, xpub, blockbook_url=None):
        super().__init__()
        if not xpub:
            raise ValueError('xpub is not set.')
        xpub = xpub.strip()
        if xpub[:4] not in ("xpub", "ypub", "zpub", "tpub", "upub", "vpub"):
            raise ValueError('xpub must start with xpub/ypub/zpub (or testnet variants)')
        self.xpub = xpub
        self.blockbook_url = (blockbook_url or self.DEFAULT_BLOCKBOOK_URL).rstrip('/')
        self._any_unconfirmed = True  # first poll uses fast cadence

    def _format_date(self, epoch_time):
        """Format epoch time as 'Apr 16' (month + day)."""
        try:
            t = time.localtime(epoch_time)
            return "{} {}".format(_MONTHS[t[1] - 1], t[2])
        except Exception:
            return ""

    def _parse_transactions(self, transactions):
        """Parse Blockbook transactions into a UniqueSortedList of Payments.

        Blockbook marks inputs/outputs belonging to our xpub with
        `isOwn: true`, so we don't need to track derived addresses ourselves.
        Returns (payments, any_unconfirmed).
        """
        payments = UniqueSortedList()
        any_unconfirmed = False

        for tx in transactions or []:
            confirmations = tx.get("confirmations", 0) or 0
            confirmed = confirmations > 0
            if not confirmed:
                any_unconfirmed = True

            sent = 0
            all_inputs_ours = bool(tx.get("vin"))
            for vin in tx.get("vin", []):
                if vin.get("isOwn"):
                    sent += _try_int(vin.get("value", "0"))
                else:
                    all_inputs_ours = False

            received = 0
            all_outputs_ours = bool(tx.get("vout"))
            for vout in tx.get("vout", []):
                if vout.get("isOwn"):
                    received += _try_int(vout.get("value", "0"))
                else:
                    all_outputs_ours = False

            net = received - sent
            epoch_time = tx.get("blockTime") or int(time.time())
            date_str = self._format_date(epoch_time)
            status_str = "confirmed" if confirmed else "pending"

            if all_inputs_ours and all_outputs_ours:
                # All inputs + outputs ours — classic self-transfer, fee-only loss.
                fee = _try_int(tx.get("fees", "0"))
                comment = "{} self-transfer".format(date_str).strip()
                payments.add(Payment(epoch_time, -fee, comment))
            else:
                comment = "{} {}".format(date_str, status_str).strip()
                payments.add(Payment(epoch_time, net, comment))

        return payments, any_unconfirmed

    def _pick_receive_address(self, tokens):
        """Return an unused external receive address as a BIP21 URI, or None.

        Blockbook tokens carry a `path` like `m/84'/0'/0'/0/3`. The
        second-to-last segment is the chain (0 = external / receive,
        1 = change). We pick the lowest-index unused external address.
        """
        best_idx = None
        best_addr = None
        for t in tokens or []:
            path = t.get("path") or ""
            parts = path.split("/")
            if len(parts) < 2:
                continue
            if parts[-2] != "0":  # must be external (receive) chain
                continue
            if (t.get("transfers") or 0) != 0:
                continue
            try:
                idx = int(parts[-1])
            except ValueError:
                continue
            if best_idx is None or idx < best_idx:
                best_idx = idx
                best_addr = t.get("name")
        if best_addr:
            return "bitcoin:" + best_addr
        return None

    async def fetch_balance_and_payments(self):
        """Single Blockbook call populates balance, payments, and receive code."""
        url = "{}/api/v2/xpub/{}?details=txs&tokens=derived".format(
            self.blockbook_url, self.xpub)
        # Don't log the full URL: it contains the xpub, which would leak the
        # user's entire derivation tree (all past/future addresses) if logs
        # are ever shared for debugging.
        print("OnchainWallet: fetching from {}".format(self.blockbook_url))
        try:
            response_bytes = await DownloadManager.download_url(
                url, headers={"User-Agent": self._USER_AGENT})
        except Exception as e:
            # Scrub xpub from error message for the same reason.
            raise RuntimeError(
                "fetch_balance: GET to {} failed: {}".format(self.blockbook_url, e))

        try:
            response = json.loads(response_bytes.decode("utf-8"))
        except Exception as e:
            raise RuntimeError("Could not parse Blockbook response as JSON: {}".format(e))

        # Balance: confirmed + mempool (Blockbook returns strings; unconfirmed may be negative)
        balance = (_try_int(response.get("balance", "0"))
                   + _try_int(response.get("unconfirmedBalance", "0")))
        self.handle_new_balance(balance, fetchPaymentsIfChanged=False)

        # Payments
        payments, any_unconfirmed = self._parse_transactions(response.get("transactions"))
        self._any_unconfirmed = any_unconfirmed or (response.get("unconfirmedTxs") or 0) > 0
        if len(payments) > 0:
            self.handle_new_payments(payments)

        # Receive address — only fetch if user hasn't set one in settings
        if not self.static_receive_code:
            receive = self._pick_receive_address(response.get("tokens"))
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
