"""Format checks for wallet settings filled in by scanning a QR code.

MicroPythonOS calls a setting's `scan_check(text)` after a QR code is
scanned into a text setting and shows a warning below the field unless it
returns True. Each check accepts what the wallet can use for that field,
and warns on codes it would accept but that do the wrong job there: a
one-time payment request or an LNURL withdraw voucher shown as the piggy's
permanent receive code. When the scanned text is
recognisable as some other kind of code, the warning says what it looks
like, which is the usual case of scanning the wrong QR code.

Firmware without `scan_check` support ignores the key: no warning, no harm.
"""

from onchain_wallet import (
    classify_credential,
    _is_valid_bech32_address,
    _is_valid_base58check_address,
    _XPUB_PREFIXES,
)

_HEX = "0123456789abcdef"
_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_LUD16_NAME_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-_.+"
_DOMAIN_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789-."

_CHECK_HINT = "Check that you scanned the right QR code."
_SPACES_WARNING = ("This has spaces at the start or end, which the wallet can't use. "
                   "Remove them, or check that you scanned the right QR code.")


def _is_hex(s, length):
    return len(s) == length and all(c in _HEX for c in s.lower())


def _is_padded(text):
    return bool(text) and text != text.strip()


def _strip_lightning_scheme(s):
    if s.lower().startswith("lightning:"):
        return s[10:]
    return s


def _query_param(s, name):
    """Value of the first `name=` query parameter in a URI, or None."""
    if "?" not in s:
        return None
    prefix = name + "="
    for part in s.split("?", 1)[1].split("&"):
        if part.lower().startswith(prefix):
            return part[len(prefix):].replace("%40", "@").replace("%3A", ":").replace("%3a", ":")
    return None


def _is_bech32_shaped(s, hrp, min_len):
    """`s` starts with `hrp` + "1", is long enough, isn't mixed case and
    uses only bech32 characters. No checksum check."""
    low = s.lower()
    if not low.startswith(hrp + "1") or len(low) < min_len:
        return False
    if s != low and s != s.upper():
        return False  # bech32 forbids mixed case
    return all(c in _BECH32_CHARSET for c in low[len(hrp) + 1:])


def _is_lightning_address(s):
    """LUD-16 `name@domain.tld`."""
    if s.count("@") != 1:
        return False
    name, domain = s.lower().split("@")
    if not name or not domain or "." not in domain:
        return False
    if domain[0] in ".-" or domain[-1] in ".-" or ".." in domain:
        return False
    return (all(c in _LUD16_NAME_CHARS for c in name)
            and all(c in _DOMAIN_CHARS for c in domain))


def _lnurl_decoded_url(s):
    """The URL inside a bech32 `lnurl1...` code (checksum not verified), or
    "" if it can't be decoded."""
    low = s.lower()
    acc = 0
    bits = 0
    out = bytearray()
    for c in low[6:-6]:
        v = _BECH32_CHARSET.find(c)
        if v < 0:
            return ""
        acc = ((acc << 5) | v) & 0xFFF
        bits += 5
        if bits >= 8:
            bits -= 8
            out.append((acc >> bits) & 0xFF)
    try:
        return bytes(out).decode("utf-8").lower()
    except Exception:
        return ""


def _lnurl_kind(s):
    """"withdraw", "login" or "channel" for LNURL codes that don't receive
    payments, else None. Bech32 codes are told apart by markers in the URL
    they carry (LUD-03/04/07 tags, LNbits /withdraw/ paths)."""
    low = s.lower()
    if low.startswith("lnurlw://"):
        return "withdraw"
    if low.startswith("keyauth://"):
        return "login"
    if low.startswith("lnurlc://"):
        return "channel"
    if not low.startswith("lnurl1"):
        return None
    url = _lnurl_decoded_url(s)
    rest = url.split("://", 1)[-1]
    host_path, _, query = rest.partition("?")
    slash = host_path.find("/")
    path = host_path[slash:] if slash >= 0 else ""
    params = query.split("&") if query else []
    if "tag=withdrawrequest" in params:
        return "withdraw"
    if "tag=login" in params:
        return "login"
    if "tag=channelrequest" in params:
        return "channel"
    if "/.well-known/lnurlp/" in path:
        return None  # LUD-16 Lightning Address paths are always pay
    segments = path.split("/")
    if "withdraw" in segments or "lnurlw" in segments:
        return "withdraw"
    return None


