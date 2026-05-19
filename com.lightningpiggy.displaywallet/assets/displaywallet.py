import time

import lvgl as lv

from mpos import Activity, Intent, ConnectivityManager, MposKeyboard, DisplayMetrics, SharedPreferences, SettingsActivity, TaskManager, WidgetAnimator

# TEMPORARY DIAGNOSTIC / UX FIX — the stock mpos SettingActivity.radio_event_handler
# lets a user click an already-selected radio button to UN-select it, saving an
# empty string (e.g. wallet_type=""). That breaks the invariant "exactly one
# wallet is always configured" — after save, the app falls back to the welcome
# screen even though the user just wanted to bounce off the settings page.
# Upstream MicroPythonOS fix is ready but not yet shipping in a firmware release;
# we patch Relay's class method at import time here so our app enforces the
# one-selection invariant locally. Remove once the upstream fix is in the
# frozen firmware.
try:
    import mpos.ui.setting_activity as _mpos_sa
    _orig_radio_event_handler = _mpos_sa.SettingActivity.radio_event_handler
    def _patched_radio_event_handler(self, event):
        target_obj = event.get_target_obj()
        target_obj_state = target_obj.get_state()
        checked = target_obj_state & lv.STATE.CHECKED
        current_checkbox_index = target_obj.get_index()
        if not checked and getattr(self, 'active_radio_index', -1) == current_checkbox_index:
            # User clicked the already-selected option — re-check it so
            # radio-group invariant (exactly one selected) holds.
            print("radio: ignoring un-check of active option (radios require exactly one)")
            target_obj.add_state(lv.STATE.CHECKED)
            return
        return _orig_radio_event_handler(self, event)
    _mpos_sa.SettingActivity.radio_event_handler = _patched_radio_event_handler
except Exception as _e:
    print("Failed to patch SettingActivity.radio_event_handler:", _e)
try:
    from mpos import NumberFormat
    _has_number_format = True
except ImportError:
    _has_number_format = False
from mpos import AppearanceManager

from confetti import Confetti
from fullscreen_qr import FullscreenQR
from payment import Payment
import wallet_cache

# Import wallet modules at the top so they're available when sys.path is restored
# This prevents ImportError when switching wallet types after the app has started
from lnbits_wallet import LNBitsWallet
from nwc_wallet import NWCWallet
from onchain_wallet import OnchainWallet


def _apply_screen_theme(screen):
    """Force an explicit screen bg that matches the app's main display colour —
    pure black in dark mode, pure white in light mode. Must set BOTH directions:
    once the explicit style is set it overrides LVGL's default-theme bg, so a
    dark→light toggle would leave a lingering black bg if we only set black."""
    if AppearanceManager.is_light_mode():
        screen.set_style_bg_color(lv.color_white(), lv.PART.MAIN)
    else:
        screen.set_style_bg_color(lv.color_black(), lv.PART.MAIN)


def _add_floating_back_button(screen, finish_callback):
    """Add a floating back-to-display button at bottom-right of a settings screen.
    Also tints the screen bg to match the active theme (pure black in dark mode,
    pure white in light mode) for consistency with the main wallet display."""
    _apply_screen_theme(screen)
    back_btn = lv.obj(screen)
    back_btn.set_size(50, 50)
    back_btn.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
    back_btn.add_flag(lv.obj.FLAG.CLICKABLE)
    back_btn.add_flag(lv.obj.FLAG.FLOATING)
    back_btn.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
    back_btn.set_style_border_width(0, lv.PART.MAIN)
    back_btn.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
    back_btn.add_event_cb(lambda e: finish_callback(), lv.EVENT.CLICKED, None)
    back_icon = lv.label(back_btn)
    back_icon.set_text(lv.SYMBOL.IMAGE)
    back_icon.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
    back_icon.center()
    focusgroup = lv.group_get_default()
    if focusgroup:
        focusgroup.add_obj(back_btn)


def _migrate_legacy_symbol_denom(prefs):
    """One-shot migration: legacy ``"symbol"`` pref value → ``"₿ symbol"``.

    The denomination value used to be the cryptic string ``"symbol"`` (label
    "₿ sats" in the picker). The Customise → Balance Denomination row
    displayed the raw stored value as its secondary text — "symbol" with
    no glyph and no clue what mode it referred to. Renaming the value to
    ``"₿ symbol"`` (matching the visible label) lets the placeholder read
    cleanly.

    This helper is idempotent: a no-op for users already on the new value,
    for users who never used the symbol mode, and on every boot after the
    first migration. Returns True iff something was migrated (for tests).

    Multi-wallet: also migrates `balance_denomination_2` for symmetry —
    slot 2 is a post-0.4.1 feature so its pref couldn't have come from the
    old picker, but covering both keys keeps the migration robust to any
    future code path that might propagate the legacy value into slot 2.
    """
    editor = prefs.edit()
    migrated = False
    for key in ("balance_denomination", "balance_denomination_2"):
        if prefs.get_string(key) == "symbol":
            editor.put_string(key, "₿ symbol")
            migrated = True
            print("displaywallet: migrated {} 'symbol' -> '₿ symbol'".format(key))
    if migrated:
        editor.commit()
    return migrated


def _slot_suffix(slot):
    """Suffix appended to per-slot pref keys: '' for slot 1 (preserves
    backward-compat with single-wallet builds — slot 1 keeps using
    `wallet_type`, `lnbits_url`, etc.) and '_2' for slot 2."""
    return "_2" if str(slot) == "2" else ""


def _resolve_denom_key(setting, default="balance_denomination"):
    """Pick the slot-aware balance-denomination pref key out of a setting
    dict. `CustomiseSettingsActivity` populates `setting["key"]` with the
    slot-aware key (`balance_denomination` for slot 1,
    `balance_denomination_2` for slot 2). `DenominationSettingsActivity`
    routes its read/write through this so it doesn't accidentally hardcode
    slot 1 — that bug (slot-2 saves landing in slot 1's key) shipped in
    an early multi-wallet draft and was caught on-device.

    Falls back to the unsuffixed key when no setting is passed (legacy
    callers / tests of bare instances)."""
    return (setting or {}).get("key") or default


def _should_show_wallet_setting(setting):
    """Conditionally show wallet-specific settings based on this slot's
    wallet_type. The slot comes from the setting dict (parent populates
    `_slot` when constructing a slot-specific WalletSettingsActivity)."""
    slot = setting.get("_slot", 1)
    suffix = _slot_suffix(slot)
    prefs = SharedPreferences("com.lightningpiggy.displaywallet")
    wallet_type = prefs.get_string("wallet_type" + suffix)
    # Strip the slot suffix from the key for prefix-matching against the
    # wallet-type branches (so `lnbits_url_2` still matches `lnbits_`).
    key = setting["key"]
    if suffix and key.endswith(suffix):
        key_base = key[:-len(suffix)]
    else:
        key_base = key
    if wallet_type != "lnbits" and key_base.startswith("lnbits_"):
        return False
    if wallet_type != "nwc" and key_base.startswith("nwc_"):
        return False
    if wallet_type != "onchain" and key_base.startswith("onchain_"):
        return False
    return True


class WalletSettingsActivity(SettingsActivity):
    """Sub-settings screen for wallet configuration. `_slot` in the parent's
    setting dict selects slot 1 (default, unsuffixed keys) or slot 2 (_2)."""
    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        parent_setting = extras.get("setting") or {}
        self.slot = parent_setting.get("_slot", 1)
        s = _slot_suffix(self.slot)
        # Optional callback passed from the parent settings dict. Used by the
        # three "Optional ... Address" overrides (LNBits / NWC / onchain) to
        # trigger an immediate QR redraw on save — without this the new value
        # is written to prefs but the home-screen QR keeps showing the old
        # one until the app is fully closed and reopened. Matches the pattern
        # CustomiseSettingsActivity uses for denomination + hero_image.
        callbacks = parent_setting.get("_callbacks") or {}
        static_cb = callbacks.get("static_receive_code")
        self.settings = [
            {"title": "Wallet Type", "key": "wallet_type" + s, "ui": "radiobuttons",
             "ui_options": [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc"), ("On-chain (xpub)", "onchain")],
             "_slot": self.slot},
            {"title": "LNBits URL", "key": "lnbits_url" + s,
             "placeholder": "https://demo.lnpiggy.com", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "LNBits Read Key", "key": "lnbits_readkey" + s,
             "placeholder": "fd92e3f8168ba314dc22e54182784045", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Optional LN Address", "key": "lnbits_static_receive_code" + s,
             "placeholder": "Will be fetched if empty.", "should_show": _should_show_wallet_setting, "_slot": self.slot,
             "changed_callback": static_cb},
            {"title": "Nostr Wallet Connect", "key": "nwc_url" + s,
             "placeholder": "nostr+walletconnect://69effe7b...", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Optional LN Address", "key": "nwc_static_receive_code" + s,
             "placeholder": "Optional if present in NWC URL.", "should_show": _should_show_wallet_setting, "_slot": self.slot,
             "changed_callback": static_cb},
            {"title": "xpub / ypub / zpub", "key": "onchain_xpub" + s,
             "placeholder": "zpub6rF...", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Blockbook URL", "key": "onchain_blockbook_url" + s,
             "placeholder": "https://btc1.trezor.io", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Optional Receive Address", "key": "onchain_static_receive_code" + s,
             "placeholder": "Auto-rotates if empty.", "should_show": _should_show_wallet_setting, "_slot": self.slot,
             "changed_callback": static_cb},
        ]
        screen = lv.obj()
        screen.set_style_pad_all(DisplayMetrics.pct_of_width(2), lv.PART.MAIN)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, lv.PART.MAIN)
        self.setContentView(screen)

    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)


class _AppThemeView:
    """Minimal prefs-like view for AppearanceManager.init() — lets us force
    theme_light_dark to a specific value while preserving the OS primary color,
    without touching OS prefs on disk. Only exposes get_string() because that's
    all AppearanceManager.init() reads."""
    def __init__(self, theme_light_dark, primary_color):
        self._data = {
            "theme_light_dark": theme_light_dark,
            "theme_primary_color": primary_color,
        }

    def get_string(self, key, default=None):
        return self._data.get(key, default)


def _apply_displaywallet_theme(app_prefs):
    """Apply the effective Light/Dark theme for displaywallet.

    If the app has a local `theme_override` pref ("light"/"dark"), that wins
    and is applied via a synthesised prefs view — OS prefs on disk are NEVER
    modified. Otherwise the OS setting is applied verbatim.
    """
    override = app_prefs.get_string("theme_override", "")
    os_prefs = SharedPreferences("com.micropythonos.settings")
    if override in ("light", "dark"):
        primary_color = os_prefs.get_string("theme_primary_color", AppearanceManager.DEFAULT_PRIMARY_COLOR)
        AppearanceManager.init(_AppThemeView(override, primary_color))
    else:
        AppearanceManager.init(os_prefs)


