# Handover: "Lightning Piggy Jump" easter egg

A hidden endless-runner mini-game embedded in the Lightning Piggy display
wallet. This doc is the handover for whoever maintains the LP app next.

Status: implemented and on-device-verified end-to-end — triple-tap trigger,
launch, and live gameplay all confirmed on a Waveshare ESP32-S3 Touch LCD 2
from a clean boot.

---

## 1. What it is / how a user triggers it

On the home (wallet) screen, **triple-tap the wallet-type indicator** — the
yellow ⚡ bolt (Lightning slots) or the pink chain-link (on-chain slot), three
taps within ~1.2 s. That launches **Lightning Piggy Jump**:

- Tap anywhere = jump (also starts / restarts).
- Hold the **DUCK** button (bottom-right) = duck under flying bolts; tapping it
  mid-air fast-falls.
- **Exit** button (top-left, shown on the start and game-over screens) returns
  to the wallet.
- Obstacles: "shitcoins" (poop+coin) on the ground, lightning bolts flying at
  three heights (appear past score 250). Speed ramps up; day/night cycle every
  700 points; a full moon drifts across the sky; high score persists.

It is **hidden by design**: a second Activity launched via `Intent`, NOT listed
in `META-INF/MANIFEST.JSON`, so it never appears on the device launcher.

---

## 2. Files

### Added to `com.lightningpiggy.displaywallet/`
- `assets/dino.py` — the whole game (one ~520-line file, class `DinoJump(Activity)`).
- `res/drawable-mdpi/` — 13 sprites:
  `piggy_run1/run2/stand/dead/duck1/duck2.png`, `bolt.png`, `cloud.png`,
  `moon.png`, `ground.png`, `restart.png`, `poop_small.png`, `poop_big.png`.
  (No launcher icon — a hidden activity needs none.)

### Changed in `assets/displaywallet.py`
All in / around `class DisplayWallet`:
1. A class constant `EGG_EXT_CLICK = 12` (px the indicator's clickable area
   is extended on each side — see point 2).
2. `onCreate`, just after `self.prefs = ...`:
   ```python
   self._egg_count = 0
   self._egg_last = 0
   ```
3. Where `self.lightning_bolt` and `self.chain_link` are created (the
   wallet-type indicator), each got:
   ```python
   self.lightning_bolt.add_flag(lv.obj.FLAG.CLICKABLE)
   self.lightning_bolt.set_ext_click_area(self.EGG_EXT_CLICK)
   self.lightning_bolt.add_event_cb(self._egg_tap, lv.EVENT.CLICKED, None)
   ```
   (and the same three lines for `self.chain_link`).

   **The `move_background()` call each indicator used to have was REMOVED.**
   This is the key reliability fix: a backgrounded widget loses click
   hit-testing to whatever sits on top of it, so the neighbouring balance
   line / QR / payments widgets were swallowing ~5 of every 6 taps. The
   indicators are created *after* the balance line and QR, so simply NOT
   backgrounding them leaves them on top for both drawing and clicks. They
   still don't overlap realistic balance numbers (those end far left of
   x≈200), so there's no visual cost — this resolves the "deliberately
   avoided foreground" caveat that earlier versions of this doc flagged.
   `set_ext_click_area` then enlarges the ~15×29 px glyph into a comfortable
   touch target (kept at 12 px so it doesn't steal the QR's fullscreen-tap
   region on the left).
