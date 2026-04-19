import lvgl as lv
import time

from mpos import Activity, Intent, ConnectivityManager, MposKeyboard, DisplayMetrics, SharedPreferences, SettingsActivity, TaskManager, WidgetAnimator
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


def _add_floating_back_button(screen, finish_callback):
    """Add a floating back-to-display button at bottom-right of a settings screen."""
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


def _slot_suffix(slot):
    """Suffix for per-slot pref keys: '' for slot 1, '_2' for slot 2."""
    return "_2" if slot == 2 else ""


def _should_show_wallet_setting(setting):
    """Conditionally show wallet-specific settings based on this slot's wallet_type."""
    slot = setting.get("_slot", 1)
    suffix = _slot_suffix(slot)
    prefs = SharedPreferences("com.lightningpiggy.displaywallet")
    wallet_type = prefs.get_string("wallet_type" + suffix)
    # Strip the slot suffix from the key for prefix matching against the wallet-type branches.
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
    setting dict selects slot 1 (default, unsuffixed keys) or slot 2 (_2 suffix).
    """
    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        parent_setting = extras.get("setting") or {}
        self.slot = parent_setting.get("_slot", 1)
        s = _slot_suffix(self.slot)
        self.settings = [
            {"title": "Wallet Type", "key": "wallet_type" + s, "ui": "radiobuttons",
             "ui_options": [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc"), ("On-chain (xpub)", "onchain")],
             "_slot": self.slot},
            {"title": "LNBits URL", "key": "lnbits_url" + s,
             "placeholder": "https://demo.lnpiggy.com", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "LNBits Read Key", "key": "lnbits_readkey" + s,
             "placeholder": "fd92e3f8168ba314dc22e54182784045", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Optional LN Address", "key": "lnbits_static_receive_code" + s,
             "placeholder": "Will be fetched if empty.", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Nostr Wallet Connect", "key": "nwc_url" + s,
             "placeholder": "nostr+walletconnect://69effe7b...", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "Optional LN Address", "key": "nwc_static_receive_code" + s,
             "placeholder": "Optional if present in NWC URL.", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "xpub / ypub / zpub", "key": "onchain_xpub" + s,
             "placeholder": "zpub6rF...", "should_show": _should_show_wallet_setting, "_slot": self.slot},
            {"title": "xpub endpoint", "key": "onchain_blockbook_url" + s,
             "placeholder": "https://btc1.trezor.io", "default_value": "https://btc1.trezor.io",
             "should_show": _should_show_wallet_setting, "_slot": self.slot},
        ]
        screen = lv.obj()
        screen.set_style_pad_all(DisplayMetrics.pct_of_width(2), lv.PART.MAIN)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, lv.PART.MAIN)
        self.setContentView(screen)

    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)


class CustomiseSettingsActivity(SettingsActivity):
    """Sub-settings screen for display customisation."""
    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        # Callbacks are passed via the setting dict from the parent
        setting = extras.get("setting") or {}
        callbacks = setting.get("_callbacks") or {}
        # Hero image and balance denomination are per-wallet-slot — keys follow the active slot
        active_slot = self.prefs.get_string("active_wallet_slot", "1")
        slot_suffix = "_2" if active_slot == "2" else ""
        hero_key = "hero_image" + slot_suffix
        denom_key = "balance_denomination" + slot_suffix
        self.settings = [
            {"title": "Balance Denomination", "key": denom_key, "ui": "activity",
             "activity_class": DenominationSettingsActivity,
             "placeholder": self.prefs.get_string(denom_key, "sats"),
             "changed_callback": callbacks.get("denomination")},
            {"title": "Hero Image", "key": hero_key, "ui": "radiobuttons",
             "ui_options": [("Lightning Piggy", "lightningpiggy"), ("Lightning Penguin", "lightningpenguin"), ("None", "none")],
             "default_value": "lightningpiggy",
             "changed_callback": callbacks.get("hero_image")},
        ]
        screen = lv.obj()
        screen.set_style_pad_all(DisplayMetrics.pct_of_width(2), lv.PART.MAIN)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, lv.PART.MAIN)
        self.setContentView(screen)

    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)


class MainSettingsActivity(SettingsActivity):
    """Settings screen with a back-to-display button."""
    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)

    def startSettingActivity(self, setting):
        """Override to handle inline toggle settings (screen lock, switch-wallet)."""
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
            # Flip active slot and drop back to the main display so the user sees the switch happen.
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
        ("\u20bf sats", "symbol"),
        ("bits", "bits"),
        ("micro-BTC", "ubtc"),
        ("milli-BTC", "mbtc"),
        ("BTC", "btc"),
    ]

    def onCreate(self):
        extras = self.getIntent().extras or {}
        self.prefs = extras.get("prefs")
        self.setting = extras.get("setting") or {}
        # Per-slot key — parent activity already selected the right one for the active slot
        self.key = self.setting.get("key", "balance_denomination")
        current = self.prefs.get_string(self.key, "sats")

        screen = lv.obj()
        screen.set_style_pad_all(DisplayMetrics.pct_of_width(2), lv.PART.MAIN)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, lv.PART.MAIN)

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
            old_value = self.prefs.get_string(self.key)
            editor = self.prefs.edit()
            editor.put_string(self.key, new_value)
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

    # activities
    fullscreenqr = FullscreenQR() # need a reference to be able to finish() it

    def onCreate(self):
        self.prefs = SharedPreferences("com.lightningpiggy.displaywallet")
        # Seed the on-chain xpub endpoint with the default so it shows in the
        # settings list and pre-populates the editor when the user taps it.
        editor = None
        for slot_suffix in ("", "_2"):
            key = "onchain_blockbook_url" + slot_suffix
            if not self.prefs.get_string(key):
                editor = editor or self.prefs.edit()
                editor.put_string(key, OnchainWallet.DEFAULT_BLOCKBOOK_URL)
        if editor:
            editor.commit()
        self.main_screen = lv.obj()
        if not AppearanceManager.is_light_mode():
            self.main_screen.set_style_bg_color(lv.color_hex(0x15171A), lv.PART.MAIN)
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
        self.balance_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.1)) # leave a small gap to the QR
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
        # Wallet-type indicator on the right side of the balance area, rendered
        # behind the balance text: yellow ⚡ for Lightning (LNBits, NWC),
        # pink chain link for on-chain. Exactly one is visible at a time.
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
        self.payments_label = lv.label(self.main_screen)
        self.payments_label.set_text("")
        self.payments_label.align_to(balance_line,lv.ALIGN.OUT_BOTTOM_LEFT, 2, 10)
        self.update_payments_label_font()
        self.payments_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.1)) # leave a small gap to the QR
        # Force word-wrap so payment lines that exceed the label width don't
        # bleed into the QR code area on the right.
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
        settings_button = lv.obj(self.main_screen)
        settings_button.set_size(40, 40)
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        settings_button.add_flag(lv.obj.FLAG.CLICKABLE)
        settings_button.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        settings_button.set_style_border_width(0, lv.PART.MAIN)
        settings_button.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        settings_icon = lv.label(settings_button)
        settings_icon.set_text(lv.SYMBOL.SETTINGS)
        settings_icon.set_style_text_font(lv.font_montserrat_18, lv.PART.MAIN)
        settings_icon.set_style_text_color(self._icon_color(), lv.PART.MAIN)
        settings_icon.center()
        focusgroup = lv.group_get_default()
        if focusgroup:
            focusgroup.add_obj(settings_button)

        # Track wallet-mode widgets so they can be hidden/shown as a group
        self.wallet_container_widgets = [balance_line, self.balance_label, self.receive_qr, self.lightning_bolt, self.chain_link, self.payments_label, self.hero_container, settings_button]

        # === Welcome Screen (shown when wallet is not configured) ===
        self.welcome_container = lv.obj(self.main_screen)
        self.welcome_container.set_size(lv.pct(100), lv.pct(100))
        self.welcome_container.set_style_border_width(0, lv.PART.MAIN)
        self.welcome_container.set_style_pad_all(DisplayMetrics.pct_of_width(5), lv.PART.MAIN)
        self.welcome_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        self.welcome_container.set_flex_align(lv.FLEX_ALIGN.START, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.welcome_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.welcome_container.add_flag(lv.obj.FLAG.HIDDEN)

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
        # Let splash background follow the theme (don't hardcode white)
        self.splash_container.set_style_bg_opa(lv.OPA.COVER, lv.PART.MAIN)
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

        # ESP32 BOOT button (GPIO0) — short press swaps active wallet (no-op if only
        # one configured), long press opens Settings. Silently no-ops on platforms
        # without machine.Pin (desktop build).
        self._start_boot_button_watcher()

    def onResume(self, main_screen):
        super().onResume(main_screen)
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
            # If the user changed wallet_type or the active slot in Settings, stop the old
            # wallet and reconnect with the new one so we don't show stale data.
            current_slot = self.prefs.get_string("active_wallet_slot", "1")
            current_suffix = "_2" if current_slot == "2" else ""
            current_wallet_type = self.prefs.get_string("wallet_type" + current_suffix)
            current_key = (current_wallet_type, current_slot)
            wallet_was_swapped = False
            if (self.wallet and self.wallet.is_running()
                    and getattr(self, '_active_wallet_key', None) != current_key):
                print("wallet changed from {} to {} — restarting wallet".format(
                    getattr(self, '_active_wallet_key', None), current_key))
                self.wallet.stop()
                self.wallet = None
                self._active_wallet_key = None
                # Clear stale UI so the previous wallet's data doesn't linger
                if hasattr(self, '_last_balance'):
                    del self._last_balance
                self.receive_qr_data = None
                self.payments_label.set_text("")
                self.balance_label.set_text(lv.SYMBOL.REFRESH)
                wallet_was_swapped = True
            if self.wallet and self.wallet.is_running():
                # Wallet already running — just redisplay, no re-fetch
                if hasattr(self, '_last_balance'):
                    self.display_balance(self._last_balance)
                if self.wallet.payment_list and len(self.wallet.payment_list) > 0:
                    self.payments_label.set_text(str(self.wallet.payment_list))
            else:
                # Wallet not running — reconnect. If we just swapped to a new
                # slot, paint its cached balance/payments/QR first so the user
                # sees instant feedback instead of a refresh spinner while the
                # new wallet's first network fetch runs (onchain Blockbook is
                # 30-60s). Mirrors the BOOT-button path in _restart_active_wallet.
                if wallet_was_swapped:
                    self._load_and_display_cache()
                self._apply_qr_theme()
                self.network_changed(cm.is_online())

    def onPause(self, main_screen):
        if self.wallet and self.destination not in (FullscreenQR, MainSettingsActivity):
            self.wallet.stop() # don't stop the wallet for fullscreen QR or settings
        self.destination = None
        cm = ConnectivityManager.get()
        cm.unregister_callback(self.network_changed)

    def onDestroy(self, main_screen):
        # Stop the BOOT-button watcher task (no-op if it never started).
        self._boot_button_keep_running = False
        # would be good to cleanup lv.layer_top() of those confetti images

    # ---- ESP32 BOOT button (GPIO0) handling ----------------------------------

    _BOOT_LONG_PRESS_MS = 800
    _BOOT_DEBOUNCE_MS = 30

    def _start_boot_button_watcher(self):
        """Wire up GPIO0 (BOOT button) for short/long press detection."""
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
        """Polling watcher with short/long press detection. Runs until onDestroy."""
        pin = self._boot_button_pin
        debounce_s = self._BOOT_DEBOUNCE_MS / 1000
        while self._boot_button_keep_running:
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
            await TaskManager.sleep(0.05)

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
        fire network_changed to start the new wallet.

        Mirrors the swap path in onResume — used when the swap is triggered from
        outside the Settings round-trip (e.g. by the BOOT button).
        """
        if self.wallet:
            self.wallet.stop()
        self.wallet = None
        self._active_wallet_key = None
        if hasattr(self, '_last_balance'):
            del self._last_balance
        self.receive_qr_data = None
        self.payments_label.set_text("")
        self.balance_label.set_text(lv.SYMBOL.REFRESH)
        # Show the new slot's cached values immediately so the user doesn't
        # stare at a refresh spinner during the (sometimes 30-60s) Blockbook fetch.
        self._load_and_display_cache()
        # Picks up new slot's hero + wallet-type icon
        self._update_hero_image()
        cm = ConnectivityManager.get()
        self.network_changed(cm.is_online())

    def network_changed(self, online):
        print("displaywallet.py network_changed, now:", "ONLINE" if online else "OFFLINE")
        if online:
            self.went_online()
        else:
            self.went_offline()

    def _active_slot_and_suffix(self):
        """Return (slot_str, suffix) for the currently active wallet slot.

        Falls back to slot 1 if slot 2 is active but unconfigured.
        """
        slot = self.prefs.get_string("active_wallet_slot", "1")
        if slot == "2" and not self.prefs.get_string("wallet_type_2"):
            print("Active slot 2 not configured, falling back to slot 1")
            editor = self.prefs.edit()
            editor.put_string("active_wallet_slot", "1")
            editor.commit()
            slot = "1"
        return slot, ("_2" if slot == "2" else "")

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
        if wallet_type == "lnbits":
            try:
                self.wallet = LNBitsWallet(self.prefs.get_string("lnbits_url" + s), self.prefs.get_string("lnbits_readkey" + s))
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
                self.wallet.static_receive_code = self.prefs.get_string("onchain_static_receive_code" + s)
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize On-chain wallet because: {e}")
                return
        else:
            self.error_cb(f"No or unsupported wallet type configured: '{wallet_type}'")
            return
        # Tag the wallet with its slot so cache reads/writes namespace correctly
        # (slot 1 uses unsuffixed cache keys for back-compat; slot 2 uses _2).
        self.wallet.slot = int(slot)
        # Remember (wallet_type, slot) so onResume can detect either-dimension changes.
        self._active_wallet_key = (wallet_type, slot)
        if not (hasattr(self, '_last_balance') and self._last_balance):
            self.balance_label.set_text(lv.SYMBOL.REFRESH)
            self.payments_label.set_text(f"\nConnecting to {wallet_type} backend.\n\nIf this takes too long, it might be down or something's wrong with the settings.")
        # by now, self.wallet can be assumed
        self.wallet.start(self.balance_updated_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb, self.error_cb)

    def went_offline(self):
        # Check the ACTIVE slot's wallet_type, not slot 1's: a user on slot 2
        # with slot 1 unconfigured would otherwise see the welcome screen
        # instead of the offline message. Mirrors the pattern in went_online.
        _, s = self._active_slot_and_suffix()
        if not self.prefs.get_string("wallet_type" + s):
            self.show_welcome_screen()
            return
        if self.wallet:
            self.wallet.stop()
        # Don't overwrite cached data with offline message
        if not (hasattr(self, '_last_balance') and self._last_balance):
            self.payments_label.set_text(f"WiFi is not connected, can't talk to wallet...")

    def show_welcome_screen(self):
        """Hide wallet widgets, show welcome container."""
        for w in self.wallet_container_widgets:
            w.add_flag(lv.obj.FLAG.HIDDEN)
        self.welcome_container.remove_flag(lv.obj.FLAG.HIDDEN)
        WidgetAnimator.show_widget(self.welcome_container)

    def show_wallet_screen(self):
        """Hide welcome container, show wallet widgets."""
        self.welcome_container.add_flag(lv.obj.FLAG.HIDDEN)
        for w in self.wallet_container_widgets:
            w.remove_flag(lv.obj.FLAG.HIDDEN)
        # Re-apply conditional visibility (blanket un-hide above ignores wallet type)
        self._update_lightning_indicator()

    def _splash_done(self, timer):
        """Called after splash duration. Fade out splash and show appropriate screen."""
        WidgetAnimator.hide_widget(self.splash_container, duration=500)
        # Show cached data immediately while waiting for network
        self._load_and_display_cache()
        cm = ConnectivityManager.get()
        self.network_changed(cm.is_online())

    def _load_and_display_cache(self):
        """Load and display the active slot's cached wallet data immediately."""
        slot, s = self._active_slot_and_suffix()
        if not self.prefs.get_string("wallet_type" + s):
            return  # active slot has no wallet configured, nothing to show
        self.show_wallet_screen()
        slot_int = int(slot)
        cached_balance = wallet_cache.load_cached_balance(slot=slot_int)
        if cached_balance is not None:
            print("Cache: displaying cached balance {} (slot {})".format(cached_balance, slot_int))
            self.display_balance(cached_balance)
        cached_payments = wallet_cache.load_cached_payments(slot=slot_int)
        if cached_payments is not None and len(cached_payments) > 0:
            print("Cache: displaying {} cached payments (slot {})".format(len(cached_payments), slot_int))
            self.payments_label.set_text(str(cached_payments))
        cached_receive_code = wallet_cache.load_cached_static_receive_code(slot=slot_int)
        if cached_receive_code:
            print("Cache: displaying cached QR code (slot {})".format(slot_int))
            self.receive_qr_data = cached_receive_code
            self.receive_qr.update(cached_receive_code, len(cached_receive_code))

    def _icon_color(self):
        """Return icon color based on current theme."""
        if not AppearanceManager.is_light_mode():
            return lv.color_white()
        return lv.color_black()

    def _hero_image_key(self):
        """Hero image is per-wallet-slot: 'hero_image' for slot 1, 'hero_image_2' for slot 2."""
        return "hero_image" + ("_2" if self.prefs.get_string("active_wallet_slot", "1") == "2" else "")

    def _active_wallet_type(self):
        slot = self.prefs.get_string("active_wallet_slot", "1")
        return self.prefs.get_string("wallet_type" + ("_2" if slot == "2" else ""))

    def _update_lightning_indicator(self):
        """Show the wallet-type icon: yellow ⚡ for Lightning, pink chain-link for on-chain."""
        wt = self._active_wallet_type()
        if wt in ("lnbits", "nwc"):
            self.lightning_bolt.remove_flag(lv.obj.FLAG.HIDDEN)
            self.chain_link.add_flag(lv.obj.FLAG.HIDDEN)
        elif wt == "onchain":
            self.lightning_bolt.add_flag(lv.obj.FLAG.HIDDEN)
            self.chain_link.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.lightning_bolt.add_flag(lv.obj.FLAG.HIDDEN)
            self.chain_link.add_flag(lv.obj.FLAG.HIDDEN)

    def _update_hero_image(self):
        """Show or hide the hero image based on settings for the active slot."""
        self._update_lightning_indicator()
        hero = self.prefs.get_string(self._hero_image_key(), "lightningpiggy")
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

    def _on_hero_image_changed(self, new_value):
        """Called when hero image setting changes."""
        self._update_hero_image()

    def _qr_colors(self):
        """Return (dark_color, light_color) tuple based on current theme."""
        if not AppearanceManager.is_light_mode():
            return (lv.color_white(), lv.color_hex(0x15171A))
        return (lv.color_black(), lv.color_white())

    def _apply_qr_theme(self):
        """Reapply QR colors and symbol when returning from settings."""
        dark, light = self._qr_colors()
        self.receive_qr.set_dark_color(dark)
        self.receive_qr.set_light_color(light)
        self.receive_qr.set_style_border_color(light, lv.PART.MAIN)
        if self.receive_qr_data:
            self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data))
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

    def _denom_key(self):
        """Balance denomination is per-wallet-slot: 'balance_denomination' for slot 1, '_2' for slot 2."""
        return "balance_denomination" + ("_2" if self.prefs.get_string("active_wallet_slot", "1") == "2" else "")

    def display_balance(self, balance):
         self._last_balance = balance
         denom = self.prefs.get_string(self._denom_key(), "sats")
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

        # Mark as connected even if balance == 0
        if getattr(self.wallet, "payment_list", None) is not None:
            if len(self.wallet.payment_list) == 0:
                # Don't overwrite cached payments with "no payments" message
                cached = wallet_cache.load_cached_payments(slot=self.wallet.slot)
                if cached and len(cached) > 0:
                    self.payments_label.set_text(str(cached))
                else:
                    self.payments_label.set_text("Connected.\nNo payments yet.")
            else:
                self.payments_label.set_text(str(self.wallet.payment_list))
        else:
            self.payments_label.set_text("Connected.")

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
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        self.payments_label.set_text(str(self.wallet.payment_list))

    def redraw_static_receive_code_cb(self):
        # static receive code from settings takes priority (for the active slot):
        slot = self.prefs.get_string("active_wallet_slot", "1")
        s = "_2" if slot == "2" else ""
        wallet_type = self.prefs.get_string("wallet_type" + s)
        if wallet_type == "nwc":
            self.receive_qr_data = self.prefs.get_string("nwc_static_receive_code" + s)
        elif wallet_type == "lnbits":
            self.receive_qr_data = self.prefs.get_string("lnbits_static_receive_code" + s)
        elif wallet_type == "onchain":
            self.receive_qr_data = self.prefs.get_string("onchain_static_receive_code" + s)
        # otherwise, see if the wallet has a static receive code:
        if not self.receive_qr_data:
            self.receive_qr_data = self.wallet.static_receive_code
        if not self.receive_qr_data:
            print("Warning: redraw_static_receive_code_cb() did not find one in the settings or the wallet, nothing to show")
            return
        self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data))

    def error_cb(self, error):
        if self.wallet and self.wallet.is_running():
            # Don't overwrite cached payments with error if we have cached data
            if hasattr(self, '_last_balance') and self._last_balance:
                print(f"WARNING: {error} (keeping cached data on screen)")
            else:
                self.payments_label.set_text(str(error))

    _WALLET_TYPE_PRETTY = {
        "lnbits": "LNBits",
        "nwc": "Nostr Wallet Connect",
        "onchain": "On-chain",
    }

    def settings_button_tap(self, event):
        self.destination = MainSettingsActivity  # prevent wallet.stop() in onPause
        intent = Intent(activity_class=MainSettingsActivity)
        intent.putExtra("prefs", self.prefs)

        active_slot = self.prefs.get_string("active_wallet_slot", "1")
        active_suffix = "_2" if active_slot == "2" else ""
        active_type = self.prefs.get_string("wallet_type" + active_suffix)
        # Slot 2 is "configured" if its wallet_type is set; slot 1 is always considered present.
        has_slot2 = bool(self.prefs.get_string("wallet_type_2"))
        # The "other" slot is whichever one isn't active
        other_slot = "2" if active_slot == "1" else "1"
        other_suffix = "_2" if other_slot == "2" else ""
        other_type = self.prefs.get_string("wallet_type" + other_suffix)

        wallet_settings = [
            # Single Wallet entry — always edits the active slot
            {"title": "Wallet", "key": "wallet_type" + active_suffix, "ui": "activity",
             "activity_class": WalletSettingsActivity,
             "_slot": int(active_slot),
             "placeholder": active_type or "not configured"},
            {"title": "Customise", "key": "customise", "ui": "activity",
             "activity_class": CustomiseSettingsActivity,
             "placeholder": "Balance denomination, hero image",
             "_callbacks": {"denomination": self._on_denomination_changed, "hero_image": self._on_hero_image_changed}},
            {"title": "Screen Lock", "key": "screen_lock", "activity_class": True,
             "placeholder": "On - tapping disabled" if self.prefs.get_string("screen_lock", "off") == "on" else "Off - tapping changes display"},
        ]

        if has_slot2:
            # Two wallets configured — bottom entry switches active slot
            other_pretty = self._WALLET_TYPE_PRETTY.get(other_type, other_type or "other wallet")
            wallet_settings.append({
                "title": "Switch to " + other_pretty, "key": "__switch_active_wallet",
                "activity_class": True,
                "placeholder": "",
            })
        else:
            # One wallet — bottom entry adds a second
            wallet_settings.append({
                "title": "Add wallet", "key": "wallet_type_2", "ui": "activity",
                "activity_class": WalletSettingsActivity,
                "_slot": 2,
                "placeholder": "Configure a second wallet",
            })

        intent.putExtra("settings", wallet_settings)
        self.startActivity(intent)

    HERO_CYCLE = ["lightningpiggy", "lightningpenguin", "none"]
    DENOMINATION_CYCLE = ["sats", "symbol", "bits", "ubtc", "mbtc", "btc"]

    def _is_screen_locked(self):
        return self.prefs.get_string("screen_lock", "off") == "on"

    def hero_image_clicked_cb(self, event):
        """Cycle through hero images on tap (for the active wallet slot)."""
        if self._is_screen_locked():
            return
        key = self._hero_image_key()
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
        """Cycle through balance denominations on tap (for the active wallet slot)."""
        if self._is_screen_locked():
            return
        key = self._denom_key()
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
        self.payments_label.set_text(lv.SYMBOL.REFRESH)

    def qr_clicked_cb(self, event):
        print("QR clicked")
        if self._is_screen_locked():
            return
        if not self.receive_qr_data:
            return
        self.destination = FullscreenQR
        self.startActivity(Intent(activity_class=self.fullscreenqr).putExtra("receive_qr_data", self.receive_qr_data))