class CustomiseSettingsActivity(SettingsActivity):
    """Sub-settings screen for display customisation."""

    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        # Callbacks are passed via the setting dict from the parent
        setting = extras.get("setting") or {}
        callbacks = setting.get("_callbacks") or {}
        # Theme row shows the effective mode. If the app has a local override
        # set, use that; otherwise show whatever the OS theme resolves to.
        # (Using a literal map because MicroPython's str lacks .capitalize().)
        override = self.prefs.get_string("theme_override", "")
        theme_display = {"light": "Light", "dark": "Dark"}
        if override in theme_display:
            theme_label = theme_display[override]
        else:
            theme_label = "Light" if AppearanceManager.is_light_mode() else "Dark"
        # Hero image and balance denomination are per-wallet-slot so the user
        # can keep their savings wallet on "₿" + Penguin while spending wallet
        # is "sats" + Piggy without one overwriting the other.
        active_slot = self.prefs.get_string("active_wallet_slot", "1")
        s = _slot_suffix(active_slot)
        hero_key = "hero_image" + s
        denom_key = "balance_denomination" + s
        hero_options = [
            ("Lightning Piggy", "lightningpiggy"),
            ("Lightning Penguin", "lightningpenguin"),
            ("None", "none"),
        ]
        # MPOS 0.9.6+ renders the human-readable label from `ui_options` in
        # the settings row (both initial render and post-save), so the
        # earlier stopgap closure that hand-patched the value_label after
        # a save is no longer needed — the framework handles it.
        hero_setting = {
            "title": "Hero Image", "key": hero_key, "ui": "radiobuttons",
            "ui_options": hero_options,
            "default_value": "lightningpiggy",
            "changed_callback": callbacks.get("hero_image"),
        }
        self.settings = [
            {"title": "Balance Denomination", "key": denom_key, "ui": "activity",
             "activity_class": DenominationSettingsActivity,
             "placeholder": self.prefs.get_string(denom_key, "sats"),
             "changed_callback": callbacks.get("denomination")},
            hero_setting,
            {"title": "Theme", "key": "theme_override", "activity_class": True,
             "placeholder": theme_label},
        ]
        screen = lv.obj()
        screen.set_style_pad_all(DisplayMetrics.pct_of_width(2), lv.PART.MAIN)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, lv.PART.MAIN)
        self.setContentView(screen)

    def startSettingActivity(self, setting):
        """Inline toggle for Theme (Light ↔ Dark). Writes only to the app's own
        prefs — OS-level theme is never modified, so other apps keep the
        user's OS preference."""
        if setting.get("key") == "theme_override":
            # Determine current effective mode and flip it.
            current_override = self.prefs.get_string("theme_override", "")
            if current_override in ("light", "dark"):
                currently_light = (current_override == "light")
            else:
                currently_light = AppearanceManager.is_light_mode()
            new_value = "dark" if currently_light else "light"
            editor = self.prefs.edit()
            editor.put_string("theme_override", new_value)
            editor.commit()
            # Update the label synchronously FIRST, before the theme reinit has
            # any chance to disturb the widget state.
            value_label = setting.get("value_label")
            if value_label:
                value_label.set_text({"light": "Light", "dark": "Dark"}[new_value])
            # Defer theme reinit to the next LVGL tick so the current click
            # event finishes cleanly before LVGL re-themes everything. Calling
            # lv.theme_default_init() from inside an event handler causes the
            # setting row's click handlers to misbehave on subsequent taps.
            # Also re-tint the active screen's bg — the explicit style set by
            # _apply_screen_theme doesn't change automatically when the theme
            # reinits, so a dark→light flip would leave the old bg behind.
            prefs = self.prefs
            def _retheme(*args):
                _apply_displaywallet_theme(prefs)
                _apply_screen_theme(lv.screen_active())
            lv.async_call(_retheme, None)
        else:
            super().startSettingActivity(setting)

    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)


class MainSettingsActivity(SettingsActivity):
    """Settings screen with a back-to-display button."""
    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)

    def startSettingActivity(self, setting):
        """Override to handle inline-toggle settings (screen lock,
        switch-active-wallet)."""
        key = setting.get("key")
        if key == "screen_lock":
            current = self.prefs.get_string("screen_lock", "off")
            new_value = "on" if current == "off" else "off"
            editor = self.prefs.edit()
            editor.put_string("screen_lock", new_value)
            editor.commit()
            value_label = setting.get("value_label")
            if value_label:
                value_label.set_text("On - tapping disabled" if new_value == "on" else "Off - tapping changes display")
        elif key == "__switch_active_wallet":
            # Flip the active wallet slot and drop back to the main display so
            # the user sees the switch happen. The actual wallet swap is
            # handled in DisplayWallet.onResume (which detects the
            # (wallet_type, slot) change and restarts the wallet cleanly).
            current = self.prefs.get_string("active_wallet_slot", "1")
            new_value = "2" if current == "1" else "1"
            editor = self.prefs.edit()
            editor.put_string("active_wallet_slot", new_value)
            editor.commit()
            self.finish()
        else:
            super().startSettingActivity(setting)


class DenominationSettingsActivity(Activity):
    """Custom denomination picker with 2-column radio button layout."""
    DENOMINATIONS = [
        ("sats", "sats"),
        # Both label and stored value are "\u20bf symbol" \u2014 the previous "symbol"
        # internal value rendered cryptically in the Customise \u2192 Balance
        # Denomination placeholder (no glyph, no clue what it meant). Old
        # prefs with the legacy "symbol" value are auto-migrated in
        # DisplayWallet.onCreate.
        ("\u20bf symbol", "\u20bf symbol"),
        ("bits", "bits"),
        ("micro-BTC", "ubtc"),
        ("milli-BTC", "mbtc"),
        ("BTC", "btc"),
    ]

    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        self.setting = extras.get("setting")
        # Use the slot-aware key passed by CustomiseSettingsActivity
        # (e.g. "balance_denomination_2" for slot 2) — see _resolve_denom_key
        # for the contract.
        self._denom_key = _resolve_denom_key(self.setting)
        current = self.prefs.get_string(self._denom_key, "sats")

        screen = lv.obj()
        screen.set_style_pad_all(DisplayMetrics.pct_of_width(2), lv.PART.MAIN)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, lv.PART.MAIN)
        _apply_screen_theme(screen)

        title = lv.label(screen)
        title.set_text("Balance Denomination")
        title.set_style_text_font(lv.font_montserrat_16, lv.PART.MAIN)

        # 2-column grid for radio buttons
        grid = lv.obj(screen)
        grid.set_width(lv.pct(100))
        grid.set_height(lv.SIZE_CONTENT)
        grid.set_style_border_width(0, lv.PART.MAIN)
        grid.set_style_pad_all(0, lv.PART.MAIN)
        grid.set_flex_flow(lv.FLEX_FLOW.ROW_WRAP)

        self.active_index = -1
        self.checkboxes = []
        for i, (label_text, value) in enumerate(self.DENOMINATIONS):
            cb = lv.checkbox(grid)
            cb.set_text(label_text)
            cb.set_width(lv.pct(48))
            # Radio style (circular indicator)
            style_radio = lv.style_t()
            style_radio.init()
            style_radio.set_radius(lv.RADIUS_CIRCLE)
            cb.add_style(style_radio, lv.PART.INDICATOR)
            style_radio_chk = lv.style_t()
            style_radio_chk.init()
            style_radio_chk.set_bg_image_src(None)
            cb.add_style(style_radio_chk, lv.PART.INDICATOR | lv.STATE.CHECKED)
            cb.add_event_cb(lambda e, idx=i: self._radio_clicked(idx), lv.EVENT.VALUE_CHANGED, None)
            if current == value:
                cb.add_state(lv.STATE.CHECKED)
                self.active_index = i
            self.checkboxes.append(cb)

        # Save / Cancel buttons
        btn_cont = lv.obj(screen)
        btn_cont.set_width(lv.pct(100))
        btn_cont.set_style_border_width(0, lv.PART.MAIN)
        btn_cont.set_height(lv.SIZE_CONTENT)
        btn_cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        btn_cont.set_style_flex_main_place(lv.FLEX_ALIGN.SPACE_BETWEEN, lv.PART.MAIN)

        cancel_btn = lv.button(btn_cont)
        cancel_btn.set_size(lv.pct(45), lv.SIZE_CONTENT)
        cancel_btn.set_style_opa(lv.OPA._70, lv.PART.MAIN)
        cancel_label = lv.label(cancel_btn)
        cancel_label.set_text("Cancel")
        cancel_label.center()
        cancel_btn.add_event_cb(lambda e: self.finish(), lv.EVENT.CLICKED, None)

        save_btn = lv.button(btn_cont)
        save_btn.set_size(lv.pct(45), lv.SIZE_CONTENT)
        save_label = lv.label(save_btn)
        save_label.set_text("Save")
        save_label.center()
        save_btn.add_event_cb(lambda e: self._save(), lv.EVENT.CLICKED, None)

        # Register all interactive elements with focus group
        focusgroup = lv.group_get_default()
        if focusgroup:
            for cb in self.checkboxes:
                focusgroup.add_obj(cb)
            focusgroup.add_obj(cancel_btn)
            focusgroup.add_obj(save_btn)

        self.setContentView(screen)

    def _radio_clicked(self, clicked_index):
        if self.active_index >= 0 and self.active_index != clicked_index:
            self.checkboxes[self.active_index].remove_state(lv.STATE.CHECKED)
        self.active_index = clicked_index

    def _save(self):
        if self.active_index >= 0:
            new_value = self.DENOMINATIONS[self.active_index][1]
            old_value = self.prefs.get_string(self._denom_key)
            editor = self.prefs.edit()
            editor.put_string(self._denom_key, new_value)
            editor.commit()
            # Update the value label on the parent settings screen
            value_label = self.setting.get("value_label") if self.setting else None
            if value_label:
                value_label.set_text(new_value)
            self.finish()
            # Call changed_callback
            changed_callback = self.setting.get("changed_callback") if self.setting else None
            if changed_callback and old_value != new_value:
                changed_callback(new_value)
        else:
            self.finish()


