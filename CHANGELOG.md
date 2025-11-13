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
