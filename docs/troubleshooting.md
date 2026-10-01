# Troubleshooting

Problems that come up when setting up a Lightning Piggy. Most of these are
on the wallet-service side rather than in the piggy itself; the same answers
apply to the MicroPythonOS app and the classic ePaper firmware.

## LNbits: "Invalid URL for LNURL encoding: http://umbrel.local:3007/. Check proxy settings." (500)

**When:** creating a Pay Link in the LNbits `lnurlp` extension on an Umbrel (or
any node reached by a `.local` name or a LAN IP).

**Why:** a Pay Link is an LNURL, which is the link's full URL bech32-encoded.
The `lnurl` library LNbits uses refuses to encode a plain `http://` URL unless
the host is `localhost` or a `.onion` address. Umbrel serves LNbits as
`http://umbrel.local:3007/`, so the encoder rejects it and the extension
reports a 500. The "check proxy settings" hint is LNbits assuming it sits
behind an HTTPS reverse proxy it cannot see.

Even if the encoding succeeded, an LNURL pointing at `umbrel.local` only
resolves on your home network, so nobody outside could pay it. A Pay Link that
other people scan needs a publicly reachable HTTPS address.

**Fix, preferred:** give LNbits a public HTTPS address and use it for the
link.

1. Expose LNbits over HTTPS under a real hostname: a Cloudflare Tunnel,
   Tailscale Funnel, or a reverse proxy with a real certificate are the
   usual routes on Umbrel.
2. In the Pay Link form, set the **Domain** field to that hostname (e.g.
   `lnbits.example.com`). The extension then builds the LNURL as
   `https://<domain>/lnurlp/<id>` regardless of how you opened the dashboard.
3. Put the same address in LNbits' base URL setting (`LNBITS_BASEURL` in
   `.env`, or Admin UI, Server tab) so other extensions generate correct links
   too.

**Fix, Tor only:** Umbrel also exposes LNbits as a `.onion` address, and the
encoder allows `http://...onion` URLs. Open the dashboard via the Tor address
(or set the Domain field to the `.onion` host) and the link will encode.
Payers then need a Tor-capable wallet, which suits a small circle more than a
public piggy.

**What does not work:** keeping `umbrel.local` and changing proxy settings, or
using a LAN IP address; both still fail the http rule.

**Piggy side:** none of this needs any change on the device. Once the Pay Link
exists, the piggy only needs the LNbits URL (the same public HTTPS address)
and the wallet's invoice/read key.
