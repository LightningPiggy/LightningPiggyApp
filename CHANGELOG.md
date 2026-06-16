0.5.2
=====
- Rename the "Lightning Piggy FF2K" hero option to "Fart Face 2000 (FF2K)" so the FF2K abbreviation is spelled out in the Settings → Customise → Hero Image picker. Label only — the stored value (`lightningpiggy_ff2k`) and the `hero_lightningpiggy_ff2k.png` asset are unchanged, so existing selections keep working
- Default "Transactions Shown" is now 21 (was 6) — a fresh install / unset slot shows a full screen of transactions out of the box. Applies to all wallet types (LNBits `limit=`, NWC `list_transactions`, on-chain `pageSize=`). Users who already set the slider keep their value; anyone who wants a shorter list can still dial it down to 1..21
- Adding a wallet now opens the device into it: when you configure a slot that had no wallet yet (e.g. adding the on-chain wallet in slot 2), it becomes the active wallet so the home screen shows the wallet you just added instead of staying on the previous one. Merely editing an already-configured wallet does not change the active slot
- Fix the balance number rendering behind the ⚡/chain-link wallet-type logo when it's long enough to overlap it (millions of sats, or wide denominations like the ₿ prefix / milli-BTC): the balance text now draws in front of the logo so it stays readable

0.5.1
=====
- Optimize PNG image sizes using optipng and zopflipng
- NWC wallets now honour the per-slot "Transactions Shown" slider — the NIP-47 `list_transactions` request previously hardcoded `limit: 6` while LNBits (`limit=`) and on-chain (`pageSize=`) already followed the setting
- NWC: outgoing payments now render as negative amounts in the transactions list (NIP-47 amounts are unsigned with a separate `type` field; previously a send showed up looking like a receive), and an outgoing payment notification updates the balance + list immediately instead of waiting for the next poll
- Fix LNBits websocket notifications being silently dropped when the message lacks `wallet_balance` (unbound-variable error swallowed by the catch-all), and fix the accompanying log line printing a literal `{e}`
- Fix LNBits `extra.comment` list handling: LNBits 0.x returns a list which previously rendered as a Python list literal (e.g. `['yes']`); also stop an `extra` dict without a comment from wiping the payment's memo
- Fix Nostr relay-manager late-configuration path adding each character of the relay URL as a separate relay, and reconfiguring NWC with the same URL after a service restart leaving the manager permanently dead (early-return skipped the main-task respawn)
- Transactions list memory is now bounded: the in-RAM payment list (fed by websocket pushes and NWC notifications for as long as the app runs) caps at 50 entries, trimming the oldest — display max is 21 so the cap is invisible, but a busy wallet no longer grows ESP32 RAM and cache-file size without limit
- Reduce ESP32 flash wear ~10×: cache writes that only refresh the staleness timestamp (one per successful poll, every 60-300 s) are rate-limited to one per 15 minutes; data writes (balance / payments / receive code changes) are never skipped. The live stale indicator runs off RAM and is unaffected; only the across-restart seed gets ±15 min granularity
- Internal robustness: `str(wallet)` no longer raises (returns the wallet-type name; previously referenced un-imported classes), comparing a payment list against `None` no longer raises TypeError
- Synchronize confetti.py with MicroPythonOS' copy
- BOOT button: re-attach the GPIO0 watcher on onResume
- NostrService: don't use permissive ensure_lightning_prefix, only allow LUD-16
- Test coverage: 56 new unit tests for the display-critical paths — NWC URL parsing (both parser copies verified in lockstep), the balance state machine, live NIP-47 payment notifications (incoming/outgoing/msat rounding), receive-code `lightning:` prefixing, emoji surrogate-pair decoding, zap/LNURLp comment parsing, and the BOOT-button watcher lifecycle

