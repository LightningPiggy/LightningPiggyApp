import hashlib
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


# ---------------------------------------------------------------------------
# Bitcoin address validators (single-address mode).
#
# Self-contained — these are intentionally NOT pulled from any of the
# bech32/base58 modules the device might already have, so the wallet
# doesn't acquire a transitive dep that complicates portability or
# testing. ~80 lines of pure Python, runs once at wallet init.
#
# Coverage:
#   * Base58Check  → P2PKH / P2SH, mainnet + testnet
#   * Bech32 (v0) → P2WPKH / P2WSH, mainnet + testnet + regtest
#   * Bech32m (v1+) → P2TR (Taproot), mainnet + testnet + regtest
#
# We never construct addresses here — only validate user input — so the
# encoder paths in the reference impls are deliberately omitted.
# ---------------------------------------------------------------------------

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BECH32_CONST = 1
_BECH32M_CONST = 0x2bc830a3
_BECH32_HRPS = ("bc", "tb", "bcrt")

_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
# Address version bytes we accept. 0x00/0x05 = mainnet P2PKH/P2SH;
# 0x6F/0xC4 = testnet (and regtest) P2PKH/P2SH.
_BASE58_VERSIONS = (0x00, 0x05, 0x6F, 0xC4)


def _bech32_polymod(values):
    GEN = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            if (b >> i) & 1:
                chk ^= GEN[i]
    return chk


def _bech32_hrp_expand(hrp):
    return [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]


def _bech32_convertbits(data, frombits, tobits, pad):
    """Standard 5-bit → 8-bit witness program decode (BIP-173 §5)."""
    acc = 0
    bits = 0
    ret = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for value in data:
        if value < 0 or (value >> frombits):
            return None
        acc = ((acc << frombits) | value) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        return None
    return ret


def _is_valid_bech32_address(addr):
    """Validate a SegWit / Taproot bech32(m) address per BIP-173 + BIP-350.

    Accepts both bech32 (witness v0) and bech32m (witness v1+) encodings.
    Mainnet (bc1...), testnet (tb1...), regtest (bcrt1...). Mixed case
    rejected per BIP-173. Witness-program length enforced to the spec
    (v0 → 20 or 32 bytes, others 2..40).
    """
    if not addr or len(addr) > 90:
        return False
    # Reject non-printable / non-ASCII early — index() on the charset
    # would catch most of these but a clean predicate is clearer.
    for c in addr:
        o = ord(c)
        if o < 33 or o > 126:
            return False
    # Mixed case is invalid (the spec forbids it precisely because
    # bech32 is meant to survive case-folding in QR scanners /
    # voice / handwritten copy). Either all-upper or all-lower OK.
    if addr.lower() != addr and addr.upper() != addr:
        return False
    addr = addr.lower()
    pos = addr.rfind('1')
    if pos < 1 or pos + 7 > len(addr):
        return False
    hrp = addr[:pos]
    if hrp not in _BECH32_HRPS:
        return False
    data_part = addr[pos + 1:]
    data = []
    for c in data_part:
        i = _BECH32_CHARSET.find(c)
        if i < 0:
            return False
        data.append(i)
    # Try bech32 (v0) and bech32m (v1+) in turn; the right one for the
    # witness version must match the encoding's checksum constant.
    polymod = _bech32_polymod(_bech32_hrp_expand(hrp) + data)
    if polymod == _BECH32_CONST:
        spec = "bech32"
    elif polymod == _BECH32M_CONST:
        spec = "bech32m"
    else:
        return False
    if len(data) < 1 + 6:  # need at least witver + 6-byte checksum
        return False
    witver = data[0]
    if witver > 16:
        return False
    program = _bech32_convertbits(data[1:-6], 5, 8, False)
    if program is None or not (2 <= len(program) <= 40):
        return False
    # Witness-version / encoding pairing (BIP-350): v0 uses bech32, v1+
    # uses bech32m. A v0 address encoded with bech32m (or vice versa) is
    # malformed.
    if witver == 0 and spec != "bech32":
        return False
    if witver != 0 and spec != "bech32m":
        return False
    # v0 must encode either a 20-byte (P2WPKH) or 32-byte (P2WSH) program.
    if witver == 0 and len(program) not in (20, 32):
        return False
    return True