4. Two new methods appended to the class:
   ```python
   def _egg_tap(self, event):
       now = time.ticks_ms()
       if time.ticks_diff(now, self._egg_last) > 1200:
           self._egg_count = 0
       self._egg_last = now
       self._egg_count += 1
       if self._egg_count >= 3:
           self._egg_count = 0
           self._launch_easter_egg()

   def _launch_easter_egg(self):
       # Re-insert the app's assets dir on sys.path before the lazy import.
       # MPOS keeps assets/ on the path only DURING app load and removes it
       # afterwards, so a bare `from dino import` at click time raises
       # "no module named 'dino'".
       try:
           import sys
           pkg = getattr(self, "appFullName", None) or "com.lightningpiggy.displaywallet"
           asset_dir = "/apps/{}/assets".format(pkg)
           if asset_dir not in sys.path:
               sys.path.insert(0, asset_dir)
           from dino import DinoJump
           self.startActivity(Intent(activity_class=DinoJump))
       except Exception as e:
           print("easter egg launch failed:", e)
   ```
   (`Intent` and `time` are already imported by displaywallet.py.)

   ⚠️ The `sys.path` re-insert in `_launch_easter_egg` is essential: `dino`
   is imported lazily (so the ~20 KB module isn't loaded on every wallet
   start), but the lazy import runs at click time — long after MPOS dropped
   `assets/` from `sys.path` post-load. Without the re-insert the import
   fails silently into the `except` and the game never launches.

### Changed: `CHANGELOG.md`
One bullet added under the `0.5.0` section.

---

## 3. The key architecture trick — host-portable resource path

`dino.py` does NOT hardcode its package. In `onCreate`:
```python
self.res = "M:apps/" + self.appFullName + "/res/drawable-mdpi/"
```
All `set_src` calls use `self.res`, and prefs use `SharedPreferences(self.appFullName)`.

Why this works when launched from LP: `Activity.startActivity()` stamps
`intent.app_fullname = self.appFullName` (see
`internal_filesystem/lib/mpos/app/activity.py:35`) and the navigator assigns it
to the new activity. So the embedded game's `appFullName` becomes
`com.lightningpiggy.displaywallet` → sprites load from LP's own `res/` and the
high score (`hi_score` key) saves under LP's prefs. **No manifest entry needed.**

Consequence: the *same* `dino.py` runs unchanged both inside LP and as the
standalone app `com.micropythonos.dinojump` (see §5).

---

## 4. Asset provenance & how to regenerate sprites

All art derives from LightningPiggy's OWN source files — no third-party sprites:
- Player frames + (standalone) icon ← `Media - Characters/lightning-piggy.png`
- "Shitcoin" poop ← `Media - Characters/lightning-piggy-shitcoin.png`
- Lightning bolt ← the `fill="#FFDB00"` polygon in `Media - Logo/lightningpiggy-logo.svg`
- Moon / cloud / ground / restart ← generated procedurally (PIL / pixel art)

⚠️ The **generator scripts do NOT live in the LP repo.** They live in the
standalone app: `com.micropythonos.dinojump/tools/`
- `gen_piggy.py` — player frames, poop (shitcoin), and the logo bolt; also the
  standalone launcher icon. Background removal is an edge flood-fill.
- `gen_sprites.py` — cloud, ground, restart (ASCII pixel art) + `make_moon()`.

To regenerate: edit/run those tools in the standalone app, then **copy the
resulting PNGs into LP's `res/drawable-mdpi/`** (and `assets/dino.py` if changed).

⚠️ **Indexed-PNG rule** (MPOS lodepng): every sprite MUST be indexed-palette
(color type 3) with alpha via `tRNS`, or `set_src` silently yields a 0×0 widget
and nothing draws. Verify with `file foo.png` → must say `8-bit colormap`. The
generators already save this way (PIL `quantize(method=2/FASTOCTREE)` or mode-P).

---

## 5. Two copies of dino.py — keep in sync