_LNURL_KIND_NAMES = {
    "withdraw": "an LNURL withdraw link",
    "login": "an LNURL login code",
    "channel": "an LNURL channel request",
}


def _is_lnurl(s):
    """LNURL-pay: bech32 LNURL (`lnurl1...`) that isn't a withdraw, login or
    channel code, or a LUD-17 `lnurlp://` link."""
    low = s.lower()
    if low.startswith("lnurlp://"):
        return len(low) > 9 and "." in low[9:]
    return _is_bech32_shaped(s, "lnurl", 20) and _lnurl_kind(s) is None


def _is_bolt12_offer(s):
    return _is_bech32_shaped(s, "lno", 20)


def _is_silent_payment_address(s):
    """BIP-352 silent payment address (`sp1q...`, testnet `tsp1q...`): two
    33-byte keys make it at least 116 characters, which also tells it apart
    from shorter codes with the same `sp1` start, such as Spark addresses."""
    low = s.lower()
    if low.startswith("tsp1"):
        return _is_bech32_shaped(s, "tsp", 117)
    return _is_bech32_shaped(s, "sp", 116)


_BIP321_ADDRESS_PARAMS = ("bc", "tb", "bcrt")


def _bip321_query_address(s):
    """A segwit address carried in a BIP-321 `bc=` / `tb=` / `bcrt=` query
    parameter (used when the address part of the link is empty), or None."""
    for name in _BIP321_ADDRESS_PARAMS:
        value = _query_param(s, name)
        if value and _is_valid_bech32_address(value):
            return value
    return None


def _is_one_time_request(s):
    """A bitcoin: link with an amount or a one-time Lightning invoice in it,
    as a wallet's receive screen shows for a single payment."""
    if _query_param(s, "amount") is not None:
        return True
    payload = _query_param(s, "lightning")
    return bool(payload) and _strip_lightning_scheme(payload).lower().startswith(("lnbc", "lntb", "lnsb"))


def _is_static_lightning_code(s):
    """A reusable Lightning receive code: Lightning Address, LNURL-pay or
    BOLT12 offer, with or without `lightning:` in front."""
    inner = _strip_lightning_scheme(s)
    return _is_lightning_address(inner) or _is_lnurl(inner) or _is_bolt12_offer(inner)


def _is_web_url(s):
    low = s.lower()
    for scheme in ("https://", "http://"):
        if low.startswith(scheme):
            host = low[len(scheme):].split("/", 1)[0].split("?", 1)[0]
            return bool(host) and " " not in s and all(c in _DOMAIN_CHARS + ":[]" for c in host)
    return False


def _is_bitcoin_address(s):
    return _is_valid_bech32_address(s) or _is_valid_base58check_address(s)


def _bitcoin_uri_address(s):
    """The address in a `bitcoin:<address>?...` link ("" when the link has
    none), or None when `s` isn't a bitcoin: link."""
    if not s.lower().startswith("bitcoin:"):
        return None
    return s[8:].split("?", 1)[0]


def _embedded_xpub(s):
    """An xpub inside a wrapper such as `[fingerprint/84h/0h/0h]zpub...` or
    `wpkh(...)`, or None."""
    if "[" not in s and "(" not in s:
        return None
    for prefix in _XPUB_PREFIXES:
        if s.find(prefix) > 0:
            return prefix
    return None