def _is_valid_base58check_address(addr):
    """Validate a legacy / P2SH base58check address.

    Accepts mainnet P2PKH (`1...`), P2SH (`3...`), and testnet/regtest
    P2PKH (`m...` / `n...`) + P2SH (`2...`). Decodes the address,
    verifies the 4-byte double-SHA256 checksum, and checks the version
    byte against the accepted set.
    """
    if not addr or len(addr) < 26 or len(addr) > 35:
        return False
    n = 0
    for c in addr:
        i = _BASE58_ALPHABET.find(c)
        if i < 0:
            return False
        n = n * 58 + i
    # Convert the integer back to bytes (big-endian). MicroPython lacks
    # both bytearray.reverse() AND negative-step slicing, so we build
    # the byte list little-endian and feed it through reversed().
    body_le = []
    while n > 0:
        body_le.append(n & 0xff)
        n >>= 8
    body = bytes(reversed(body_le))
    # Restore leading zero bytes — base58 encodes each leading 0x00
    # byte as a leading '1' character.
    leading_ones = 0
    for c in addr:
        if c == '1':
            leading_ones += 1
        else:
            break
    decoded = bytes(leading_ones) + body
    if len(decoded) != 25:
        return False
    payload, checksum = decoded[:-4], decoded[-4:]
    expected = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    if checksum != expected:
        return False
    if payload[0] not in _BASE58_VERSIONS:
        return False
    return True


_XPUB_PREFIXES = ("xpub", "ypub", "zpub", "tpub", "upub", "vpub")


def classify_credential(s):
    """Decide whether `s` is an extended public key or a single address.

    Returns:
        ("xpub", normalized_string)     — for xpub/ypub/zpub (mainnet
                                          or testnet variants).
        ("address", normalized_string)  — for a fully-validated
                                          base58check or bech32(m)
                                          Bitcoin address.

    Raises ValueError for anything that fits neither shape. We do NOT
    try to parse the body of an xpub — Blockbook will surface a
    checksum error on a malformed one — but a single address must
    pass full base58check / bech32(m) validation locally so the user
    gets immediate feedback before any network call.
    """
    if not s:
        raise ValueError("credential is not set.")
    s = s.strip()
    if s[:4] in _XPUB_PREFIXES:
        return ("xpub", s)
    if _is_valid_bech32_address(s) or _is_valid_base58check_address(s):
        return ("address", s)
    raise ValueError(
        "credential must be xpub/ypub/zpub (or testnet variant) "
        "or a valid Bitcoin address"
    )