class DisplayWallet(Activity):

    wallet = None
    receive_qr_data = None
    destination = None
    receive_qr_pct_of_display = 30 # could be a setting
    # balance denomination is now stored in prefs as "balance_denomination"
    # Default cycle position 1 → font_montserrat_16, matching the visible
    # font on first launch under the old (7-entry) cycle which defaulted
    # to position 2 → font_montserrat_16. Shifted down by one because
    # the two lv.font_unscii_* entries were removed (they're ASCII-only
    # and don't include the ₿ glyph U+20BF, so a transaction line like
    # "₿1,234: comment" rendered as "1,234: comment" with a missing
    # glyph or substituted box). Cycle now: 10 → 16 → 24 → 28 → 40.
    payments_label_current_font = 1
    try:
        # MicroPythonOS 0.9.3+
        payments_label_fonts = [ lv.font_montserrat_10, lv.font_montserrat_16, lv.font_montserrat_24, lv.font_montserrat_28]
    except Exception as e:
        # Fallback for users with MicroPythonOS < 0.9.3
        payments_label_fonts = [ lv.font_montserrat_10, lv.font_montserrat_16, lv.font_montserrat_24, lv.font_montserrat_28_compressed]

    # screens:
    main_screen = None

    # widgets
    balance_label = None
    receive_qr = None
    payments_label = None

    # welcome screen
    welcome_container = None
    wallet_container_widgets = []

    # splash screen
    splash_container = None
    splash_shown = False

    # confetti:
    confetti = None
    confetti_duration = 15000
    ASSET_PATH = "M:apps/com.lightningpiggy.displaywallet/res/drawable-mdpi/"
    ICON_PATH = "M:apps/com.lightningpiggy.displaywallet/res/mipmap-mdpi/"

    # Stale-data indicator — if the wallet has been producing only errors
    # (no successful balance/payments refresh) for this long, surface a
    # coloured dot under the mascot. Two tiers so the user can tell the
    # difference between "might be slightly behind" and "definitely old":
    #   WARN  (orange) after 10 minutes of error streak
    #   ERROR (red)    after 60 minutes of error streak
    # Thresholds are deliberately generous so transient blips (WiFi hiccup,
    # TLS retry, one failed poll) don't flash the indicator.
    STALE_WARN_THRESHOLD_S = 600   # 10 minutes → orange
    STALE_ERROR_THRESHOLD_S = 3600 # 60 minutes → red

    # Auto-scroll the payments area back to the top after this many ms of
    # no screen contact, so the device naturally re-presents the most
    # recent transactions to anyone who walks up after the previous user
    # scrolled down to inspect older entries.
    AUTO_SCROLL_PAYMENTS_INACTIVITY_MS = 120000   # 2 minutes

    # activities
    fullscreenqr = FullscreenQR() # need a reference to be able to finish() it

    def onCreate(self):
        self.prefs = SharedPreferences("com.lightningpiggy.displaywallet")
        # Run any required pref migrations before any code path reads
        # `balance_denomination` / `balance_denomination_2`. The helper
        # covers both slot keys (slot 2's pref couldn't have been the
        # legacy "symbol" value in practice, but the helper handles both
        # for symmetry).
        _migrate_legacy_symbol_denom(self.prefs)
        self.main_screen = lv.obj()
        # Disable scrolling on the screen itself — overflowing widgets are
        # supposed to scroll in-place (the payments_container below has its
        # own vertical scroll). Without this, a growing payments_label
        # used to drag the whole screen along with it.
        self.main_screen.set_scroll_dir(lv.DIR.NONE)
        self.main_screen.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        # Track the timestamp of the most recent screen contact (any touch
        # on any interactive widget). Drives the auto-scroll-to-top
        # behaviour for the payments area after AUTO_SCROLL_PAYMENTS_INACTIVITY_MS
        # of no user input. NB: in LVGL 9 events DON'T bubble to ancestors
        # by default — a PRESSED on a child widget never reaches the screen
        # unless we either set the EVENT_BUBBLE flag on the child OR
        # register a listener on the child directly. Going with direct
        # registration (in _install_contact_tracker) since it's robust
        # against any widget that lacks EVENT_BUBBLE.
        self._last_screen_contact_ms = None
        if not AppearanceManager.is_light_mode():
            self.main_screen.set_style_bg_color(lv.color_black(), lv.PART.MAIN)
        else:
            self.main_screen.set_style_bg_color(lv.color_white(), lv.PART.MAIN)
        self.main_screen.set_style_pad_all(0, lv.PART.MAIN)
        # This line needs to be drawn first, otherwise it's over the balance label and steals all the clicks!
        balance_line = lv.line(self.main_screen)
        balance_line.set_points([{'x':2,'y':35},{'x':DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.2),'y':35}],2)
        # Balance is split into two labels: a big number (this label) and a
        # smaller unit suffix ("sats" / "bits" / "micro-BTC" / etc.) just
        # to its right. Two reasons:
        #
        # 1. Header real-estate. With a single large font for the entire
        #    "12,345 sats" string, longer numbers (millions of sats, or
        #    spelled-out denominations like "milli-BTC") would push the
        #    text into the wallet-type indicator (⚡ / chain-link icon)
        #    or even into the QR area. Shrinking just the unit suffix
        #    gives the number itself another ~40 px to grow into.
        # 2. Visual hierarchy. The balance NUMBER is the headline; the
        #    unit is metadata. Typographically that's how it should look.
        #
        # Width: SIZE_CONTENT so the label hugs the text width — lets
        # the unit label position cleanly to the right via OUT_RIGHT_*.
        # Height: explicit 45 px keeps the tap target generous (iOS/Material
        # min ~44–48). The text renders top-left so the extra space below
        # is invisible empty padding that's still clickable.
        self.balance_label = lv.label(self.main_screen)
        self.balance_label.set_text("")
        self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
        self.balance_label.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        self.balance_label.set_size(lv.SIZE_CONTENT, 45)
        self.balance_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.balance_label.add_event_cb(self.balance_label_clicked_cb, lv.EVENT.CLICKED, None)
        # Smaller unit suffix. Font 16 vs the number's 24 — half-size-ish.
        # Both labels are 45 px tall and aligned via OUT_RIGHT_BOTTOM, which
        # in LVGL means "place outside-right of ref with widget BOTTOM
        # matching ref BOTTOM". Their text renders top-left inside the
        # 45-tall bounding box: the big balance text fills y=0..29, the
        # small unit text would fill y=0..19 if we did nothing. dy=10
        # shifts the unit label down 10 px so its text occupies y=10..29
        # — sharing a bottom edge with the balance text at y=29
        # (approximate typographic baseline alignment).
        self.balance_unit_label = lv.label(self.main_screen)
        self.balance_unit_label.set_text("")
        self.balance_unit_label.set_style_text_font(lv.font_montserrat_16, lv.PART.MAIN)
        self.balance_unit_label.set_height(45)
        self.balance_unit_label.align_to(self.balance_label, lv.ALIGN.OUT_RIGHT_BOTTOM, 2, 10)
        self.balance_unit_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.balance_unit_label.add_event_cb(self.balance_label_clicked_cb, lv.EVENT.CLICKED, None)
        self.receive_qr = lv.qrcode(self.main_screen)
        self.receive_qr.set_size(DisplayMetrics.pct_of_width(self.receive_qr_pct_of_display)) # bigger QR results in simpler code (less error correction?)
        dark, light = self._qr_colors()
        self.receive_qr.set_dark_color(dark)
        self.receive_qr.set_light_color(light)
        self.receive_qr.align(lv.ALIGN.TOP_RIGHT,0,0)
        self.receive_qr.set_style_border_color(light, lv.PART.MAIN)
        self.receive_qr.set_style_border_width(8, lv.PART.MAIN);
        self.receive_qr.add_flag(lv.obj.FLAG.CLICKABLE)
        self.receive_qr.add_event_cb(self.qr_clicked_cb,lv.EVENT.CLICKED,None)
        # Wallet-type indicator on the right side of the balance area, rendered
        # behind the balance text: yellow ⚡ for Lightning (LNBits, NWC),
        # pink chain link for on-chain. Exactly one is visible at a time;
        # _update_wallet_type_indicator() flips them based on active slot.
        # Sits behind the balance label so the split big-number + small-unit
        # typography (0.4.1) can flow over the indicator if the balance
        # string is long.
        self.lightning_bolt = lv.label(self.main_screen)
        self.lightning_bolt.set_text(lv.SYMBOL.CHARGE)
        self.lightning_bolt.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        self.lightning_bolt.set_style_text_color(lv.color_hex(0xFFD700), lv.PART.MAIN)
        self.lightning_bolt.align_to(self.receive_qr, lv.ALIGN.OUT_LEFT_TOP, -4, 4)
        self.lightning_bolt.move_background()
        self.lightning_bolt.add_flag(lv.obj.FLAG.HIDDEN)
        self.chain_link = lv.image(self.main_screen)
        self.chain_link.set_src(f"{self.ASSET_PATH}chain_link.png")
        self.chain_link.align_to(self.receive_qr, lv.ALIGN.OUT_LEFT_TOP, -4, 2)
        self.chain_link.move_background()
        self.chain_link.add_flag(lv.obj.FLAG.HIDDEN)
        # Payments live inside a fixed-height container that scrolls
        # vertically when the text overflows. Without this wrapper, a
        # long zap comment or many on-chain tx lines would push the
        # payments_label past the bottom of the screen and the whole
        # main_screen would gain a scrollbar — disorienting because
        # the balance + QR + hero would all scroll along with the
        # transactions list. With the wrapper, ONLY the transactions
        # area scrolls and the rest of the screen stays put.
        # Width is slightly narrower than 100% - QR (the *1.1) to leave
        # room for the wallet-type indicator icon that sits just left of
        # the QR; without that nudge the indicator would visually crowd
        # the right edge of long transaction lines.
        payments_container_width = DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.1)
        payments_container_height = DisplayMetrics.height() - 50
        self.payments_container = lv.obj(self.main_screen)
        self.payments_container.align_to(balance_line, lv.ALIGN.OUT_BOTTOM_LEFT, 2, 10)
        self.payments_container.set_size(payments_container_width, payments_container_height)
        self.payments_container.set_style_border_width(0, lv.PART.MAIN)
        self.payments_container.set_style_pad_all(0, lv.PART.MAIN)
        self.payments_container.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        # Vertical scroll only — horizontal would clash with the wrap.
        # SCROLLBAR_MODE.OFF hides the bar entirely (the container is still
        # scrollable via touch drag) so the few pixels the AUTO scrollbar
        # used to reserve on the right edge are reclaimed for transaction
        # text. The bar would also have been visually distracting on a
        # 320×240 display.
        self.payments_container.set_scroll_dir(lv.DIR.VER)
        self.payments_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.payments_label = lv.label(self.payments_container)
        self.payments_label.set_text("")
        # Label width follows its container (the 1.1× narrowing now
        # lives on the container; the label fills it).
        self.payments_label.set_width(lv.pct(100))
        self.update_payments_label_font()
        # Force word-wrap as a belt-and-braces against any line that does
        # exceed the label width (long zap comments, long Bitcoin tx labels
        # in future).
        self.payments_label.set_long_mode(lv.label.LONG_MODE.WRAP)
        self.payments_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.payments_label.add_event_cb(self.payments_label_clicked,lv.EVENT.CLICKED,None)
        # Hero image below QR code
        # Hero image area — container is always clickable, image inside may be hidden
        self.hero_container = lv.obj(self.main_screen)
        self.hero_container.set_size(80, 100)
        self.hero_container.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        self.hero_container.set_style_border_width(0, lv.PART.MAIN)
        self.hero_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.hero_container.add_flag(lv.obj.FLAG.CLICKABLE)
        self.hero_container.add_event_cb(self.hero_image_clicked_cb, lv.EVENT.CLICKED, None)
        self.hero_image = lv.image(self.hero_container)
        self.hero_image.center()
        self._update_hero_image()

        # Stale indicator — a small dot that appears beneath the mascot
        # when the wallet has been failing to refresh. Colour tiers the
        # severity: orange after STALE_WARN_THRESHOLD_S, red after
        # STALE_ERROR_THRESHOLD_S. Purely a visual cue that the
        # balance/payments currently showing may be out of date. Hidden
        # by default; toggled by _set_stale_indicator. Positioned relative
        # to the hero container in _update_hero_image so it follows the
        # mascot if the hero image is changed.
        # Parent the dot on main_screen. Earlier versions of this widget
        # were positioned on the mascot and needed lv.layer_top() to draw
        # over the hero image — but the current position (end of the
        # balance underline) is in a clear area, so parent-level z-order
        # suffices. Using main_screen also means the dot is automatically
        # hidden when another Activity (Settings, FullscreenQR) covers this
        # screen; lv.layer_top() is a global overlay that would leak the
        # dot onto those screens.
        self.stale_indicator_dot = lv.obj(self.main_screen)
        # 8-pixel diameter circle. lv.obj has non-zero default padding that
        # eats into the drawn area, so explicitly zero it out — without
        # `set_style_pad_all(0)` a 10x10 widget renders as a ~2-pixel sliver.
        self.stale_indicator_dot.set_size(8, 8)
        self.stale_indicator_dot.set_style_pad_all(0, lv.PART.MAIN)
        self.stale_indicator_dot.set_style_border_width(0, lv.PART.MAIN)
        # Explicit default colour so the widget isn't relying on a theme-
        # inherited bg (which can be transparent or match the screen bg and
        # render invisibly). `_set_stale_indicator` overrides this for the
        # warn/error tiers; this value is what would render if we ever un-
        # hid without setting a colour first.
        self.stale_indicator_dot.set_style_bg_color(lv.color_hex(0xDD2222), lv.PART.MAIN)
        self.stale_indicator_dot.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
        self.stale_indicator_dot.set_style_radius(lv.RADIUS_CIRCLE, lv.PART.MAIN)
        self.stale_indicator_dot.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        # Float the dot so it renders over whatever happens to be below it
        # in the stack (the mascot image, in particular). Without FLOATING
        # the dot's screen position can end up occluded by the hero image
        # or clipped by the screen edge on some displays.
        self.stale_indicator_dot.add_flag(lv.obj.FLAG.FLOATING)
        self.stale_indicator_dot.add_flag(lv.obj.FLAG.HIDDEN)
        # Dot position is a fixed offset (end of the balance underline),
        # not dependent on runtime layout — safe to compute and apply
        # immediately.
        self._reposition_stale_indicator()

        settings_button = lv.obj(self.main_screen)
        settings_button.set_size(40, 40)
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        settings_button.add_flag(lv.obj.FLAG.CLICKABLE)
        settings_button.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        settings_button.set_style_border_width(0, lv.PART.MAIN)
        settings_button.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        self.settings_icon = lv.label(settings_button)
        self.settings_icon.set_text(lv.SYMBOL.SETTINGS)
        self.settings_icon.set_style_text_font(lv.font_montserrat_18, lv.PART.MAIN)
        self.settings_icon.set_style_text_color(self._icon_color(), lv.PART.MAIN)
        self.settings_icon.center()
        focusgroup = lv.group_get_default()
        if focusgroup:
            focusgroup.add_obj(settings_button)

        # Track wallet-mode widgets so they can be hidden/shown as a group
        self.wallet_container_widgets = [balance_line, self.balance_label, self.balance_unit_label, self.receive_qr, self.lightning_bolt, self.chain_link, self.payments_container, self.hero_container, settings_button]
        # Install the screen-contact tracker on every interactive widget.
        # LVGL 9 doesn't bubble events to ancestors by default, so a single
        # listener on main_screen would miss touches that originate on
        # child widgets (the empirical observation: monitor showed
        # "no contact recorded" even after the user scrolled the payments
        # container twice). Registering on each widget directly is robust
        # against the lack of EVENT_BUBBLE.
        for _w in (self.main_screen, balance_line, self.balance_label, self.balance_unit_label,
                   self.receive_qr, self.lightning_bolt, self.chain_link,
                   self.payments_container, self.payments_label,
                   self.hero_container, self.hero_image, settings_button):
            try:
                _w.add_event_cb(self._on_screen_contact, lv.EVENT.PRESSED, None)
            except Exception as _e:
                print("Could not install contact tracker on widget: {}".format(_e))

        # === Welcome Screen (shown when wallet is not configured) ===
        self.welcome_container = lv.obj(self.main_screen)
        self.welcome_container.set_size(lv.pct(100), lv.pct(100))
        self.welcome_container.set_style_border_width(0, lv.PART.MAIN)
        self.welcome_container.set_style_pad_all(DisplayMetrics.pct_of_width(5), lv.PART.MAIN)
        self.welcome_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.welcome_container.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.welcome_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.welcome_container.add_flag(lv.obj.FLAG.HIDDEN)
        # Opaque welcome screen bg follows the theme (pure black in dark mode,
        # pure white in light) — otherwise LVGL's default dark-grey shows through.
        _apply_screen_theme(self.welcome_container)

        welcome_title = lv.label(self.welcome_container)
        welcome_title.set_text("Lightning Piggy")
        welcome_title.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        welcome_title.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)
        welcome_title.add_flag(lv.obj.FLAG.CLICKABLE)

        welcome_subtitle = lv.label(self.welcome_container)
        welcome_subtitle.set_text("An electronic piggy bank that accepts\nBitcoin sent over lightning")
        welcome_subtitle.set_style_text_font(lv.font_montserrat_12, lv.PART.MAIN)
        welcome_subtitle.set_style_text_color(lv.color_hex(0x888888), lv.PART.MAIN)
        welcome_subtitle.set_long_mode(lv.label.LONG_MODE.WRAP)
        welcome_subtitle.set_width(lv.pct(90))
        welcome_subtitle.set_style_text_align(lv.TEXT_ALIGN.CENTER, lv.PART.MAIN)
        welcome_subtitle.add_flag(lv.obj.FLAG.CLICKABLE)

        welcome_instructions = lv.label(self.welcome_container)
        welcome_instructions.set_text(
            "To get started you will first need to setup a "
            "bitcoin enabled wallet, and then connect to it "
            "in this app. Visit lightningpiggy.com/build/ "
            "for instructions."
        )
        welcome_instructions.set_style_text_font(lv.font_montserrat_12, lv.PART.MAIN)
        welcome_instructions.set_long_mode(lv.label.LONG_MODE.WRAP)
        welcome_instructions.set_width(lv.pct(90))
        welcome_instructions.set_style_text_align(lv.TEXT_ALIGN.CENTER, lv.PART.MAIN)
        welcome_instructions.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)
        welcome_instructions.add_flag(lv.obj.FLAG.CLICKABLE)

        welcome_qr_label = lv.label(self.welcome_container)
        welcome_qr_label.set_text("Scan for more info:")
        welcome_qr_label.set_style_text_font(lv.font_montserrat_10, lv.PART.MAIN)
        welcome_qr_label.set_style_text_color(lv.color_hex(0x888888), lv.PART.MAIN)
        welcome_qr_label.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)
        welcome_qr_label.add_flag(lv.obj.FLAG.CLICKABLE)

        welcome_qr = lv.qrcode(self.welcome_container)
        welcome_qr.set_size(round(DisplayMetrics.min_dimension() * 0.25))
        dark, light = self._qr_colors()
        welcome_qr.set_dark_color(dark)
        welcome_qr.set_light_color(light)
        welcome_qr.set_style_border_color(light, lv.PART.MAIN)
        welcome_qr.set_style_border_width(4, lv.PART.MAIN)
        welcome_url = "https://lightningpiggy.com/build"
        welcome_qr.update(welcome_url, len(welcome_url))
        welcome_qr.add_flag(lv.obj.FLAG.CLICKABLE)

        welcome_setup_btn = lv.button(self.welcome_container)
        welcome_setup_btn.set_size(lv.pct(60), lv.SIZE_CONTENT)
        welcome_setup_btn.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)
        welcome_setup_btn.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        welcome_setup_btn.set_style_border_width(1, lv.PART.MAIN)
        welcome_setup_btn.set_style_border_color(self._icon_color(), lv.PART.MAIN)
        welcome_setup_btn.add_event_cb(self.settings_button_tap, lv.EVENT.CLICKED, None)
        welcome_setup_label = lv.label(welcome_setup_btn)
        welcome_setup_label.set_text(lv.SYMBOL.SETTINGS + " Setup")
        welcome_setup_label.set_style_text_font(lv.font_montserrat_16, lv.PART.MAIN)
        welcome_setup_label.set_style_text_color(self._icon_color(), lv.PART.MAIN)
        welcome_setup_label.center()

        # === Splash Screen (logo shown for 2 seconds on first launch) ===
        self.splash_container = lv.obj(self.main_screen)
        self.splash_container.set_size(lv.pct(100), lv.pct(100))
        self.splash_container.set_style_border_width(0, lv.PART.MAIN)
        # Splash bg is opaque and follows the theme — pure black in dark mode,
        # pure white in light. Without this, LVGL's default dark-grey leaks
        # through on first boot before _apply_qr_theme has had a chance to run.
        self.splash_container.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
        _apply_screen_theme(self.splash_container)
        self.splash_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.splash_container.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.splash_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.splash_container.add_flag(lv.obj.FLAG.HIDDEN)

        splash_logo = lv.image(self.splash_container)
        splash_logo.set_src(f"{self.ICON_PATH}lightningpiggy-logo.png")
        # Scale logo to 80% of screen width (original is 467x190)
        splash_target_width = DisplayMetrics.pct_of_width(80)
        splash_scale = splash_target_width / 467
        splash_logo.set_scale(round(splash_scale * 256))
        splash_logo.set_size(round(467 * splash_scale), round(190 * splash_scale))

        self.setContentView(self.main_screen)

    def onStart(self, main_screen):
        self.main_ui_set_defaults()

        # Initialize Confetti
        self.confetti = Confetti(main_screen, self.ICON_PATH, self.ASSET_PATH, self.confetti_duration)

        # ESP32 BOOT button (GPIO0) — short press swaps active wallet, long
        # press opens Settings. No-op on the desktop build (no machine.Pin).
        self._start_boot_button_watcher()

        # Periodic stale-indicator check — runs every 60 s so the dot
        # appears even across periods with no wallet events (e.g. WiFi
        # offline with cached data on screen). Idempotent: fires
        # _refresh_stale_indicator which also runs on every success and
        # every error, so this is purely a safety net.
        self._stale_timer = lv.timer_create(self._stale_timer_tick, 60000, None)

    def onResume(self, main_screen):
        super().onResume(main_screen)
        # Ensure the app's effective theme (local override or OS) is applied.
        # This never writes to OS prefs — see _apply_displaywallet_theme.
        _apply_displaywallet_theme(self.prefs)
        # Detect wallet config change EARLY (before _apply_qr_theme and before
        # the else branch below) so we can wipe the display state before any
        # code path repaints the previous wallet's data onto the now-visible
        # screen. In particular: the 15-second balance WidgetAnimator started
        # by balance_updated_cb keeps calling display_balance on each tick —
        # without lv.anim_delete() the animator overwrites our SYMBOL.REFRESH
        # for up to 15 seconds, which is exactly the "old balance lingers for
        # seconds after wallet switch" symptom.
        config_changed_old_wallet = None
        if self.splash_shown and self.wallet and self.wallet.is_running():
            _current_key = self._wallet_config_key()
            if getattr(self, '_active_wallet_key', None) != _current_key:
                # Log only the wallet_type transition, NOT the full key tuples —
                # those contain URLs/readkeys/NWC secrets which would leak to
                # the serial console.
                _prev_type = (self._active_wallet_key[0]
                              if getattr(self, '_active_wallet_key', None) else None)
                _new_type = _current_key[0] if _current_key else None
                print("wallet config changed ({} -> {}) — restarting wallet".format(
                    _prev_type, _new_type))
                config_changed_old_wallet = self.wallet
                config_changed_old_wallet.stop()
                self.wallet = None
                self._active_wallet_key = None
                # Drop cached display state so _apply_qr_theme's tail (which
                # re-renders self._last_balance and QR data) is a no-op.
                if hasattr(self, '_last_balance'):
                    del self._last_balance
                self.receive_qr_data = None
                # Cancel any in-flight balance animation on balance_label —
                # otherwise WidgetAnimator.change_widget keeps ticking
                # display_balance for the remainder of its duration (15s by
                # default), continuously resetting the label to the PREVIOUS
                # wallet's balance and overwriting our SYMBOL.REFRESH below.
                lv.anim_delete(self.balance_label, None)
                self.balance_label.set_text(lv.SYMBOL.REFRESH)
                self.balance_unit_label.set_text("")
                self.payments_label.set_text("")
                # Hide the QR widget until the new wallet emits a static
                # receive code. redraw_static_receive_code_cb un-hides it
                # when it has fresh data to draw. show_wallet_screen()
                # below specifically skips un-hiding receive_qr when
                # self.receive_qr_data is empty, so this hide persists
                # across went_online → show_wallet_screen.
                self.receive_qr.add_flag(lv.obj.FLAG.HIDDEN)
                # Config-change restart implies the previous error streak
                # (if any) is no longer meaningful for the new wallet —
                # reset so the red dot doesn't persist past the swap.
                self._reset_stale_tracking()
        # Re-apply theme-dependent styles (screen bg, QR colors) right away —
        # onCreate set these based on is_light_mode at construction time, before
        # our app-local override had a chance to flip it. On first launch after
        # a theme override is active, the onCreate bg colour is wrong; this
        # corrects it before the splash even runs.
        self._apply_qr_theme()
        cm = ConnectivityManager.get()
        cm.register_callback(self.network_changed)
        if not self.splash_shown:
            # First launch: show splash for 2 seconds, then proceed
            self.splash_shown = True
            self.splash_container.remove_flag(lv.obj.FLAG.HIDDEN)
            lv.timer_create(self._splash_done, 2000, None).set_repeat_count(1)
        else:
            # Returning from settings or other activity
            self._update_hero_image()
            if config_changed_old_wallet is not None:
                # Starting the new wallet synchronously now would race against
                # the old wallet's async socket teardown — on ESP32 that
                # exhausts the TCP pool and the new connection fails. Defer
                # the restart until old_wallet.is_stopped() reports cleanup
                # is fully done.
                TaskManager.create_task(self._await_old_and_reconnect(config_changed_old_wallet))
                return
            if self.wallet and self.wallet.is_running():
                # Wallet already running — just redisplay, no re-fetch
                if hasattr(self, '_last_balance'):
                    self.display_balance(self._last_balance)
                if self.wallet.payment_list and len(self.wallet.payment_list) > 0:
                    self.payments_label.set_text(str(self.wallet.payment_list))
            else:
                # Wallet not running — reconnect
                self.network_changed(cm.is_online())

    async def _await_old_and_reconnect(self, old_wallet):
        """Poll the old wallet's is_stopped() flag, then start the new one.

        Keeps a cap on the wait so a stuck teardown (e.g. a relay that
        won't close cleanly) doesn't lock out a reconnect. 5s is enough
        for a clean NWC relay close (WebSocket CLOSE + TCP FIN handshake);
        past that we proceed and hope the sockets are released by the
        time the new wallet actually opens connections."""
        for _ in range(50):
            if old_wallet.is_stopped():
                break
            await TaskManager.sleep(0.1)
        else:
            print("WARN: old wallet didn't fully stop in 5s; reconnecting anyway")
        cm = ConnectivityManager.get()
        self.network_changed(cm.is_online())

    def _active_slot_and_suffix(self):
        """Return (slot_str, suffix) for the currently active wallet slot.
        Falls back to slot 1 if slot 2 is set active but unconfigured —
        e.g. user deleted slot 2's wallet_type without flipping the active
        slot back."""
        slot = self.prefs.get_string("active_wallet_slot", "1")
        if slot == "2" and not self.prefs.get_string("wallet_type_2"):
            print("Active slot 2 not configured, falling back to slot 1")
            editor = self.prefs.edit()
            editor.put_string("active_wallet_slot", "1")
            editor.commit()
            slot = "1"
        return slot, _slot_suffix(slot)

    def _wallet_config_key(self):
        """Tuple uniquely identifying the active wallet's config. Changes
        to any of these prefs invalidate the running wallet — onResume uses
        this to detect when the user changed settings (or flipped the active
        slot) and restart cleanly.

        The optional receive-address override IS included for each wallet
        type so that if the override is changed through a code path that
        doesn't fire `changed_callback` (programmatic prefs write, a
        settings migration, a future settings UI), onResume still catches
        the change and forces a wallet restart — pessimistic but always
        correct. For the common UI-edit case,
        `_on_static_receive_code_changed` already handles the redraw and
        bumps `_active_wallet_key` to the new tuple, so onResume sees no
        change and skips the wallet restart entirely. Result: live update
        via the callback (no socket churn) with the config-key check as a
        defence-in-depth safety net.

        Only the active slot's override is included — changes to the
        inactive slot's override shouldn't restart the running wallet.
        The inactive slot's override takes effect on next slot switch
        (which re-reads prefs in went_online)."""
        slot, s = self._active_slot_and_suffix()
        wt = self.prefs.get_string("wallet_type" + s)
        if wt == "lnbits":
            return (wt, slot,
                    self.prefs.get_string("lnbits_url" + s),
                    self.prefs.get_string("lnbits_readkey" + s),
                    self.prefs.get_string("lnbits_static_receive_code" + s))
        if wt == "nwc":
            return (wt, slot,
                    self.prefs.get_string("nwc_url" + s),
                    self.prefs.get_string("nwc_static_receive_code" + s))
        if wt == "onchain":
            # Pointing the same xpub at a different Blockbook is a real
            # config change — must trigger a wallet restart.
            return (wt, slot,
                    self.prefs.get_string("onchain_xpub" + s),
                    self.prefs.get_string("onchain_blockbook_url" + s),
                    self.prefs.get_string("onchain_static_receive_code" + s))
        return (wt, slot)

    def onPause(self, main_screen):
        leaving_app = self.destination not in (FullscreenQR, MainSettingsActivity)
        if self.wallet and leaving_app:
            self.wallet.stop() # don't stop the wallet for fullscreen QR or settings
        if leaving_app:
            # Restore the OS-level theme so the launcher and other apps see the
            # user's OS preference unmodified (our theme override only applies
            # while displaywallet is foregrounded).
            try:
                AppearanceManager.init(SharedPreferences("com.micropythonos.settings"))
            except Exception as e:
                print("displaywallet: failed to restore OS theme:", e)
        self.destination = None
        cm = ConnectivityManager.get()
        cm.unregister_callback(self.network_changed)

    def onDestroy(self, main_screen):
        # Stop the BOOT button watcher (its task checks
        # self._boot_button_keep_running every 50 ms, so this will exit on
        # the next tick — no hard kill needed).
        self._boot_button_keep_running = False
        # Stop the periodic stale-indicator timer so it doesn't fire on a
        # dead Activity instance.
        if getattr(self, '_stale_timer', None) is not None:
            try:
                self._stale_timer.delete()
            except Exception:
                pass
            self._stale_timer = None
        # would be good to cleanup lv.layer_top() of those confetti images

    # ---- ESP32 BOOT button (GPIO0) handling ----------------------------------

    _BOOT_LONG_PRESS_MS = 800
    _BOOT_DEBOUNCE_MS = 30

    def _start_boot_button_watcher(self):
        """Wire up GPIO0 (BOOT button) for short/long press detection. Silent
        no-op on desktop builds without machine.Pin."""
        try:
            from machine import Pin
        except ImportError:
            # Desktop build — no GPIO. Silently skip.
            self._boot_button_keep_running = False
            return
        try:
            self._boot_button_pin = Pin(0, Pin.IN, Pin.PULL_UP)
        except Exception as e:
            print("BOOT button: could not init GPIO0: {}".format(e))
            self._boot_button_keep_running = False
            return
        self._boot_button_keep_running = True
        TaskManager.create_task(self._boot_button_watcher_task())

    async def _boot_button_watcher_task(self):
        """Polling watcher with short/long press detection. Runs until onDestroy.

        Wrapped in try/except so any transient exception inside a press-handler
        (e.g. a prefs read failing during the first ~second of boot, an
        `lv.async_call` from a not-yet-attached widget, etc.) gets logged +
        skipped rather than silently killing the task. Earlier observation:
        on the very first cold boot the task occasionally showed up as
        `done:True` in `TaskManager.list_tasks()` with no visible error — most
        likely an unhandled exception in `_on_boot_button_*_press` firing
        during early startup. Hardening so even if the cause recurs the
        button keeps working.
        """
        pin = self._boot_button_pin
        debounce_s = self._BOOT_DEBOUNCE_MS / 1000
        while self._boot_button_keep_running:
            try:
                if pin.value() == 0:  # active LOW: pressed
                    await TaskManager.sleep(debounce_s)
                    if pin.value() != 0:
                        # bounce — released too fast
                        continue
                    t0 = time.ticks_ms()
                    # Wait for release
                    while pin.value() == 0 and self._boot_button_keep_running:
                        await TaskManager.sleep(0.02)
                    duration = time.ticks_diff(time.ticks_ms(), t0)
                    if duration >= self._BOOT_LONG_PRESS_MS:
                        self._on_boot_button_long_press()
                    else:
                        self._on_boot_button_short_press()
            except Exception as e:
                # Don't let one bad press tear out the whole watcher — log
                # and continue. The next iteration polls the pin again.
                print("BOOT watcher: caught exception, continuing: {}".format(e))
                import sys
                sys.print_exception(e)
            await TaskManager.sleep(0.05)
        # Helpful log if the loop ever exits cleanly (= onDestroy fired
        # or keep_running was flipped). Without this an unexpected exit
        # looked indistinguishable from a silent crash.
        print("BOOT watcher: loop exited (keep_running={})".format(
            self._boot_button_keep_running))

    def _on_boot_button_short_press(self):
        """Short press: switch active wallet, but only if a second wallet is configured."""
        if not self.prefs.get_string("wallet_type_2"):
            print("BOOT short press: no second wallet configured, ignoring")
            return
        current = self.prefs.get_string("active_wallet_slot", "1")
        new_value = "2" if current == "1" else "1"
        editor = self.prefs.edit()
        editor.put_string("active_wallet_slot", new_value)
        editor.commit()
        print("BOOT short press: switching active wallet {} -> {}".format(current, new_value))
        # UI work must run on the LVGL thread
        lv.async_call(self._restart_active_wallet, None)

    def _on_boot_button_long_press(self):
        """Long press: open Settings (same as tapping the cog)."""
        print("BOOT long press: opening Settings")
        lv.async_call(lambda *args: self.settings_button_tap(None), None)

    def _restart_active_wallet(self, *args):
        """Stop current wallet, repaint with the new slot's cached data,
        fire network_changed to start the new wallet. Mirrors the swap path
        in onResume — used when the swap is triggered from outside the
        Settings round-trip (e.g. by the BOOT button)."""
        if self.wallet:
            self.wallet.stop()
        self.wallet = None
        self._active_wallet_key = None
        if hasattr(self, '_last_balance'):
            del self._last_balance
        self.receive_qr_data = None
        # Cancel any in-flight balance animation so the OLD wallet's animator
        # doesn't keep ticking display_balance during the swap.
        lv.anim_delete(self.balance_label, None)
        self.balance_label.set_text(lv.SYMBOL.REFRESH)
        self.payments_label.set_text("")
        # Hide the previous wallet's QR until the new slot's static_receive_code
        # is loaded (from cache or fresh fetch).
        self.receive_qr.add_flag(lv.obj.FLAG.HIDDEN)
        # New slot might have a different hero image / wallet type icon —
        # repaint both via went_online (which calls _update_wallet_type_indicator).
        self._update_hero_image()
        cm = ConnectivityManager.get()
        self.network_changed(cm.is_online())

    def network_changed(self, online):
        print("displaywallet.py network_changed, now:", "ONLINE" if online else "OFFLINE")
        if online:
            self.went_online()
        else:
            self.went_offline()

    def _paint_from_cache(self, wallet_type, slot=None):
        """Paint balance, payments and QR from the on-disk cache slot for
        the given (`wallet_type`, `slot`) pair, if the cached fingerprints
        still match the current prefs. Returns True if anything was painted.

        `slot` defaults to whatever `_active_slot_and_suffix()` returns,
        so callers that don't care about cross-slot reads can omit it.

        Called from went_online() before wallet.start() so the UI shows
        the last-known data instantly while the network fetch is in
        flight. Any field whose fingerprint doesn't match comes back None
        and is left in its default (spinner / Connecting... text)."""
        if slot is None:
            slot, _ = self._active_slot_and_suffix()
        slot_key = wallet_cache.compute_slot_key(wallet_type, slot)
        creds_fp, qr_fp = wallet_cache.compute_fingerprints(wallet_type, self.prefs, slot=slot)
        cached = wallet_cache.load_slot(slot_key, creds_fp, qr_fp)
        painted_anything = False
        if cached["balance"] is not None:
            self.display_balance(cached["balance"])
            painted_anything = True
        if cached["payments"] is not None:
            self.payments_label.set_text(str(cached["payments"]))
            painted_anything = True
        if cached["static_receive_code"] is not None:
            self.receive_qr_data = cached["static_receive_code"]
            self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data))
            self.receive_qr.remove_flag(lv.obj.FLAG.HIDDEN)
            painted_anything = True
        if painted_anything:
            print("Cache: painted slot '{}' from disk".format(slot_key))
            # Seed the stale-tracking timer from the cache's last_updated so
            # the indicator reflects true age of the painted data, across
            # app restarts. If the slot is weeks old, the user sees an
            # orange/red dot the moment the app opens.
            #
            # Fallback: slots written by older builds (pre last_updated
            # support) don't have a timestamp. Treat those as "fresh right
            # now" so the dot doesn't appear immediately on cached data we
            # can't date — the next successful refresh will stamp a real
            # last_updated and future paints will use it.
            lu = cached.get("last_updated")
            if lu is None:
                lu = int(time.time())
                print("Cache: slot has no last_updated, seeding as now")
            self._last_success_ts = lu
            self._refresh_stale_indicator()
        return painted_anything

    # Colour palette for the stale indicator.
    _STALE_COLOR_WARN = 0xE69B1F   # amber / Bitcoin-orange
    _STALE_COLOR_ERROR = 0xDD2222  # red

    def _reposition_stale_indicator(self, timer=None):
        """Place the dot at the right end of the balance underline,
        centered vertically on it. That's the line drawn at y=35 from x=2
        to x=pct_of_width(100 - receive_qr_pct_of_display * 1.2), i.e. the
        visible separator under the balance text. Dot is 8x8 so we subtract
        half-size to centre it on the line endpoint."""
        if not hasattr(self, 'stale_indicator_dot'):
            return
        try:
            line_end_x = DisplayMetrics.pct_of_width(
                100 - self.receive_qr_pct_of_display * 1.2)
            line_y = 35
            dot_half = 4
            # Nudge 6px up from the line centre so the dot sits cleanly in
            # the gap above the line, not overlapping the stroke.
            self.stale_indicator_dot.set_pos(
                line_end_x - dot_half, line_y - dot_half - 6)
        except Exception as e:
            print("stale_indicator: reposition exception:", e)

    def _set_stale_indicator(self, level):
        """Toggle the stale-indicator dot beneath the mascot.

        `level` is one of:
            None / False / ''  — hide the dot
            'warn'             — show orange (>= 10 min since last update)
            'error'            — show red  (>= 60 min since last update)
        """
        if not hasattr(self, 'stale_indicator_dot'):
            return
        try:
            if level == 'error':
                self.stale_indicator_dot.set_style_bg_color(
                    lv.color_hex(self._STALE_COLOR_ERROR), lv.PART.MAIN)
                self.stale_indicator_dot.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
                self.stale_indicator_dot.remove_flag(lv.obj.FLAG.HIDDEN)
                self.stale_indicator_dot.move_foreground()
            elif level == 'warn':
                self.stale_indicator_dot.set_style_bg_color(
                    lv.color_hex(self._STALE_COLOR_WARN), lv.PART.MAIN)
                self.stale_indicator_dot.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
                self.stale_indicator_dot.remove_flag(lv.obj.FLAG.HIDDEN)
                self.stale_indicator_dot.move_foreground()
            else:
                self.stale_indicator_dot.add_flag(lv.obj.FLAG.HIDDEN)
        except Exception as e:
            print("stale_indicator: exception:", e)

    def _note_successful_update(self):
        """Called whenever a balance or payments refresh lands successfully
        (including after a paint-from-cache with a fresh `last_updated`).
        Bumps _last_success_ts and refreshes the indicator."""
        self._last_success_ts = time.time()
        self._refresh_stale_indicator()

    def _reset_stale_tracking(self):
        """Called on a fresh wallet construction. Treats the construction
        itself as a reset point; the indicator stays hidden until
        STALE_WARN_THRESHOLD_S has elapsed with no successful update."""
        self._note_successful_update()

    def _refresh_stale_indicator(self):
        """Compute stale tier from time-since-last-successful-update and
        paint the dot. Called on every success, every error, and from a
        periodic lv.timer so the dot appears even while the wallet is
        stopped (e.g. offline with cached data on screen)."""
        last = getattr(self, '_last_success_ts', None)
        if last is None:
            # Never had a successful update or a cache hit this session —
            # don't show the dot; the spinner/"Connecting..." messaging
            # is already communicating state.
            self._set_stale_indicator(None)
            return
        elapsed = time.time() - last
        if elapsed >= self.STALE_ERROR_THRESHOLD_S:
            tier = 'error'
        elif elapsed >= self.STALE_WARN_THRESHOLD_S:
            tier = 'warn'
        else:
            tier = None
        self._set_stale_indicator(tier)

    def _on_screen_contact(self, event):
        """Record the time of any touch on the screen. Used by
        _maybe_auto_scroll_payments_to_top to decide when to reset the
        payments view back to the most recent transactions. In LVGL 9
        events do NOT bubble to ancestors by default, so this callback
        has to be registered on every interactive widget directly (see
        the registration loop near the end of onCreate). A single
        screen-level listener would miss touches on child widgets."""
        try:
            self._last_screen_contact_ms = time.ticks_ms()
        except Exception:
            # time.ticks_ms() can fail on some boards; treat absence as
            # "never touched" — auto-scroll just won't fire, no crash.
            pass

    def _maybe_auto_scroll_payments_to_top(self):
        """If the user scrolled the payments area down and then hasn't
        touched the screen for AUTO_SCROLL_PAYMENTS_INACTIVITY_MS, scroll
        the list back to the top so the most recent transactions are the
        ones a passer-by sees. No-op if already at top, no-op if the
        screen has never been touched (fresh boot, nothing to revert)."""
        if not hasattr(self, 'payments_container'):
            return
        last = getattr(self, '_last_screen_contact_ms', None)
        if last is None:
            return
        try:
            elapsed = time.ticks_diff(time.ticks_ms(), last)
        except Exception:
            return
        if elapsed < self.AUTO_SCROLL_PAYMENTS_INACTIVITY_MS:
            return
        if self.payments_container.get_scroll_y() == 0:
            return
        print("DisplayWallet: auto-scrolling payments back to top after {}s inactivity".format(elapsed // 1000))
        # `True` = animated, so the user (if they happen to glance back)
        # sees the slide rather than a hard snap. Matches the cue we use
        # in redraw_payments_cb on new transactions.
        self.payments_container.scroll_to_y(0, True)

    def _stale_timer_tick(self, timer):
        self._refresh_stale_indicator()
        self._maybe_auto_scroll_payments_to_top()

    def went_online(self):
        if self.wallet and self.wallet.is_running():
            print("wallet is already running, nothing to do") # might have come from the QR activity
            return
        slot, s = self._active_slot_and_suffix()
        wallet_type = self.prefs.get_string("wallet_type" + s)
        if not wallet_type:
            self.show_welcome_screen()
            return # nothing is configured, nothing to do
        self.show_wallet_screen()
        # Paint from cache before constructing the wallet, so the user sees
        # last-known data immediately. Fingerprint mismatch (config change)
        # returns nothing painted and we fall through to the spinner.
        painted_from_cache = self._paint_from_cache(wallet_type, slot)
        if wallet_type == "lnbits":
            try:
                self.wallet = LNBitsWallet(
                    self.prefs.get_string("lnbits_url" + s),
                    self.prefs.get_string("lnbits_readkey" + s))
                self.wallet.static_receive_code = self.prefs.get_string("lnbits_static_receive_code" + s)
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize LNBits wallet because: {e}")
                return
        elif wallet_type == "nwc":
            try:
                self.wallet = NWCWallet(self.prefs.get_string("nwc_url" + s))
                self.wallet.static_receive_code = self.prefs.get_string("nwc_static_receive_code" + s)
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize NWC Wallet because: {e}")
                return
        elif wallet_type == "onchain":
            try:
                blockbook_url = self.prefs.get_string("onchain_blockbook_url" + s) or None
                self.wallet = OnchainWallet(
                    self.prefs.get_string("onchain_xpub" + s),
                    blockbook_url=blockbook_url,
                )
                # Settings override (a user-supplied BIP21 URI / static address)
                # wins; otherwise the wallet auto-rotates per-poll.
                self.wallet.static_receive_code = self.prefs.get_string("onchain_static_receive_code" + s)
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize On-chain wallet because: {e}")
                return
        else:
            self.error_cb(f"No or unsupported wallet type configured: '{wallet_type}'")
            return
        # Stamp the (per-wallet-type, per-slot) cache identity onto the wallet
        # so its handle_new_* writes land in the correct slot with matching
        # fingerprints. slot_key = "{type}_{slot}" → e.g. "lnbits_1", "onchain_2".
        self.wallet.slot_key = wallet_cache.compute_slot_key(wallet_type, slot)
        self.wallet.creds_fingerprint, self.wallet.qr_fingerprint = \
            wallet_cache.compute_fingerprints(wallet_type, self.prefs, slot=slot)
        # Stamp the config key so onResume can detect future changes.
        self._active_wallet_key = self._wallet_config_key()
        # Fresh wallet session — reset stale tracking.
        self._reset_stale_tracking()
        # Re-apply conditional wallet-type indicator visibility (was hidden
        # during the cache-paint phase to avoid showing the previous
        # wallet's icon during a slot/type switch).
        self._update_wallet_type_indicator()
        if not painted_from_cache and not (hasattr(self, '_last_balance') and self._last_balance):
            self.balance_label.set_text(lv.SYMBOL.REFRESH)
            self.balance_unit_label.set_text("")
            self.payments_label.set_text(f"\nConnecting to {wallet_type} backend.\n\nIf this takes too long, it might be down or something's wrong with the settings.")
        # by now, self.wallet can be assumed
        self.wallet.start(self.balance_updated_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb, self.error_cb)
        # Hook the per-poll success signal so the stale indicator resets
        # even when balance/payments don't change across polls. `start()`
        # doesn't take this as a positional arg to keep the signature
        # stable for existing callers; DisplayWallet attaches it after.
        self.wallet.poll_success_cb = self._note_successful_update

    def went_offline(self):
        # Check the ACTIVE slot's wallet_type, not slot 1's: a user with slot 2
        # active but slot 1 unconfigured would otherwise see the welcome
        # screen instead of the offline message. Mirrors went_online's pattern.
        slot, s = self._active_slot_and_suffix()
        wallet_type = self.prefs.get_string("wallet_type" + s)
        if not wallet_type:
            self.show_welcome_screen()
            return
        if self.wallet:
            self.wallet.stop()
        # Cold-boot-offline path: the app just launched and WiFi isn't up
        # yet, so went_online hasn't run. Paint from cache here too so the
        # user still sees their last-known balance/QR while offline.
        if not (hasattr(self, '_last_balance') and self._last_balance):
            self.show_wallet_screen()
            self._paint_from_cache(wallet_type, slot)
        # Don't overwrite cached data with offline message
        if not (hasattr(self, '_last_balance') and self._last_balance):
            self.payments_label.set_text(f"WiFi is not connected, can't talk to wallet...")

    def show_welcome_screen(self):
        """Hide wallet widgets, show welcome container."""
        for w in self.wallet_container_widgets:
            w.add_flag(lv.obj.FLAG.HIDDEN)
        # Hide the stale-indicator dot too — it lives outside
        # wallet_container_widgets so it isn't auto-shown when we return
        # to the wallet screen, but when we go to the welcome screen it
        # must explicitly hide.
        if hasattr(self, 'stale_indicator_dot'):
            self.stale_indicator_dot.add_flag(lv.obj.FLAG.HIDDEN)
        self.welcome_container.remove_flag(lv.obj.FLAG.HIDDEN)
        WidgetAnimator.show_widget(self.welcome_container)

    def show_wallet_screen(self):
        """Hide welcome container, show wallet widgets."""
        self.welcome_container.add_flag(lv.obj.FLAG.HIDDEN)
        for w in self.wallet_container_widgets:
            # Leave the receive-QR hidden if we don't yet have data for it —
            # otherwise a wallet restart (NWC → LNBits or vice versa) would
            # un-hide the QR widget with the PREVIOUS wallet's pixels still
            # rendered, showing the old QR for however long it takes the new
            # wallet to emit its own static_receive_code. redraw_static_receive_code_cb
            # will un-hide it when fresh data arrives.
            if w is self.receive_qr and not self.receive_qr_data:
                continue
            # The wallet-type indicators are mutually exclusive — let
            # _update_wallet_type_indicator() decide which one to show
            # based on the active wallet, rather than un-hiding both here.
            if w is self.lightning_bolt or w is self.chain_link:
                continue
            w.remove_flag(lv.obj.FLAG.HIDDEN)
        # Re-apply mutually-exclusive indicator visibility AFTER the blanket
        # un-hide above (otherwise both would briefly appear together).
        self._update_wallet_type_indicator()

    def _update_wallet_type_indicator(self):
        """Show exactly one wallet-type icon next to the QR area, based on
        the active slot's wallet type. Lightning (LNBits/NWC) → yellow ⚡;
        on-chain → pink chain-link. Anything else → both hidden."""
        if not hasattr(self, 'lightning_bolt'):
            return  # Called before onCreate completed (test path)
        _, s = self._active_slot_and_suffix()
        wt = self.prefs.get_string("wallet_type" + s)
        if wt in ("lnbits", "nwc"):
            self.lightning_bolt.remove_flag(lv.obj.FLAG.HIDDEN)
            self.chain_link.add_flag(lv.obj.FLAG.HIDDEN)
        elif wt == "onchain":
            self.lightning_bolt.add_flag(lv.obj.FLAG.HIDDEN)
            self.chain_link.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.lightning_bolt.add_flag(lv.obj.FLAG.HIDDEN)
            self.chain_link.add_flag(lv.obj.FLAG.HIDDEN)

    def _splash_done(self, timer):
        """Called after splash duration. Fade out splash and show appropriate screen.

        network_changed → went_online/went_offline both call
        _paint_from_cache, so the on-disk cache is replayed instantly
        for the currently-configured wallet type before (or in place of)
        the network fetch. Per-slot caching + fingerprint invalidation
        means there's no cross-wallet leakage: if the user switched
        wallet_type or changed credentials since the last run, the
        fingerprint won't match and the cache returns empty."""
        WidgetAnimator.hide_widget(self.splash_container, duration=500)
        cm = ConnectivityManager.get()
        self.network_changed(cm.is_online())


    def _icon_color(self):
        """Return icon color based on current theme."""
        if not AppearanceManager.is_light_mode():
            return lv.color_white()
        return lv.color_black()

    def _update_hero_image(self):
        """Show or hide the hero image based on the active slot's settings."""
        _, s = self._active_slot_and_suffix()
        hero = self.prefs.get_string("hero_image" + s, "lightningpiggy")
        # Always position the container in the same spot
        qr_size = DisplayMetrics.pct_of_width(self.receive_qr_pct_of_display)
        qr_bottom_y = qr_size + 16
        screen_h = DisplayMetrics.height()
        container_h = 100
        gap = (screen_h - qr_bottom_y - container_h) // 2
        self.hero_container.align_to(self.receive_qr, lv.ALIGN.OUT_BOTTOM_MID, 0, gap - 10)
        if hero and hero != "none":
            self.hero_image.set_src(f"{self.ASSET_PATH}hero_{hero}.png")
            self.hero_image.center()
            self.hero_image.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.hero_image.add_flag(lv.obj.FLAG.HIDDEN)
        # Re-anchor the stale-indicator dot on the (new) mascot position.
        # Go through _reposition_stale_indicator so the layout-flush +
        # coord read logic is shared between onCreate and hero-image swaps.
        self._reposition_stale_indicator()

    def _on_hero_image_changed(self, new_value):
        """Called when hero image setting changes."""
        self._update_hero_image()

    def _on_static_receive_code_changed(self, new_value):
        """Called when the user edits any "Optional ... Address" override
        in Settings → Wallet — `lnbits_static_receive_code`,
        `nwc_static_receive_code`, or `onchain_static_receive_code`,
        for slot 1 or slot 2.

        Re-syncs the currently-active wallet's `static_receive_code`
        from prefs and triggers an immediate QR redraw, so the new
        value shows up without requiring an app restart.

        Multi-wallet behaviour: only the *active* slot's override is
        read here. If the user edited the *inactive* slot's override,
        the active slot's value is unchanged and this is a no-op for
        the visible state — the inactive slot's new value is correctly
        saved to prefs and will take effect on the next slot switch
        (which already re-reads prefs via `went_online`). The fix is
        therefore safe to wire on every LN-address setting regardless
        of which slot it belongs to.

        Also updates `_active_wallet_key` so the subsequent `onResume`
        doesn't see a "config changed" and waste cycles restarting the
        active wallet — the override change is handled live, no socket
        churn needed.
        """
        if self.wallet:
            _, s = self._active_slot_and_suffix()
            wt = self.prefs.get_string("wallet_type" + s)
            if wt == "lnbits":
                override = self.prefs.get_string("lnbits_static_receive_code" + s)
            elif wt == "nwc":
                override = self.prefs.get_string("nwc_static_receive_code" + s)
            elif wt == "onchain":
                override = self.prefs.get_string("onchain_static_receive_code" + s)
            else:
                override = ""
            if override:
                self.wallet.static_receive_code = override
        self.redraw_static_receive_code_cb()
        # Keep the active-config key in sync so onResume's "config
        # changed → restart wallet" branch doesn't fire redundantly.
        if hasattr(self, '_active_wallet_key'):
            self._active_wallet_key = self._wallet_config_key()

    def _qr_colors(self):
        """Return (dark_color, light_color) tuple based on current theme."""
        if not AppearanceManager.is_light_mode():
            return (lv.color_white(), lv.color_black())
        return (lv.color_black(), lv.color_white())

    def _apply_qr_theme(self):
        """Reapply theme-dependent styles (screen bg, QR colors, icon tints)."""
        # Screen background follows light/dark mode — otherwise the hardcoded
        # bg from onCreate lingers after a theme toggle.
        if AppearanceManager.is_light_mode():
            self.main_screen.set_style_bg_color(lv.color_white(), lv.PART.MAIN)
        else:
            self.main_screen.set_style_bg_color(lv.color_black(), lv.PART.MAIN)
        dark, light = self._qr_colors()
        self.receive_qr.set_dark_color(dark)
        self.receive_qr.set_light_color(light)
        self.receive_qr.set_style_border_color(light, lv.PART.MAIN)
        if self.receive_qr_data:
            self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data))
        # Settings-cog icon colour tracks the theme (white in dark mode, black in light).
        if hasattr(self, 'settings_icon'):
            self.settings_icon.set_style_text_color(self._icon_color(), lv.PART.MAIN)
        # Splash + welcome containers are opaque overlays; keep their bg in sync
        # with the screen so a theme flip while either is visible doesn't leave
        # a stale dark-grey rectangle behind.
        if getattr(self, 'splash_container', None) is not None:
            _apply_screen_theme(self.splash_container)
        if getattr(self, 'welcome_container', None) is not None:
            _apply_screen_theme(self.welcome_container)
        # Re-render balance in case denomination setting changed
        if hasattr(self, '_last_balance'):
            self.display_balance(self._last_balance)

    def update_payments_label_font(self):
        self.payments_label.set_style_text_font(self.payments_label_fonts[self.payments_label_current_font], lv.PART.MAIN)

    def payments_label_clicked(self, event):
        if self._is_screen_locked():
            return
        self.payments_label_current_font = (self.payments_label_current_font + 1) % len(self.payments_label_fonts)
        self.update_payments_label_font()

    def float_to_string(self, value, decimals):
        if _has_number_format:
            return NumberFormat.format_number(value, decimals)
        # Fallback for firmware without NumberFormat
        s = "{:.{}f}".format(value, decimals)
        return s.rstrip("0").rstrip(".")

    def display_balance(self, balance):
         self._last_balance = balance
         # Slot-aware denom read: slot 1 uses `balance_denomination`,
         # slot 2 uses `balance_denomination_2` (multi-wallet).
         _, s = self._active_slot_and_suffix()
         denom = self.prefs.get_string("balance_denomination" + s, "sats")
         Payment.use_symbol = (denom == "\u20bf symbol")
         self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
         # Split the balance into a big number + a smaller unit suffix.
         # See onCreate for the layout reasoning. Each branch sets
         # `number_text` (rendered in the big font) and `unit_text`
         # (rendered in the small font, to the right). The \u20bf-symbol mode
         # has no unit suffix since the glyph IS the unit indicator.
         if denom == "\u20bf symbol":
             sats = int(round(balance))
             number_text = "\u20bf" + NumberFormat.format_number(sats)
             unit_text = ""
         elif denom == "sats":
             sats = int(round(balance))
             number_text = NumberFormat.format_number(sats)
             unit_text = " sat" if sats == 1 else " sats"
         elif denom == "bits":
             balance_bits = round(balance / 100, 2)
             number_text = self.float_to_string(balance_bits, 2)
             unit_text = " bit" if balance_bits == 1 else " bits"
         elif denom == "ubtc":
             balance_ubtc = round(balance / 100, 2)
             number_text = self.float_to_string(balance_ubtc, 2)
             unit_text = " micro-BTC"
         elif denom == "mbtc":
             balance_mbtc = round(balance / 100000, 5)
             number_text = self.float_to_string(balance_mbtc, 5)
             unit_text = " milli-BTC"
         elif denom == "btc":
             balance_btc = round(balance / 100000000, 8)
             number_text = self.float_to_string(balance_btc, 8)
             unit_text = " BTC"
         else:
             # Unknown denomination \u2014 defensive fallback that mirrors the
             # pre-split single-string behaviour (everything in the big font).
             number_text = str(balance)
             unit_text = ""
         self.balance_label.set_text(number_text)
         self.balance_unit_label.set_text(unit_text)
         # Re-align the unit label every time we update because the number
         # label's content-fitted width changes with each new value \u2014 the
         # unit needs to follow.
         self.balance_unit_label.align_to(self.balance_label, lv.ALIGN.OUT_RIGHT_BOTTOM, 2, 10)

    def balance_updated_cb(self, sats_added=0):
        print(f"balance_updated_cb(sats_added={sats_added})")

        if self.fullscreenqr.has_foreground():
            self.fullscreenqr.finish()

        if sats_added > 0:
            self.confetti.start()

        balance = self.wallet.last_known_balance
        print(f"balance: {balance}")

        if balance is None:
            print("Not drawing balance because it's None")
            return

        # Successful refresh — bump last-success timestamp and re-evaluate
        # the stale indicator (usually hides the dot).
        self._note_successful_update()

        # Mark as connected even if balance == 0
        if getattr(self.wallet, "payment_list", None) is not None:
            if len(self.wallet.payment_list) == 0:
                # Wallet reports empty — but if we previously painted
                # payments from cache they're still on-screen and accurate
                # for the last session; don't overwrite with "Connected."
                # until fetch_payments has actually run and confirmed.
                # A freshly-constructed wallet has payment_list == [] before
                # its first fetch, so we rely on the fetch_payments triggered
                # inside handle_new_balance to repaint.
                if not (hasattr(self, '_last_balance') and self._last_balance):
                    self.payments_label.set_text("Connected.\nNo payments yet.")
            else:
                self.payments_label.set_text(str(self.wallet.payment_list))
        else:
            self.payments_label.set_text("Connected.")

        # Paint the final balance synchronously before handing off to the
        # animator. Two edge cases were leaving the screen blank until the
        # user left the app and came back:
        #   1. Zero-delta animations (sats_added == 0) don't always tick
        #      display_change, so the label kept whatever stale text it had.
        #   2. WidgetAnimator wraps display_change in _safe_widget_access,
        #      which silently swallows LvReferenceError — if the label was
        #      briefly orphaned during a wallet swap, the animator's ticks
        #      would no-op and the balance would never render.
        # Calling display_balance directly first guarantees the label shows
        # the current balance; the animator then rolls from begin -> end
        # over the confetti duration as usual.
        self.display_balance(balance)
        WidgetAnimator.change_widget(
            self.balance_label,
            anim_type="interpolate",
            duration=self.confetti_duration,
            delay=0,
            begin_value=balance - sats_added,
            end_value=balance,
            display_change=self.display_balance
        )
    
    def redraw_payments_cb(self):
        # Called from the wallet's polling task. MicroPython asyncio is
        # single-threaded and cooperative, so this runs on the same event
        # loop as LVGL — direct widget writes are safe between awaits.
        self.payments_label.set_text(str(self.wallet.payment_list))
        # Scroll the transactions area back to the top so any new tx is
        # immediately visible — even if the user had previously scrolled
        # down to inspect older entries. `True` = animated; gives a brief
        # slide-up cue that the list changed. No-op when already at top.
        if hasattr(self, 'payments_container'):
            self.payments_container.scroll_to_y(0, True)
        # Successful payments refresh — bump last-success timestamp.
        self._note_successful_update()

    def redraw_static_receive_code_cb(self):
        # Settings override (for the active slot's wallet type) wins if present.
        _, s = self._active_slot_and_suffix()
        wallet_type = self.prefs.get_string("wallet_type" + s)
        override = None
        if wallet_type == "nwc":
            override = self.prefs.get_string("nwc_static_receive_code" + s)
        elif wallet_type == "lnbits":
            override = self.prefs.get_string("lnbits_static_receive_code" + s)
        elif wallet_type == "onchain":
            override = self.prefs.get_string("onchain_static_receive_code" + s)
        # Next, the wallet's own discovered receive code (from backend / NWC lud16).
        wallet_code = self.wallet.static_receive_code if self.wallet else None
        # Pick the first non-empty source; fall through to whatever's already
        # set (e.g. painted from the cache by _paint_from_cache) so we don't
        # wipe a valid QR when neither override nor wallet-side code is
        # populated yet — typical right after went_online, before the wallet
        # has had a chance to fetch_static_receive_code.
        if override:
            self.receive_qr_data = override
        elif wallet_code:
            self.receive_qr_data = wallet_code
        # else: keep self.receive_qr_data as-is
        if not self.receive_qr_data:
            print("Warning: redraw_static_receive_code_cb() did not find one in the settings or the wallet, nothing to show")
            return
        self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data))
        # Un-hide the QR widget (it's hidden during wallet-switch resets in
        # onResume so the previous wallet's QR doesn't linger on screen).
        self.receive_qr.remove_flag(lv.obj.FLAG.HIDDEN)

    def error_cb(self, error):
        if self.wallet and self.wallet.is_running():
            # Don't overwrite cached payments with error if we have cached data
            if hasattr(self, '_last_balance') and self._last_balance:
                print(f"WARNING: {error} (keeping cached data on screen)")
            else:
                self.payments_label.set_text(str(error))
        # An error means time-since-last-success keeps growing. Recompute
        # the tier opportunistically so the dot updates without waiting
        # for the next timer tick. The timer still runs in the background
        # as a safety net for periods with no events (e.g. wallet stopped
        # while WiFi is down).
        self._refresh_stale_indicator()

    def settings_button_tap(self, event):
        self.destination = MainSettingsActivity  # prevent wallet.stop() in onPause
        intent = Intent(activity_class=MainSettingsActivity)
        intent.putExtra("prefs", self.prefs)
        # "Wallet" always points at the *active* slot (so editing this row
        # changes the wallet the user is looking at). The bottom row is
        # contextual: if no slot-2 wallet exists, show "Add wallet"
        # (opens slot 2 in WalletSettingsActivity); once slot 2 is
        # configured, show "Switch to <other-type>" which flips the
        # active slot on tap and drops back to the main display.
        active_slot, _ = self._active_slot_and_suffix()
        active_slot_int = int(active_slot)
        other_slot = 2 if active_slot_int == 1 else 1
        other_suffix = _slot_suffix(other_slot)
        other_wallet_type = self.prefs.get_string("wallet_type" + other_suffix)
        # Shared callback bundle for both Wallet entries below. Only the
        # static_receive_code (Optional LN Address / Optional Receive
        # Address) override needs live-redraw on save; URL / readkey /
        # NWC URL / xpub / Blockbook URL changes already trip
        # `_wallet_config_key()` and onResume restarts the wallet.
        _wallet_callbacks = {"static_receive_code": self._on_static_receive_code_changed}
        settings_rows = [
            {"title": "Wallet", "key": "wallet_type", "ui": "activity",
             "activity_class": WalletSettingsActivity,
             "placeholder": self.prefs.get_string(
                 "wallet_type" + _slot_suffix(active_slot_int),
                 "not configured"),
             "_slot": active_slot_int,
             "_callbacks": _wallet_callbacks},
            {"title": "Customise", "key": "customise", "ui": "activity",
             "activity_class": CustomiseSettingsActivity,
             "placeholder": "Balance denomination, hero image",
             "_callbacks": {"denomination": self._on_denomination_changed, "hero_image": self._on_hero_image_changed}},
            {"title": "Screen Lock", "key": "screen_lock", "activity_class": True,
             "placeholder": "On - tapping disabled" if self.prefs.get_string("screen_lock", "off") == "on" else "Off - tapping changes display"},
        ]
        if not other_wallet_type:
            # No second wallet yet — offer to set one up.
            settings_rows.append({
                "title": "Add wallet",
                "key": "wallet_type",
                "ui": "activity",
                "activity_class": WalletSettingsActivity,
                "placeholder": "Set up a second wallet to switch between",
                "_slot": other_slot,
                "_callbacks": _wallet_callbacks,
            })
        else:
            # Second wallet exists — offer a one-tap switch.
            settings_rows.append({
                "title": "Switch to " + other_wallet_type,
                "key": "__switch_active_wallet",
                "activity_class": True,  # routed inline by MainSettingsActivity
                "placeholder": "Flip the active wallet",
            })
        intent.putExtra("settings", settings_rows)
        self.startActivity(intent)

    HERO_CYCLE = ["lightningpiggy", "lightningpenguin", "none"]
    DENOMINATION_CYCLE = ["sats", "₿ symbol", "bits", "ubtc", "mbtc", "btc"]

    def _is_screen_locked(self):
        return self.prefs.get_string("screen_lock", "off") == "on"

    def hero_image_clicked_cb(self, event):
        """Cycle through hero images on tap — writes to the active slot's
        hero_image pref so a per-slot choice (Piggy on slot 1, Penguin on
        slot 2) is preserved across wallet switches."""
        if self._is_screen_locked():
            return
        _, s = self._active_slot_and_suffix()
        key = "hero_image" + s
        current = self.prefs.get_string(key, "lightningpiggy")
        try:
            idx = self.HERO_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_hero = self.HERO_CYCLE[(idx + 1) % len(self.HERO_CYCLE)]
        editor = self.prefs.edit()
        editor.put_string(key, next_hero)
        editor.commit()
        self._update_hero_image()

    def balance_label_clicked_cb(self, event):
        """Cycle through balance denominations on tap — writes to the active
        slot's denomination pref so each wallet remembers its own display
        format independently."""
        if self._is_screen_locked():
            return
        _, s = self._active_slot_and_suffix()
        key = "balance_denomination" + s
        current = self.prefs.get_string(key, "sats")
        try:
            idx = self.DENOMINATION_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_denom = self.DENOMINATION_CYCLE[(idx + 1) % len(self.DENOMINATION_CYCLE)]
        editor = self.prefs.edit()
        editor.put_string(key, next_denom)
        editor.commit()
        if hasattr(self, '_last_balance'):
            self.display_balance(self._last_balance)
        if self.wallet and self.wallet.payment_list and len(self.wallet.payment_list) > 0:
            self.payments_label.set_text(str(self.wallet.payment_list))

    def _on_denomination_changed(self, new_value):
        """Called when balance denomination setting changes."""
        if hasattr(self, '_last_balance'):
            self.display_balance(self._last_balance)
        if self.wallet and self.wallet.payment_list and len(self.wallet.payment_list) > 0:
            self.payments_label.set_text(str(self.wallet.payment_list))

    def main_ui_set_defaults(self):
        self.balance_label.set_text("Welcome!")
        self.balance_unit_label.set_text("")
        self.payments_label.set_text(lv.SYMBOL.REFRESH)

    def qr_clicked_cb(self, event):
        print("QR clicked")
        if self._is_screen_locked():
            return
        if not self.receive_qr_data:
            return
        self.destination = FullscreenQR
        self.startActivity(Intent(activity_class=self.fullscreenqr).putExtra("receive_qr_data", self.receive_qr_data))