def describe(text):
    """Return what kind of code `text` looks like, e.g. "a Bitcoin address",
    or None if it isn't one we recognise."""
    s = (text or "").strip()
    low = s.lower()
    if low.startswith(("nostr+walletconnect:", "nwc:")):
        return "a Nostr Wallet Connect link"
    inner = _strip_lightning_scheme(s)
    inner_low = inner.lower()
    if _is_lightning_address(inner):
        return "a Lightning Address"
    nostr = low[6:] if low.startswith("nostr:") else low
    if nostr.startswith(("npub1", "nsec1", "nprofile1")):
        return "a Nostr key"
    if nostr.startswith(("note1", "nevent1", "naddr1")):
        return "a Nostr post link"
    if low.startswith("nostr:"):
        return "a Nostr link"
    address = _bitcoin_uri_address(s)
    if address is not None and _is_one_time_request(s):
        return "a one-time payment request"
    if address:
        if _is_silent_payment_address(address):
            return "a silent payment address"
        return "a Bitcoin address"
    if address == "":
        if _bip321_query_address(s):
            return "a Bitcoin address"
        for name in ("lightning", "lno"):
            payload = _query_param(s, name)
            if payload and not payload.lower().startswith("bitcoin:"):
                return describe(payload)
        if _query_param(s, "sp"):
            return "a silent payment address"
        return None
    if _is_bitcoin_address(s):
        return "a Bitcoin address"
    if _is_silent_payment_address(s):
        return "a silent payment address"
    if s[:4] in _XPUB_PREFIXES:
        return "an xpub"
    if inner_low.startswith(("lnbc", "lntb", "lnsb")):
        return "a one-time Lightning invoice"
    if inner_low.startswith("lno1"):
        return "a BOLT12 offer"
    kind = _lnurl_kind(inner)
    if kind:
        return _LNURL_KIND_NAMES[kind]
    if inner_low.startswith(("lnurl1", "lnurlp://")):
        return "an LNURL"
    if low.startswith(("http://", "https://")):
        # LUD-01 fallback links carry the Lightning code in ?lightning=.
        payload = _query_param(s, "lightning")
        if payload and not payload.lower().startswith(("http://", "https://", "bitcoin:")):
            found = describe(payload)
            if found:
                return found
        return "a web address"
    if low.startswith(("ws://", "wss://")):
        return "a relay address"
    if _is_hex(s, 32):
        return "an LNbits key"
    if _is_hex(s, 64):
        return "a 64-character key"
    return None


def _warning(expected, text, same_kind=()):
    """Warning for `text` that isn't `expected`. `same_kind` lists the
    describe() results that are the right kind of code but malformed."""
    found = describe(text)
    if found and found in same_kind:
        return "This looks like %s, but part of it is missing or wrong. %s" % (found, _CHECK_HINT)
    if found:
        return "This QR code looks like %s, not %s. %s" % (found, expected, _CHECK_HINT)
    return "This doesn't look like %s. %s" % (expected, _CHECK_HINT)


def _server_url_check(expected, example):
    def check(text):
        if _is_padded(text):
            return _SPACES_WARNING
        s = text or ""
        if not _is_web_url(s):
            return _warning(expected, s, ("a web address",))
        if "?" in s or "#" in s:
            return ("This web address has extra parts after the server name. "
                    "Enter only the server address, like %s." % example)
        return True
    return check


check_lnbits_url = _server_url_check("an LNbits server address", "https://demo.lnbits.com")
check_blockbook_url = _server_url_check("a Blockbook server address", "https://btc1.trezor.io")


def check_lnbits_readkey(text):
    if _is_padded(text):
        return _SPACES_WARNING
    s = text or ""
    if _is_hex(s, 32):
        return True
    return _warning("an LNbits read key", s)


