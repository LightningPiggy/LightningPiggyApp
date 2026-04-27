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
