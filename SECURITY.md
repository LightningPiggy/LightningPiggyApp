# Security Policy

## Reporting a vulnerability

Please report security issues privately by email to **oink@lightningpiggy.com**.
Do not open a public GitHub issue for anything you believe is a security
vulnerability.

Include what you can of the following:

- a description of the issue and its impact
- the app version (Settings shows it; also in `MANIFEST.JSON`) and the
  MicroPythonOS version and board it was observed on
- steps to reproduce, or a proof of concept
- whether the issue is already public

You will get an acknowledgement within 7 days. We will keep you informed of
progress and agree a disclosure date with you once a fix is available. Credit
is given in the release notes unless you prefer otherwise.

## Scope

This repository contains the Lightning Piggy app for MicroPythonOS. It is a
display-only wallet: it shows balances, transactions and receive codes from
an externally managed wallet (LNbits, Nostr Wallet Connect, or a watch-only
on-chain xpub/address). It holds no spending keys and cannot move funds.

In scope:

- handling of wallet credentials stored on the device (LNbits read keys, NWC
  connection strings, xpubs) and how they are displayed or logged
- network handling (LNbits, Nostr relays, Blockbook) including TLS use and
  input parsing of remote data
- anything that could make the display show incorrect balances or payments
- the app's use of MicroPythonOS APIs in a way that affects other apps or the
  device

Out of scope, but please report them to the right place:

- MicroPythonOS itself: https://github.com/MicroPythonOS/MicroPythonOS
- the original Arduino "Lightning Piggy Classic" firmware:
  https://github.com/LightningPiggy/lightning-piggy
- LNbits, Nostr relays, Blockbook or wallet services the app talks to

## Supported versions

Security fixes are made on the latest release published on the MicroPythonOS
AppStore and on GitHub Releases. Older releases are not maintained; please
update to the latest version.

## Practical notes for users

- An NWC connection string or LNbits read key lets its holder see your
  balance and transactions; treat them like passwords, and revoke them from
  your wallet service if a device is lost.
- Prefer read-only credentials (an LNbits invoice/read key, a read-only NWC
  connection) for a piggy that is on display.