def check_lightning_address(text):
    s = (text or "").strip()
    if _is_static_lightning_code(s):
        return True
    if s.lower().startswith("bitcoin:") and _is_one_time_request(s):
        return ("This is a one-time payment request, with an amount or an "
                "invoice in it. Scan your Lightning Address or another "
                "reusable receive code instead.")
    # Unified QRs (bitcoin:...?lightning=LNURL...) and the LUD-01 https
    # fallback (https://...?lightning=LNURL...) carry the Lightning code in
    # a query parameter; the wallet shows them as they are.
    if s.lower().startswith(("bitcoin:", "http://", "https://")):
        for name in ("lightning", "lno"):
            payload = _query_param(s, name)
            if payload and _is_static_lightning_code(payload):
                return True
    return _warning("a Lightning Address", s, ("a Lightning Address", "an LNURL", "a BOLT12 offer"))


def check_nwc_url(text):
    if _is_padded(text):
        return _SPACES_WARNING
    s = text or ""
    from nwc_wallet import NWCWallet
    try:
        # parse_nwc_url ignores `self`; the wallet runs this same parser.
        NWCWallet.parse_nwc_url(None, s)
        return True
    except Exception:
        return _warning("a Nostr Wallet Connect link", s, ("a Nostr Wallet Connect link",))


def check_xpub_or_address(text):
    s = (text or "").strip()
    try:
        classify_credential(s)
        return True
    except ValueError:
        pass
    address = _bitcoin_uri_address(s)
    if address and _is_bitcoin_address(address):
        return ('This is a "bitcoin:" payment link. Enter just the address, '
                'without "bitcoin:" at the start or anything after a "?".')
    if address == "" and _bip321_query_address(s):
        return ('This is a "bitcoin:" payment link. Enter just the address, '
                'the part that starts with %s.' % _bip321_query_address(s)[:4])
    prefix = _embedded_xpub(s)
    if prefix:
        return ("This has extra text around the key. Enter just the part "
                "that starts with %s." % prefix)
    return _warning("an xpub or Bitcoin address", s, ("an xpub", "a Bitcoin address"))


def check_bitcoin_address(text):
    s = (text or "").strip()
    address = _bitcoin_uri_address(s)
    target = s if address is None else address
    if address is not None and _is_one_time_request(s):
        return ("This is a one-time payment request, with an amount or an "
                "invoice in it. Scan your wallet's plain receive address instead.")
    if _is_bitcoin_address(target) or _is_silent_payment_address(target):
        return True
    if address == "":
        # BIP-321 links with no on-chain address, e.g. bitcoin:?sp=sp1...
        # or bitcoin:?lno=lno1..., which the wallet shows as they are.
        if _bip321_query_address(s):
            return True
        sp = _query_param(s, "sp")
        if sp and _is_silent_payment_address(sp):
            return True
        for name in ("lno", "lightning"):
            payload = _query_param(s, name)
            if payload and _is_static_lightning_code(payload):
                return True
    return _warning("a Bitcoin address", s, ("a Bitcoin address", "a silent payment address"))

# Wallet setting keys (without the slot suffix) and their checks.
SCAN_CHECKS = {
    "lnbits_url": check_lnbits_url,
    "lnbits_readkey": check_lnbits_readkey,
    "lnbits_static_receive_code": check_lightning_address,
    "nwc_url": check_nwc_url,
    "nwc_static_receive_code": check_lightning_address,
    "onchain_xpub": check_xpub_or_address,
    "onchain_blockbook_url": check_blockbook_url,
    "onchain_static_receive_code": check_bitcoin_address,
}


def add_scan_checks(settings, suffix=""):
    """Give each wallet setting in `settings` its `scan_check`. `suffix` is
    the wallet slot suffix on the setting keys."""
    for setting in settings:
        key = setting.get("key", "")
        if suffix:
            if not key.endswith(suffix):
                continue
            key = key[:-len(suffix)]
        check = SCAN_CHECKS.get(key)
        if check:
            setting["scan_check"] = check
