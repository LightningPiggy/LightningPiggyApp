# Lightning Piggy

MicroPythonOS display wallet: shows balance, transactions, a receive QR code,
and more. Supports LNBits, Nostr Wallet Connect, and on-chain (xpub via
Blockbook) wallet types. See https://www.LightningPiggy.com.

App package: `com.lightningpiggy.displaywallet/`.

## Docs

- [docs/appearance.md](docs/appearance.md) — theming / appearance.
- [docs/assets.md](docs/assets.md) — image/asset format rules (indexed-palette PNGs).
- [docs/dino-easter-egg.md](docs/dino-easter-egg.md) — **handover** for the
  hidden "Lightning Piggy Jump" mini-game (triple-tap the wallet-type indicator
  to launch it). Read this before touching `assets/dino.py`, the wallet-type
  indicator click handling in `assets/displaywallet.py`, or the game sprites —
  `dino.py` is a synced copy of the standalone `com.micropythonos.dinojump` app.
