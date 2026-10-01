# Troubleshooting

Problems that come up when setting up a Lightning Piggy. Most of these are
on the wallet-service side rather than in the piggy itself; the same answers
apply to the MicroPythonOS app and the classic ePaper firmware.

## LNbits: "Invalid URL for LNURL encoding: `http://umbrel.local:3007/`. Check proxy settings." (500)

**When:** creating a Pay Link in the LNbits "Pay Links" (`lnurlp`) extension on
an Umbrel (or any node reached by a `.local` name or a LAN IP).

**Why:** a Pay Link is your LNbits web address packaged so wallets can scan it
(an LNURL). The `lnurl` library LNbits uses refuses to package a plain
`http://` address unless the host is `localhost` or a `.onion` address. Umbrel
serves LNbits as `http://umbrel.local:3007/`, which is neither, so the
extension reports a 500. The "check proxy settings" hint means LNbits expects
an HTTPS reverse proxy in front of it. Keeping `umbrel.local` or a LAN IP
cannot give a usable link anyway: nobody outside your home network could reach
it.

**Fix, preferred:** give LNbits a public HTTPS address and use it for the link.

1. Expose LNbits over HTTPS under a real hostname: on Umbrel that usually means
   a Cloudflare Tunnel, a Tailscale Funnel, or a reverse proxy with a real
   certificate. This is the part that takes some setting up.
2. Create the Pay Link again and type just the hostname (for example
   `lnbits.example.com`, without `https://`) into the box after the @ sign on
   the Lightning Address row of the form. The box has no name of its own; its
   label shows your current host, such as `umbrel.local:3007`. The extension
   then builds the link as `https://<hostname>/lnurlp/<id>` regardless of how
   you opened the dashboard.
3. Optionally set LNbits' Base URL to the same address for consistency: open
   Settings in the left menu (admin account), choose Security, and under
   Server Management set "Base URL of the server" to
   `https://lnbits.example.com`.

**Fix, Tor only:** Umbrel also exposes LNbits as a `.onion` address, and the
library allows `http://...onion` links. Open the dashboard via the Tor address
(or type the `.onion` host into the same box) and the link will encode. Payers
then need a Tor-capable wallet, which suits a small circle more than a public
piggy.

**Piggy side:** you do not need to copy the Pay Link onto the piggy. It fetches
the link from LNbits by itself, so it only needs an LNbits URL it can reach and
the wallet's invoice/read key. If the piggy then reports connection errors,
see the website's Troubleshooting page under "Connection errors when fetching
balance".