`dino.py` exists in two places and they should stay identical:
- `com.micropythonos.dinojump/assets/dino.py` — the **canonical/standalone** app
  (this is where it's edited and where the `tools/` generators are).
- `com.lightningpiggy.displaywallet/assets/dino.py` — the embedded copy.

After editing the game, copy the file to the other location. Because the resource
path is `appFullName`-derived (§3), no per-copy edits are needed — it's a plain
file copy. The standalone app also still ships its own sprite set + launcher icon.

---

## 6. How to test

### Standalone game (fastest iteration)
Runs on desktop and device as `com.micropythonos.dinojump`.
Desktop: `timeout -s 9 30 ./scripts/run_desktop.sh com.micropythonos.dinojump`
(headless here — no window, but prints/tracebacks show on stdout).

### LP on desktop — blocked by a broken symlink (see §7)
`internal_filesystem/apps/com.lightningpiggy.displaywallet` is a symlink with
the wrong depth, so the desktop build can't find LP. To test LP locally,
temporarily repoint it then restore it exactly:
```sh
cd internal_filesystem/apps
ln -sfn "../../LightningPiggyApp/com.lightningpiggy.displaywallet/" com.lightningpiggy.displaywallet  # 2x ../, correct
# ... test ...
ln -sfn "../../../LightningPiggyApp/com.lightningpiggy.displaywallet/" com.lightningpiggy.displaywallet  # restore original (3x ../)
```

### On device
- Board: Waveshare ESP32-S3 Touch LCD 2, 320×240, `/dev/cu.usbmodem101`, MPOS 0.11.0.
- LP is really installed at `/apps/com.lightningpiggy.displaywallet/`. Push with
  `mpremote ... cp` (copy files individually; clear
  `assets/__pycache__/` after, then `machine.soft_reset()`).
- Verify a sprite decodes on hardware (the indexed-PNG gotcha): parent an
  `lv.image` to `lv.screen_active()` (NOT a fresh off-screen obj — images decode
  lazily on draw), pump `lv.timer_handler()` ~12×, read `get_width()/get_height()`;
  0×0 = decode failed.
- The triple-tap and visual gameplay need a human at the touchscreen — not
  automatable from here.

---

## 7. Known issues / caveats

1. **Trigger reliability — RESOLVED.** Originally the ⚡/chain indicator was
   `move_background()`'d, which lost click hit-testing to the balance line /
   QR / payments widgets on top of it — only ~1 of every 6 taps reached the
   indicator (measured on-device). Fixed by removing `move_background()` (the
   indicator is created after the balance line + QR, so it's naturally on top
   for clicks) and adding `set_ext_click_area(EGG_EXT_CLICK)` to enlarge the
   small glyph's touch target. The feared visual regression (icon over a long
   balance) doesn't occur in practice — realistic balances end far left of the
   indicator's x≈200 position. Triple-tap now registers reliably and was
   confirmed launching the game from a clean boot. See §2 point 3.
2. **Broken desktop symlink** (pre-existing, NOT introduced here):
   `internal_filesystem/apps/com.lightningpiggy.displaywallet` →
   `../../../LightningPiggyApp/...` (three `../`) resolves to
   `/Users/RT/LightningPiggyApp` (one level too high). Correct is `../../`. Left
   unchanged because it's a tracked file and the layout intent is unclear — but
   it blocks desktop testing of LP. Fix if appropriate.
3. **mpremote vs the running app.** While LP (or the game) is running its LVGL
   loop, mpremote often can't enter the raw REPL (`cp`/`exec` hang/EXIT=124).
   Reset or replug to recover.
4. **Browser WebSerial.** A browser tab (e.g. install.micropythonos.com in
   Brave) will grab `/dev/cu.usbmodem101` and block mpremote with "in use by
   another program". Close that tab.

---

## 8. dino.py internals cheat-sheet

- Loop: `lv.timer_create(self._tick, 20, None)` (~50 fps), created in
  `onResume`, deleted in `onPause`. Fixed-timestep with `time.ticks_diff`.
- States: `INTRO` / `RUNNING` / `GAMEOVER`.
- Input: full-screen transparent `jump_btn` behind the sprites (taps fall
  through to it since images aren't clickable); `duck_btn` and `exit_btn` on top.
- Sizes live in the `SIZ` dict; player sprite names in `CHAR_*` constants.
- Day/night recolour (`_apply_palette`) only touches ground/clouds/restart +
  background + score text. Piggy, poop, bolt, and moon are full-colour and
  excluded (`_all_images` list + `_apply_obstacle_recolor` sets recolour-opa
  TRANSP for obstacles).
- Obstacles pool of 4 reused `lv.image`s; `kind` is `"poop"` or `"bolt"`.
- Moon drifts at 1/4 cloud speed and wraps L→R; piggy has a ±2px running bob
  (visual only — not in the collision box).