class OnchainWallet(Wallet):
    """On-chain Bitcoin wallet backed by a Blockbook instance.

    Blockbook (https://github.com/trezor/blockbook) does server-side
    derivation from the xpub/ypub/zpub and returns balance, transactions,
    and derived addresses in a single call. The default points at Trezor's
    hosted instance; privacy-conscious users can set a self-hosted Blockbook
    URL (Umbrel, Start9, BTCPay Server, Sparrow Server, etc.) via the
    onchain_blockbook_url setting.

    Privacy note: whoever runs the Blockbook instance sees every address
    derived from your xpub and can link them together. That's true of any
    external indexer; funds custody is unaffected.
    """

    PAYMENTS_TO_SHOW = 6
    PERIODIC_FETCH_SECONDS_UNCONFIRMED = 60   # while any tx is pending
    PERIODIC_FETCH_SECONDS_CONFIRMED = 300    # when everything's confirmed
    DEFAULT_BLOCKBOOK_URL = "https://btc1.trezor.io"
    # Trezor's hosted Blockbook is Cloudflare-proxied; a browser UA avoids 403.
    _USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/122 Safari/537.36")
    # Whether the running MPOS framework supports DownloadManager's
    # redact_url= kwarg (added in MicroPythonOS#136, shipped 0.9.6+).
    # None = unknown / not probed yet; True/False set by first successful
    # or first TypeError-raising call in fetch_balance_and_payments.
    # Class-level so the verdict survives wallet-restart cycles.
    _redact_url_supported = None

    def __init__(self, credential, blockbook_url=None):
        """`credential` is either an extended public key (xpub/ypub/zpub
        + testnet variants) or a single Bitcoin address. The mode is
        auto-detected so the settings UI can offer one field instead of
        two — see `classify_credential` at module top.

        In xpub mode the wallet watches every address derived from the
        key and rotates the receive QR through unused external
        addresses. In address mode the wallet watches the one address
        and the receive QR is always that address (no rotation, since
        there's no derivation tree to rotate through).
        """
        super().__init__()
        mode, value = classify_credential(credential)
        self.mode = mode  # "xpub" | "address"
        if mode == "xpub":
            self.xpub = value
            self.address = None
        else:
            self.xpub = None
            self.address = value
        self.blockbook_url = (blockbook_url or self.DEFAULT_BLOCKBOOK_URL).rstrip('/')
        # Cache slot — DisplayWallet.went_online() stamps creds/qr fingerprints
        # after construction (same pattern as LNBitsWallet / NWCWallet).
        self.slot_key = "onchain"
        self._any_unconfirmed = True  # first poll uses fast cadence
        # Tracks whether the currently-displayed receive address has been used
        # yet, so we know when to rotate to the next unused index. Initially
        # None — first successful fetch will pick one. Address mode reuses
        # this slot as a "have we set the receive code yet?" flag so the
        # `handle_new_static_receive_code(...)` call happens exactly once.
        self._displayed_receive_addr = None

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

    def _pick_unused_receive_address(self, tokens):
        """Return the lowest-index unused external receive address, or None.

        Blockbook tokens carry a `path` like `m/84'/0'/0'/0/3`. The
        second-to-last segment is the chain (0 = external / receive,
        1 = change). We pick the lowest-index entry with transfers == 0.
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
        return best_addr

    def _displayed_address_has_been_used(self, tokens, current_addr):
        """True if the currently-displayed receive address now has a transfer.

        Used to rotate the QR to the next unused address right after a
        payment lands on the displayed one, without rotating mid-scan
        when the address is still fresh.
        """
        if not current_addr:
            return False
        for t in tokens or []:
            if t.get("name") == current_addr:
                return (t.get("transfers") or 0) > 0
        # Not in the response (gap-limit drift, etc.) → assume still fresh.
        return False

    async def fetch_balance_and_payments(self):
        """Single Blockbook call populates balance, payments, and receive code.

        Endpoint depends on mode:
            xpub mode    → /api/v2/xpub/{xpub}?details=txslight&tokens=derived&pageSize=N
                           (server-side derivation; `tokens` carries all
                           addresses + their `transfers` count, used to
                           pick the next unused receive address)
            address mode → /api/v2/address/{addr}?details=txslight&pageSize=N
                           (single watched address; no `tokens`, no
                           receive-address rotation)

        `details=txslight` (vs the default `txs`) drops per-tx fields the
        parser doesn't use — `hex`, `version`, `size`, vin/vout script
        bytes, etc. — and keeps everything we do use: `confirmations`,
        `vin[].value`, `vout[].value`, `vout[].isOwn`, `fees`, `blockTime`.
        Measured response size on a typical 21-tx page: ~177 KB → ~101 KB
        (~43 % smaller, ~76 KB saved per fetch). Suggested by Thomas in
        LightningPiggyApp#45 review.

        `pageSize` is capped at `self.PAYMENTS_TO_SHOW` (the user's per-slot
        Transactions Shown setting from PR #43, default 6, max 21). Without
        the cap, Blockbook defaults to 1000 transactions per page; on
        addresses with many txs (mainnet genesis ~3000+, or the kind of
        mining-payout cluster Thomas reported with ~5000) the JSON
        response + the subsequent slot-cache write blew the ESP32-S3
        heap with `MemoryError: memory allocation failed`. Fetching only
        what's actually displayed kills that bug at the source; txslight
        compounds the savings.
        """
        # PAYMENTS_TO_SHOW is set on the instance by DisplayWallet after
        # construction (per-slot user setting). Cap defensively to 100 in
        # case a future code path sets a larger value — at typical
        # ~5 KB per tx in txslight that's ~500 KB of JSON, still inside
        # the heap with margin.
        page_size = max(1, min(int(self.PAYMENTS_TO_SHOW or 6), 100))
        if self.mode == "xpub":
            url = "{}/api/v2/xpub/{}?details=txslight&tokens=derived&pageSize={}".format(
                self.blockbook_url, self.xpub, page_size)
        else:
            url = "{}/api/v2/address/{}?details=txslight&pageSize={}".format(
                self.blockbook_url, self.address, page_size)
        # Don't log the full URL: in xpub mode it contains the xpub
        # (would leak the entire derivation tree if logs are ever
        # shared); in address mode it contains the watched address
        # (single-address linkability). Both are PII for the user.
        print("OnchainWallet: fetching from {}".format(self.blockbook_url))
        # Pre-0.9.6 MicroPythonOS doesn't recognise the `redact_url=` kwarg
        # (added in MPOS#136) and raises
        # TypeError("unexpected keyword argument 'redact_url'") on every
        # call. Probe once and remember — `_redact_url_supported` is a
        # class-level attribute so the result is shared across instances
        # and survives the wallet-restart cycle in `went_online` /
        # slot-switch flows (the class object outlives any single wallet
        # instance). True/False after the first call; None means
        # "not probed yet".
        kwargs = {"headers": {"User-Agent": self._USER_AGENT}}
        if OnchainWallet._redact_url_supported is not False:
            kwargs["redact_url"] = True
        try:
            try:
                response_bytes = await DownloadManager.download_url(
                    url, **kwargs)
                # First successful call confirms the kwarg is accepted.
                OnchainWallet._redact_url_supported = True
            except TypeError as e:
                if "redact_url" not in str(e):
                    raise
                # Old MPOS — cache the verdict and retry without the kwarg.
                print("OnchainWallet: redact_url= unsupported (pre-0.9.6 MPOS), "
                      "falling back to plain download (xpub still hidden in "
                      "LP's own log lines; framework logs may show the URL)")
                OnchainWallet._redact_url_supported = False
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

        # Receive address — skip entirely if user has pinned one in
        # Settings (handle_new_static_receive_code dedups by string so the
        # settings-supplied value won't change).
        #
        # xpub mode → rotate through derived addresses:
        #   - On first poll, the wallet has no displayed address yet → pick one.
        #   - On subsequent polls, only rotate when Blockbook reports the
        #     currently-displayed address has received its first transfer.
        #     This avoids rotating the QR mid-scan when a payer is still
        #     looking at it.
        #
        # address mode → there's only one address; set it once on first poll.
        if self.mode == "xpub":
            tokens = response.get("tokens")
            if not self._displayed_receive_addr:
                picked = self._pick_unused_receive_address(tokens)
                if picked:
                    self._displayed_receive_addr = picked
                    self.handle_new_static_receive_code("bitcoin:" + picked)
            elif self._displayed_address_has_been_used(tokens, self._displayed_receive_addr):
                picked = self._pick_unused_receive_address(tokens)
                if picked and picked != self._displayed_receive_addr:
                    self._displayed_receive_addr = picked
                    self.handle_new_static_receive_code("bitcoin:" + picked)
        else:
            # Address mode — `self.address` IS the receive code. Set
            # once; subsequent polls are no-ops because the wallet's
            # dedup-by-string in handle_new_static_receive_code keeps
            # the same value from re-firing the UI.
            if not self._displayed_receive_addr:
                self._displayed_receive_addr = self.address
                self.handle_new_static_receive_code("bitcoin:" + self.address)

        # Heartbeat for the stale-data indicator — fires every successful
        # fetch even when nothing changed (a healthy quiet wallet would
        # otherwise look identical to an offline one).
        self.notify_poll_success()

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