0.5.0
=====
- Add on-chain wallet type: watch a Bitcoin xpub / ypub / zpub by polling a Blockbook indexer (Trezor's open-source explorer, https://github.com/trezor/blockbook). Server-side derivation means no BIP32 lib on the device. Defaults to Trezor's hosted instance at `btc1.trezor.io`; configurable to a self-hosted Blockbook (Umbrel / Start9 / BTCPay Server / Sparrow Server) for full privacy via the Settings → Wallet → Blockbook URL field
- On-chain wallet also accepts a single Bitcoin address as an alternative to an xpub — paste a P2PKH (`1…` / `m…` / `n…`), P2SH (`3…` / `2…`), SegWit (`bc1q…` / `tb1q…`), or Taproot (`bc1p…` / `tb1p…`) address into the same "xpub or Bitcoin Address" field. Picks the mode automatically. Address mode hits Blockbook's `/api/v2/address/{addr}` endpoint instead of the xpub one — same balance / transactions / self-transfer detection — and the receive QR is the watched address itself (no rotation, since there's no derivation tree). Full base58check + bech32 / bech32m checksum validation is done locally at wallet construction time so invalid addresses are rejected with a clear "credential must be xpub/ypub/zpub or a valid Bitcoin address" error before any network call. Useful when you only have a single watch-only address (e.g. shared deposit address, or a derived address from a wallet that doesn't expose xpub)
- On-chain Blockbook fetches now pass `pageSize=<Transactions Shown>` and use `details=txslight` so the response contains only the transactions the user actually wants displayed, and each transaction omits per-tx data the parser doesn't use (hex, scripts). Without the pageSize cap, Blockbook defaults to 1000 txs per page; on addresses with many txs (the genesis address, big mining-payout clusters, etc.) the JSON response + the subsequent slot-cache write blew the ESP32-S3 heap with `MemoryError: memory allocation failed`. Now bounded by the per-slot Transactions Shown setting (1..21), and the `txslight` switch trims another ~43 % off each tx (~177 KB → ~101 KB measured for a 21-tx page) — together a 5000-tx address downloads roughly 100× less data than before and the cache fits comfortably in heap
- Receive QR auto-rotates to a fresh unused address after the displayed one has received a payment — preserves Bitcoin's "one address per receive" privacy convention. Avoids rotating mid-scan: the QR only changes after Blockbook reports the currently-displayed address has a transfer, not on every poll
- Transactions list shows `"<amount> sats: Apr 16 confirmed"` / `"... pending"`; self-transfers (where every input AND every output belongs to the xpub) render as `"-<fee> sats: Apr 16 self-transfer"` so on-chain hopping looks like a fee-only loss instead of a misleading large net send
- Poll cadence: 60 s while any tx is unconfirmed, 300 s when everything's confirmed — fast feedback during a receive without hammering the indexer the rest of the time
- xpub is never written to logs or surfaced in error messages — leaking the xpub exposes the entire past + future derivation tree to anyone who reads it. The Blockbook URL passed to `DownloadManager.download_url` uses `redact_url=True` (MicroPythonOS 0.9.6+) so the framework also scrubs the xpub from its own request/response/exception log lines
- Privacy note: any external indexer (mempool.space, Esplora, Blockbook, an Electrum server) learns your addresses and can link them. Doesn't affect custody — Lightning Piggy holds no keys — but does affect chain confidentiality. Point the Blockbook URL setting at your own node to eliminate it
- Multi-wallet: configure up to two wallets side-by-side and switch between them with one tap. Mix-and-match — LNBits + on-chain, NWC + on-chain, two LNBits, two NWCs, etc. Settings shows "Add wallet" when only one is configured and turns into "Switch to <type>" once both slots are populated
- Per-wallet customisation: hero image (Piggy / Penguin / None) and balance denomination (sats / ₿ / bits / micro-BTC / milli-BTC / BTC) are stored per-slot, so each wallet remembers its own display preferences across switches
- Wallet-type indicator next to the balance: yellow ⚡ for Lightning (LNBits, NWC), pink chain-link for on-chain. Visible only for the active slot's type
- Per-slot wallet cache: each (wallet type, slot) pair retains its own cached balance / transactions / receive QR across reboots and slot-switches. Switching the active slot paints the new slot's data from disk instantly while a fresh fetch is in flight (matches the existing instant-paint experience for single-wallet users from 0.4.0)
- ESP32 BOOT button (GPIO0) as a hardware wallet-switcher: short press flips the active wallet (when both slots are configured), long press (≥800 ms) opens Settings. No-op on desktop builds without GPIO. Means you can keep the device on a shelf and switch between your savings wallet and spending wallet without picking it up
- Fix: the "Optional LN Address" / "Optional Receive Address" override in Settings → Wallet now updates the on-screen receive QR immediately on save. Previously (and through 0.4.x) the new address was written to prefs correctly but the home-screen QR kept showing the old one until the app was fully closed and reopened — there was no `changed_callback` wired on the LN-address settings AND `_wallet_config_key()` didn't include the override. Now: editing the override fires `_on_static_receive_code_changed`, which re-reads the active slot's override from prefs, updates the running wallet's `static_receive_code`, and calls `redraw_static_receive_code_cb` directly — live update, no wallet restart, no socket churn. The active-slot override is also added to `_wallet_config_key()` as a defence-in-depth safety net so the bug can't recur via a code path that doesn't wire the callback. Covers LNBits, NWC, and on-chain wallet types across both slots
- Prefix `lightning:` URI scheme to Lightning Address / LNURL / BOLT11 receive QRs for broader scanner compatibility (≈90 % → ≈95 % of mobile Lightning wallets). New `ensure_lightning_prefix()` helper in `wallet.py` recognises lud16 (`user@host`), LNURL bech32 (`LNURL1…`), and BOLT11 (`lnbc…` / `lntb…`) and wraps with `lightning:`; idempotent on already-prefixed values (case-insensitive on the scheme), and a no-op for on-chain `bitcoin:…` URIs and `http(s):…` LNURL-fallback URLs so it can be applied uniformly without per-wallet-type guards. Applied at four sites — wallet construction in `went_online` (LNBits + NWC), `nwc_wallet.async_wallet_manager_task` when the lud16 from the NWC URL is delivered to the base wallet, `_on_static_receive_code_changed` when the user saves an Optional LN Address override, and — critically — `redraw_static_receive_code_cb` (the function that actually pushes the string into the QR widget reads the override straight from prefs, so wrapping at the input sites alone wouldn't reach the encoder)
- Multi-wallet shape locked to "Lightning + On-chain". Slot 1's Wallet Type radio is restricted to LNBits + Nostr Wallet Connect; slot 2's radio is restricted to On-chain (xpub). Eliminates the previous footgun where the user could end up with two Lightning wallets — which broke the "Switch to <other>" button (it derives its label from the other slot's wallet_type via `_friendly_wallet_type`, so two Lightning slots both produced "Switch to Lightning" regardless of which was active) and left them with no on-chain visibility. Slot 2 settings also pre-seed `wallet_type_2 = "onchain"` + `onchain_blockbook_url_2 = OnchainWallet.DEFAULT_BLOCKBOOK_URL` so the lone radio shows already-selected and the Blockbook field shows the Trezor default the first time you open it — paste an xpub and you're done. Critically, the pre-seeds do NOT count as "wallet configured": a new `_slot_has_credentials()` helper checks the actual mandatory credential (xpub for onchain, url+readkey for lnbits, nwc_url for nwc), so the main settings row stays "Add an on-chain wallet" until you've genuinely entered an xpub, and the active-slot fallback in `_active_slot_and_suffix()` also uses this stricter check to guard against half-set-up slots becoming active and crashing in `OnchainWallet(xpub="")`. "Add wallet" renamed to "Add an on-chain wallet" so the row says exactly what tapping it will set up. Multi-wallet is a new 0.5.0 feature so no migration is shipped — pre-existing dual-Lightning configs in interim builds can't reach end-users
- Add Lightning Piggy FF2K hero variant (post-apocalyptic gas-mask piggy). New `hero_lightningpiggy_ff2k.png` asset; appears between "Lightning Piggy" and "Lightning Penguin" in both the Settings → Customise → Hero Image radio and the tap-to-cycle order on the home screen. Tap-to-cycle is now 4-way: Piggy → Piggy FF2K → Penguin → none → loops
- Fix: hero image (Piggy / Penguin), wallet-type chain-link icon, and confetti graphics now render again on MicroPythonOS 0.10.0. The bundled `lodepng` decoder in MPOS 0.10.0 silently rejects 8-bit RGBA PNGs — `lv.image.set_src()` returns success, no error is printed, the image widget stays at 0×0 pixels and nothing draws. All `res/drawable-mdpi/*.png` and `res/mipmap-mdpi/*.png` artwork was re-encoded from RGBA truecolor (color type 6) to indexed-palette (color type 3) via Pillow's `Image.quantize(method=FASTOCTREE)`. Transparency is preserved through the indexed PNG's `tRNS` chunk; at the device's 80×100 mascot size the visual difference vs RGBA is invisible. Also added `lv.lodepng_init()` at LP startup as a belt-and-braces decoder init (no-op on builds where MPOS already initialised it), plus `scripts/check_png_format.py` (a pre-commit / CI validator that scans `res/` and fails the build on any RGBA PNG) and `docs/assets.md` (the canonical asset-format reference). The underlying MPOS decoder bug is tracked separately upstream
- Hidden easter egg: triple-tap the wallet-type indicator (the ⚡ bolt or the on-chain chain-link, within ~1.2 s) on the home screen to launch "Lightning Piggy Jump" — an endless-runner mini-game starring the Lightning Piggy. Tap to jump, hold DUCK to dodge the flying lightning bolts (rendered from the LP logo), hop over the shitcoins, and watch the moon drift across the day/night sky. The start screen has an Exit button back to the wallet; the high score is stored under the LP app's prefs. Implemented as a hidden second Activity (`assets/dino.py`, launched via `Intent`, deliberately not registered in the manifest so it never appears on the launcher). All art is derived from LightningPiggy's own source assets

0.4.4
=====
- Support emojis

0.4.3
=====
- Cleanup MANIFEST.JSON file

0.4.2
=====
- Remove unsupported lv.font_montserrat_40 (MicroPythonOS 0.9.6+)

0.4.1
=====
- Balance header split into two labels: a big number (`12,345`) in font_montserrat_24 plus a smaller unit suffix (`sats` / `bits` / `micro-BTC` / `milli-BTC` / `BTC`) in font_montserrat_16, sharing a baseline. The previous all-one-font rendering made long balance strings (millions of sats, or spelled-out denominations like "8.98765432 milli-BTC") overflow the available header area and visually collide with the wallet-type indicator icons (⚡ for Lightning, chain-link for on-chain) or push toward the QR. Shrinking just the unit suffix gives the number itself another ~40 px to grow into without changing its visual weight. The "₿ symbol" denomination is unchanged (the ₿ glyph is part of the big number, no separate unit suffix). Both labels remain clickable so tap-to-cycle-denomination keeps working from anywhere on the balance line
- Tap-to-cycle font on the transactions list: drop the two `lv.font_unscii_*` entries (`unscii_8` and `unscii_16`) from the cycle. These are ASCII-only bitmap fonts that don't include the ₿ glyph (U+20BF), so a transaction line like "₿1,234: comment" rendered with a missing/substituted glyph on those two stops in the rotation. Cycle is now five Montserrat sizes (10 → 16 → 24 → 28 → 40), all of which render ₿ correctly. Default boot-up font stays at montserrat_16 (cycle index shifted from 2 → 1 to compensate for the two removed entries)
- NWC wallet: detect and recover from a half-broken WebSocket to the Nostr relay. Symptom: the device sends NWC RPC requests to the relay (`publishing message to relays: ...` in logs every poll) but never receives any useful response back — the TCP socket is in a one-way state, most often triggered by transient packet loss on a weak WiFi signal. ESP32's kernel-level TCP timeout for this state takes minutes-to-hours to fire, leaving the wallet appearing alive (task still polling) but silently delivering no updates until the user manually restarts the app. The fix tracks consecutive poll cycles where the relay returns no useful response (a `result.balance` or `result.transactions` payload — historical events, decryption failures, push notifications without `result`, and other relay chatter explicitly don't count, otherwise the watchdog would be masked into never firing on half-broken sockets that still emit noise); after 3 silent cycles (6 minutes) the wallet closes + reopens + re-subscribes to the relay. Recovery is automatic and the stale-data dot self-clears once a useful response arrives over the new socket
- Refactor: NIP-47 subscription setup (`add_subscription` + REQUEST publish) factored out of `async_wallet_manager_task` into `_setup_subscription`, so it can be re-invoked after a watchdog reconnect
- Transaction amounts on the on-screen payments list now use the MicroPythonOS NumberFormat thousands separator, matching the balance label's style (e.g. balance "₿8,984" + transaction "₿8,984: Apr 9 confirmed" — previously the transaction showed bare "8984"). Honours the user's `number_format` preference (US comma_dot, European dot_comma, Swiss apos_dot, French space_comma, etc.). Falls back to bare `str()` on pre-0.9.1 firmware
- Rename the "₿ sats" denomination's internal value from the cryptic `"symbol"` to `"₿ symbol"` (matching the visible picker label) so the Customise → Balance Denomination row reads cleanly. Includes a one-shot migration in `DisplayWallet.onCreate`: anyone with the old `"symbol"` value in prefs is auto-converted to `"₿ symbol"` on next launch (idempotent — no-op on subsequent boots and for users who never used the symbol mode)
- Transactions area now scrolls in-place when it has more entries than fit on screen. Previously a long zap comment or a long list of payments dragged the WHOLE screen (balance + QR + hero + transactions) into scroll mode, which was disorienting. Now only the transactions list scrolls; the balance, QR, hero, and settings cog stay put. The scrollbar itself is hidden — the area is still scrollable via touch drag, the few pixels the AUTO scrollbar used to reserve are reclaimed for transaction text
- Auto-scroll the transactions area to the top on every new transaction. If the user had previously scrolled down to inspect older entries, the list animates back to the top when the wallet emits a new payment — same "look, something new arrived" cue as the confetti for balance changes. No-op when already at top
- Auto-scroll the transactions area to the top after 2 minutes of no screen contact. If the user scrolls down to inspect older transactions and then walks away, the device naturally re-presents the most recent transactions to the next person who looks. Tracks any touch on any interactive widget (LVGL 9 events don't bubble to ancestors by default, so the contact tracker is registered on each widget directly)
- Balance label tap target enlarged from 224×29 to 224×45 px — 55 % more area. Below the Material Design 48 px minimum but as large as fits without overlapping the transactions area. The visible text rendering is unchanged; only the (invisible) click region grew downward to the line under the balance. Fixes "tapping balance to cycle denomination is hard on hardware"

0.4.0
=====
- Per-wallet-type cache: balance, transactions, and receive QR paint instantly on app open / re-entry for each configured wallet (LNBits and NWC each get their own cached slot). Previously the cache was write-only and the screen started blank on every launch until the first network fetch landed
- Fingerprint-guarded cache invalidation: changing credential settings (LNBits URL / read key, NWC URL) wipes that slot's cached data so the next paint waits for fresh fetches. Changing just the optional LN-address override invalidates only the cached QR, keeping cached balance and transactions on-screen
- Stale-data indicator: a small dot appears beneath the mascot when the wallet has produced only errors for a sustained period. Two tiers — orange after 10 minutes of failures (data might be slightly behind) and red after 60 minutes (definitely old). Cleared automatically on the next successful refresh
- Cache file format bumped to v2; any existing v1 cache file is silently discarded on first launch

0.3.2
=====
- Fix payment list never refreshing on budgeted NWC connections (e.g. Primal/Spark, Alby with a spend budget). The NWC main loop only triggered `fetch_payments` when `handle_new_balance` saw the balance change — but on budgeted connections `get_balance` returns the connection's spend budget (locked at the value chosen during NWC setup), so the balance never moves and the transaction list was fetched only once on initial connect and then frozen forever. Now polls `list_transactions` every cycle alongside `fetch_balance`, so newly received payments appear within ≤120 s regardless of whether the displayed balance moves

0.3.1
=====
- Fix LNBits wallet silently dying after a single `fetch_static_receive_code` network error. The call sits in the main poll loop but was not guarded by a try/except like `fetch_balance` — any 5xx / timeout / DNS glitch tore the task out of its `while self.keep_running:` and no code restarted it, so the wallet appeared frozen until the user reopened the app. Now wraps the fetch the same way as the balance path, surfaces the error via `handle_error`, and continues on the next cycle

0.3.0
=====
- Light/Dark theme toggle in Customise settings — app-local override that doesn't touch the OS-level theme; other apps and the launcher keep the user's OS preference
- Dark mode uses pure black (#000) for the main display, settings screens, and the fullscreen QR view (previously a dark charcoal); keeps all surfaces consistent with the QR code backdrop
- Editing wallet config in Settings now actually switches the running wallet. Previous behaviour kept the old wallet polling silently; balance/transactions/QR on screen wouldn't match the edited credentials until an app restart
- Switching wallets no longer shows stale data for a few seconds — previously the old balance (re-animated for 15 s), old transactions (from cached previous-wallet data), and old QR code (widget not hidden on swap) would linger before the new wallet's fetch completed
- Switching wallets no longer exhausts the ESP32 TCP socket pool: `NWCWallet.stop()` and `LNBitsWallet.stop()` now eagerly close relay websockets / payment-notification websockets, and the new wallet's startup waits for the old one's sockets to release before opening its own (fixes "Could not connect to any Nostr Wallet Connect relays" on quick swaps)
- Scrub three more secret-leak paths: the `wallet config changed` log line (leaked URLs/secret/readkey during restarts) and three `RuntimeError` messages in `LNBitsWallet.fetch_*` methods (leaked the readkey to the on-screen error label when a fetch failed)
- Remove dead send_button code (pre-multi-wallet placeholder that never shipped) and its orphan tap handler
- Guard the payments_updated_cb callback against a missing assignment (consistency with the peer callbacks)
- Correct a misleading comment that claimed wallet callbacks run "on another thread" — they actually run on the same event loop as LVGL via TaskManager.create_task
- Security: scrub NWC URL, secret, and pubkey from debug logs. The Nostr Wallet Connect secret authorises spending; prior builds printed it to serial/REPL during `parse_nwc_url()`, so any shared debug output exposed wallet control. Redacted eight leak points (full URL, post-prefix URL, url-decoded URL, raw query string containing `secret=`, extracted secret, extracted pubkey, parsed-summary line, and RuntimeError message).
- Adapt to MicroPythonOS 0.9.3 changed fontname font_montserrat_28_compressed to font_montserrat_28

0.2.6
=====
- Use native ₿ font glyph for balance and transaction amounts (replaces PNG images)
- Restructure settings: Wallet, Customise (balance denomination + hero image), Screen Lock
- Screen Lock toggle prevents tapping balance, transactions, QR code, and hero image
- Tap balance to cycle through denominations (sats, ₿, bits, micro-BTC, milli-BTC, BTC)
- Tap hero image to cycle through characters (Lightning Piggy, Lightning Penguin, None)
- Screen Lock toggles inline on settings screen without opening a sub-screen

0.2.5
=====
- Add selectable hero image on main screen (Lightning Piggy, Lightning Penguin, or None)
- Smaller settings cog icon

0.2.4
=====
- Fix crash on boot: remove undefined _has_number_format references
- Preserve cached payments on screen when WiFi goes offline

0.2.3
=====
- Use NumberFormat framework for decimal and thousands separators
- Restructure settings, add balance denomination picker, theme-aware UI, wallet cache
- Fix light mode background to match QR code white

0.2.2
=====
- Welcome screen by @bitcoin3us
- Fix call balance callback on initial 0 balance (NWC) by @floydianslips

0.2.1
=====
- Close FullscreenQR when balance changes so the rolling balance animation and payments are visible
- Add support for Nostr zaps, properly decoding the zap content to show the text
- Speed up connection in case of bad Nostr Wallet Connect relays
- Fix "wallet_type" setting not showing up after having been selected
- Properly round balance to avoid too many decimals
- Give preference to "static receive code" (Lightning Address or LNURL) from settings before fetching from backend or from NWC URL
- Replace requests library with DownloadManager for HTTP requests in LNBitsWallet
- Increase quiet size around QR codes and increase QR code size

0.2.0
=====
- Animate balance updates, incrementing while the confetti animation is also running
- Improve text if payment doesn't include comment
- Increase balance unit modes from 2 to 5: add bits, micro-BTC and milli-BTC in addition to sats and BTC

0.1.3
=====
- Simplify code by using MicroPythonOS's new TaskManager API

0.1.2
=====
- Huge overhaul of camera and QR scanning capabilities
- Cleanup redundant keyboard handling code

0.1.1
=====
- Tweak font sizes for compatibility with MicroPythonOS 0.5.0

0.1.0
=====
- Wait for WiFi connection if not connected already
- Integrate MposKeyboard: bigger keys, bigger labels, better layout
- UI: fix on-screen keyboard button color in light mode
- Adapt to task_handler API change

0.0.17
======
- Camera for QR scanning: fix one-in-two "camera image stays blank" issue
- Payments list: click to change font (not persistent)

0.0.16
======
- Fix click on balance to switch currency denomination

0.0.15
======
- Replace confetti GIF with custom confetti animation to fix slowdown
- Make line under balance clickable for confetti animation
- Support multiple relays in Nostr Wallet Connect URL
- Rewrite LNBitsWallet, NWCWallet and Wallet classes for improved speed and stability
- NWCWallet: increase number of listed payments from 3 to 6
- NWCWallet: re-fetch balance balance every 60 seconds

0.0.14
======
- Fix 0 balance handling
- Improve NWC performance: much faster list_transactions

0.0.13
======
- Use update_ui_threadsafe_if_foreground()
- Improve QR scanning help text

0.0.12
======
- Improve non-touchscreen (keypad) usage for settings
- Don't update the UI after the user has closed the app
- Don't allow newlines in single-line fields

0.0.11
======
- Adapt for compatibility with LVGL 9.3.0 (be sure to update to MicroPythonOS 0.1.1)

0.0.10
======
- Fix Keypad handling (for devices without touchscreen)

0.0.9
=====
- Improve user feedback in case of 0 balance

0.0.8
=====
- Close fullscreen QR code with any click
- Fix fullscreen QR code window compatibility with MicroPythonOS 0.0.9
- Update balance, even if it's 0
- Improve user feedback in case of errors

0.0.7
=====
- Power off camera after closing to conserve power

0.0.6
=====
- Improve QR scanning behavior on larger displays
- Fix click on balance issue

0.0.5
=====
- Fix wallet type selection radio buttons

0.0.4
=====
- Fix Nostr Wallet Connect setting selection not being indicated if settings were empty
- Remove gold coins animation because it takes too much space (party confetti stays)

0.0.3
=====
- Add gold coins and party confetti animation when receiving sats 

0.0.2
=====
- Improve "Scan QR" button: make it big and add a tip
- Add "Optional LN Address" option for Nostr Wallet Connect because not all providers include lud16 tag
