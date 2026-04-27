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


def _should_show_wallet_setting(setting):
    """Conditionally show wallet-specific settings based on selected wallet type."""
    prefs = SharedPreferences("com.lightningpiggy.displaywallet")
    wallet_type = prefs.get_string("wallet_type")
    if wallet_type != "lnbits" and setting["key"].startswith("lnbits_"):
        return False
    if wallet_type != "nwc" and setting["key"].startswith("nwc_"):
        return False
    return True


class WalletSettingsActivity(SettingsActivity):
    """Sub-settings screen for wallet configuration."""
    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        self.settings = [
            {"title": "Wallet Type", "key": "wallet_type", "ui": "radiobuttons",
             "ui_options": [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc")]},
            {"title": "LNBits URL", "key": "lnbits_url",
             "placeholder": "https://demo.lnpiggy.com", "should_show": _should_show_wallet_setting},
            {"title": "LNBits Read Key", "key": "lnbits_readkey",
             "placeholder": "fd92e3f8168ba314dc22e54182784045", "should_show": _should_show_wallet_setting},
            {"title": "Optional LN Address", "key": "lnbits_static_receive_code",
             "placeholder": "Will be fetched if empty.", "should_show": _should_show_wallet_setting},
            {"title": "Nostr Wallet Connect", "key": "nwc_url",
             "placeholder": "nostr+walletconnect://69effe7b...", "should_show": _should_show_wallet_setting},
            {"title": "Optional LN Address", "key": "nwc_static_receive_code",
             "placeholder": "Optional if present in NWC URL.", "should_show": _should_show_wallet_setting},
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
        self.settings = [
            {"title": "Balance Denomination", "key": "balance_denomination", "ui": "activity",
             "activity_class": DenominationSettingsActivity,
             "placeholder": self.prefs.get_string("balance_denomination", "sats"),
             "changed_callback": callbacks.get("denomination")},
            {"title": "Hero Image", "key": "hero_image", "ui": "radiobuttons",
             "ui_options": [("Lightning Piggy", "lightningpiggy"), ("Lightning Penguin", "lightningpenguin"), ("None", "none")],
             "default_value": "lightningpiggy",
             "changed_callback": callbacks.get("hero_image")},
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
        """Override to handle screen lock toggle inline."""
        if setting.get("key") == "screen_lock":
            current = self.prefs.get_string("screen_lock", "off")
            new_value = "on" if current == "off" else "off"
            editor = self.prefs.edit()
            editor.put_string("screen_lock", new_value)
            editor.commit()
            value_label = setting.get("value_label")
            if value_label:
                value_label.set_text("On - tapping disabled" if new_value == "on" else "Off - tapping changes display")
        else:
            super().startSettingActivity(setting)


class DenominationSettingsActivity(Activity):
    """Custom denomination picker with 2-column radio button layout."""
    DENOMINATIONS = [
        ("sats", "sats"),
        ("\u20bf sats", "symbol"),
        ("bits", "bits"),
        ("micro-BTC", "ubtc"),
        ("milli-BTC", "mbtc"),
        ("BTC", "btc"),
    ]

    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        self.setting = extras.get("setting")
        current = self.prefs.get_string("balance_denomination", "sats")

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
            old_value = self.prefs.get_string("balance_denomination")
            editor = self.prefs.edit()
            editor.put_string("balance_denomination", new_value)
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
    payments_label_current_font = 2
    try:
        # MicroPythonOS 0.9.3
        payments_label_fonts = [ lv.font_montserrat_10, lv.font_unscii_8, lv.font_montserrat_16, lv.font_montserrat_24, lv.font_unscii_16, lv.font_montserrat_28, lv.font_montserrat_40]
    except Exception as e:
        # Fallback for users with MicroPythonOS < 0.9.3
        payments_label_fonts = [ lv.font_montserrat_10, lv.font_unscii_8, lv.font_montserrat_16, lv.font_montserrat_24, lv.font_unscii_16, lv.font_montserrat_28_compressed, lv.font_montserrat_40]

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

    # activities
    fullscreenqr = FullscreenQR() # need a reference to be able to finish() it

    def onCreate(self):
        self.prefs = SharedPreferences("com.lightningpiggy.displaywallet")
        self.main_screen = lv.obj()
        if not AppearanceManager.is_light_mode():
            self.main_screen.set_style_bg_color(lv.color_black(), lv.PART.MAIN)
        else:
            self.main_screen.set_style_bg_color(lv.color_white(), lv.PART.MAIN)
        self.main_screen.set_style_pad_all(0, lv.PART.MAIN)
        # This line needs to be drawn first, otherwise it's over the balance label and steals all the clicks!
        balance_line = lv.line(self.main_screen)
        balance_line.set_points([{'x':2,'y':35},{'x':DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.2),'y':35}],2)
        self.balance_label = lv.label(self.main_screen)
        self.balance_label.set_text("")
        self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
        self.balance_label.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        self.balance_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.balance_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display)) # 100 - receive_qr
        self.balance_label.add_event_cb(self.balance_label_clicked_cb, lv.EVENT.CLICKED, None)
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
        self.payments_label = lv.label(self.main_screen)
        self.payments_label.set_text("")
        self.payments_label.align_to(balance_line,lv.ALIGN.OUT_BOTTOM_LEFT, 2, 10)
        self.update_payments_label_font()
        self.payments_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display)) # 100 - receive_qr
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
        self.wallet_container_widgets = [balance_line, self.balance_label, self.receive_qr, self.payments_label, self.hero_container, settings_button]

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

    def _wallet_config_key(self):
        """Tuple that uniquely identifies the current wallet config. Changes
        to any of these prefs invalidate the running wallet — onResume uses
        this to detect when the user changed settings and restart."""
        wt = self.prefs.get_string("wallet_type")
        if wt == "lnbits":
            return (wt,
                    self.prefs.get_string("lnbits_url"),
                    self.prefs.get_string("lnbits_readkey"))
        if wt == "nwc":
            return (wt, self.prefs.get_string("nwc_url"))
        return (wt,)

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
        # Stop the periodic stale-indicator timer so it doesn't fire on a
        # dead Activity instance.
        if getattr(self, '_stale_timer', None) is not None:
            try:
                self._stale_timer.delete()
            except Exception:
                pass
            self._stale_timer = None
        # would be good to cleanup lv.layer_top() of those confetti images

    def network_changed(self, online):
        print("displaywallet.py network_changed, now:", "ONLINE" if online else "OFFLINE")
        if online:
            self.went_online()
        else:
            self.went_offline()

    def _paint_from_cache(self, wallet_type):
        """Paint balance, payments and QR from the on-disk cache slot for
        `wallet_type`, if the cached fingerprints still match the current
        prefs. Returns True if anything was painted.

        Called from went_online() before wallet.start() so the UI shows
        the last-known data instantly while the network fetch is in
        flight. Any field whose fingerprint doesn't match comes back None
        and is left in its default (spinner / Connecting... text)."""
        creds_fp, qr_fp = wallet_cache.compute_fingerprints(wallet_type, self.prefs)
        cached = wallet_cache.load_slot(wallet_type, creds_fp, qr_fp)
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
            print("Cache: painted slot '{}' from disk".format(wallet_type))
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

    def _stale_timer_tick(self, timer):
        self._refresh_stale_indicator()

    def went_online(self):
        if self.wallet and self.wallet.is_running():
            print("wallet is already running, nothing to do") # might have come from the QR activity
            return
        wallet_type = self.prefs.get_string("wallet_type")
        if not wallet_type:
            self.show_welcome_screen()
            return # nothing is configured, nothing to do
        self.show_wallet_screen()
        # Paint from cache before constructing the wallet, so the user sees
        # last-known data immediately. Fingerprint mismatch (config change)
        # returns nothing painted and we fall through to the spinner.
        painted_from_cache = self._paint_from_cache(wallet_type)
        if wallet_type == "lnbits":
            try:
                self.wallet = LNBitsWallet(self.prefs.get_string("lnbits_url"), self.prefs.get_string("lnbits_readkey"))
                self.wallet.static_receive_code = self.prefs.get_string("lnbits_static_receive_code")
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize LNBits wallet because: {e}")
                return
        elif wallet_type == "nwc":
            try:
                self.wallet = NWCWallet(self.prefs.get_string("nwc_url"))
                self.wallet.static_receive_code = self.prefs.get_string("nwc_static_receive_code")
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize NWC Wallet because: {e}")
                return
        else:
            self.error_cb(f"No or unsupported wallet type configured: '{wallet_type}'")
            return
        # Stamp the cache fingerprints onto the wallet so its handle_new_*
        # writes land in the correct slot with a matching fingerprint.
        self.wallet.creds_fingerprint, self.wallet.qr_fingerprint = \
            wallet_cache.compute_fingerprints(wallet_type, self.prefs)
        # Stamp the config key so onResume can detect future changes.
        self._active_wallet_key = self._wallet_config_key()
        # Fresh wallet session — reset stale tracking.
        self._reset_stale_tracking()
        if not painted_from_cache and not (hasattr(self, '_last_balance') and self._last_balance):
            self.balance_label.set_text(lv.SYMBOL.REFRESH)
            self.payments_label.set_text(f"\nConnecting to {wallet_type} backend.\n\nIf this takes too long, it might be down or something's wrong with the settings.")
        # by now, self.wallet can be assumed
        self.wallet.start(self.balance_updated_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb, self.error_cb)
        # Hook the per-poll success signal so the stale indicator resets
        # even when balance/payments don't change across polls. `start()`
        # doesn't take this as a positional arg to keep the signature
        # stable for existing callers; DisplayWallet attaches it after.
        self.wallet.poll_success_cb = self._note_successful_update

    def went_offline(self):
        wallet_type = self.prefs.get_string("wallet_type")
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
            self._paint_from_cache(wallet_type)
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
            w.remove_flag(lv.obj.FLAG.HIDDEN)

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
        """Show or hide the hero image based on settings."""
        hero = self.prefs.get_string("hero_image", "lightningpiggy")
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
         denom = self.prefs.get_string("balance_denomination", "sats")
         Payment.use_symbol = (denom == "symbol")
         self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
         if denom in ("sats", "symbol"):
             sats = int(round(balance))
             formatted = NumberFormat.format_number(sats)
             if denom == "symbol":
                 balance_text = "\u20bf" + formatted
             else:
                 balance_text = formatted + (" sat" if sats == 1 else " sats")
         elif denom == "bits":
             balance_bits = round(balance / 100, 2)
             balance_text = self.float_to_string(balance_bits, 2) + " bit"
             if balance_bits != 1:
                 balance_text += "s"
         elif denom == "ubtc":
             balance_ubtc = round(balance / 100, 2)
             balance_text = self.float_to_string(balance_ubtc, 2) + " micro-BTC"
         elif denom == "mbtc":
             balance_mbtc = round(balance / 100000, 5)
             balance_text = self.float_to_string(balance_mbtc, 5) + " milli-BTC"
         elif denom == "btc":
             balance_btc = round(balance / 100000000, 8)
             balance_text = self.float_to_string(balance_btc, 8) + " BTC"
         self.balance_label.set_text(balance_text)

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
        # Successful payments refresh — bump last-success timestamp.
        self._note_successful_update()

    def redraw_static_receive_code_cb(self):
        # Settings override wins if present.
        wallet_type = self.prefs.get_string("wallet_type")
        override = None
        if wallet_type == "nwc":
            override = self.prefs.get_string("nwc_static_receive_code")
        elif wallet_type == "lnbits":
            override = self.prefs.get_string("lnbits_static_receive_code")
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
        intent.putExtra("settings", [
            {"title": "Wallet", "key": "wallet_type", "ui": "activity",
             "activity_class": WalletSettingsActivity,
             "placeholder": self.prefs.get_string("wallet_type", "not configured")},
            {"title": "Customise", "key": "customise", "ui": "activity",
             "activity_class": CustomiseSettingsActivity,
             "placeholder": "Balance denomination, hero image",
             "_callbacks": {"denomination": self._on_denomination_changed, "hero_image": self._on_hero_image_changed}},
            {"title": "Screen Lock", "key": "screen_lock", "activity_class": True,
             "placeholder": "On - tapping disabled" if self.prefs.get_string("screen_lock", "off") == "on" else "Off - tapping changes display"},
        ])
        self.startActivity(intent)

    HERO_CYCLE = ["lightningpiggy", "lightningpenguin", "none"]
    DENOMINATION_CYCLE = ["sats", "symbol", "bits", "ubtc", "mbtc", "btc"]

    def _is_screen_locked(self):
        return self.prefs.get_string("screen_lock", "off") == "on"

    def hero_image_clicked_cb(self, event):
        """Cycle through hero images on tap."""
        if self._is_screen_locked():
            return
        current = self.prefs.get_string("hero_image", "lightningpiggy")
        try:
            idx = self.HERO_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_hero = self.HERO_CYCLE[(idx + 1) % len(self.HERO_CYCLE)]
        editor = self.prefs.edit()
        editor.put_string("hero_image", next_hero)
        editor.commit()
        self._update_hero_image()

    def balance_label_clicked_cb(self, event):
        """Cycle through balance denominations on tap."""
        if self._is_screen_locked():
            return
        current = self.prefs.get_string("balance_denomination", "sats")
        try:
            idx = self.DENOMINATION_CYCLE.index(current)
        except ValueError:
            idx = 0
        next_denom = self.DENOMINATION_CYCLE[(idx + 1) % len(self.DENOMINATION_CYCLE)]
        editor = self.prefs.edit()
        editor.put_string("balance_denomination", next_denom)
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
        self.payments_label.set_text(lv.SYMBOL.REFRESH)

    def qr_clicked_cb(self, event):
        print("QR clicked")
        if self._is_screen_locked():
            return
        if not self.receive_qr_data:
            return
        self.destination = FullscreenQR
        self.startActivity(Intent(activity_class=self.fullscreenqr).putExtra("receive_qr_data", self.receive_qr_data))
