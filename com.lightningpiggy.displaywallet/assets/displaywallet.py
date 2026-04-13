import lvgl as lv

from mpos import Activity, AppearanceManager, Intent, ConnectivityManager, MposKeyboard, NumberFormat, DisplayMetrics, SharedPreferences, SettingsActivity, WidgetAnimator

from confetti import Confetti
from fullscreen_qr import FullscreenQR
from payment import Payment
import wallet_cache

# Import wallet modules at the top so they're available when sys.path is restored
# This prevents ImportError when switching wallet types after the app has started
from lnbits_wallet import LNBitsWallet
from nwc_wallet import NWCWallet


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


class MainSettingsActivity(SettingsActivity):
    """Settings screen with a back-to-display button."""
    def onResume(self, screen):
        super().onResume(screen)
        _add_floating_back_button(screen, self.finish)


class DenominationSettingsActivity(Activity):
    """Custom denomination picker with 2-column radio button layout."""
    DENOMINATIONS = [
        ("sats", "sats"),
        ("   sats", "symbol"),  # ₿ image added separately
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
            if value == "symbol":
                # Add ₿ image next to the checkbox text
                if not AppearanceManager.is_light_mode():
                    symbol_path = "M:apps/com.lightningpiggy.displaywallet/res/drawable-mdpi/bitcoin_symbol_white_small.png"
                else:
                    symbol_path = "M:apps/com.lightningpiggy.displaywallet/res/drawable-mdpi/bitcoin_symbol_black_small.png"
                symbol_img = lv.image(cb)
                symbol_img.set_src(symbol_path)
                symbol_img.set_pos(22, 4)
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
        self.main_screen = lv.obj()
        if not AppearanceManager.is_light_mode():
            self.main_screen.set_style_bg_color(lv.color_hex(0x15171A), lv.PART.MAIN)
        else:
            self.main_screen.set_style_bg_color(lv.color_white(), lv.PART.MAIN)
        self.main_screen.set_style_pad_all(0, lv.PART.MAIN)
        # This line needs to be drawn first, otherwise it's over the balance label and steals all the clicks!
        balance_line = lv.line(self.main_screen)
        balance_line.set_points([{'x':2,'y':35},{'x':DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.2),'y':35}],2)
        balance_line.add_flag(lv.obj.FLAG.CLICKABLE)
        balance_line.add_event_cb(self.send_button_tap,lv.EVENT.CLICKED,None)
        self.balance_label = lv.label(self.main_screen)
        self.balance_label.set_text("")
        self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
        self.balance_label.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        self.balance_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.balance_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display)) # 100 - receive_qr
        # Balance denomination is now set via settings, not by tapping
        self.bitcoin_symbol = lv.image(self.main_screen)
        self.bitcoin_symbol.set_src(self._bitcoin_symbol_path())
        self.bitcoin_symbol.align(lv.ALIGN.TOP_LEFT, 2, 4)
        self.bitcoin_symbol.add_flag(lv.obj.FLAG.HIDDEN)
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
        settings_button = lv.obj(self.main_screen)
        settings_button.set_size(50, 50)
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        settings_button.add_flag(lv.obj.FLAG.CLICKABLE)
        settings_button.set_style_bg_opa(lv.OPA.TRANSP, lv.PART.MAIN)
        settings_button.set_style_border_width(0, lv.PART.MAIN)
        settings_button.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        settings_icon = lv.label(settings_button)
        settings_icon.set_text(lv.SYMBOL.SETTINGS)
        settings_icon.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        settings_icon.set_style_text_color(self._icon_color(), lv.PART.MAIN)
        settings_icon.center()
        focusgroup = lv.group_get_default()
        if focusgroup:
            focusgroup.add_obj(settings_button)
        if False: # send button disabled for now, not implemented
            send_button = lv.button(self.main_screen)
            send_button.set_size(lv.pct(20), lv.pct(25))
            send_button.align_to(settings_button, lv.ALIGN.OUT_TOP_MID, 0, -pct_of_display_height(2))
            send_button.add_event_cb(self.send_button_tap,lv.EVENT.CLICKED,None)
            send_label = lv.label(send_button)
            send_label.set_text(lv.SYMBOL.UPLOAD)
            send_label.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
            send_label.center()

        # Track wallet-mode widgets so they can be hidden/shown as a group
        self.wallet_container_widgets = [balance_line, self.balance_label, self.receive_qr, self.payments_label, settings_button]

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
            if self.wallet and self.wallet.is_running():
                # Wallet already running — just redisplay, no re-fetch
                if hasattr(self, '_last_balance'):
                    self.display_balance(self._last_balance)
                if self.wallet.payment_list and len(self.wallet.payment_list) > 0:
                    self.payments_label.set_text(str(self.wallet.payment_list))
            else:
                # Wallet not running — reconnect
                self._apply_qr_theme()
                self.network_changed(cm.is_online())

    def onPause(self, main_screen):
        if self.wallet and self.destination not in (FullscreenQR, MainSettingsActivity):
            self.wallet.stop() # don't stop the wallet for fullscreen QR or settings
        self.destination = None
        cm = ConnectivityManager.get()
        cm.unregister_callback(self.network_changed)

    def onDestroy(self, main_screen):
        pass # would be good to cleanup lv.layer_top() of those confetti images

    def network_changed(self, online):
        print("displaywallet.py network_changed, now:", "ONLINE" if online else "OFFLINE")
        if online:
            self.went_online()
        else:
            self.went_offline()

    def went_online(self):
        if self.wallet and self.wallet.is_running():
            print("wallet is already running, nothing to do") # might have come from the QR activity
            return
        wallet_type = self.prefs.get_string("wallet_type")
        if not wallet_type:
            self.show_welcome_screen()
            return # nothing is configured, nothing to do
        self.show_wallet_screen()
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
        if not (hasattr(self, '_last_balance') and self._last_balance):
            self.balance_label.set_text(lv.SYMBOL.REFRESH)
            self.payments_label.set_text(f"\nConnecting to {wallet_type} backend.\n\nIf this takes too long, it might be down or something's wrong with the settings.")
        # by now, self.wallet can be assumed
        self.wallet.start(self.balance_updated_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb, self.error_cb)

    def went_offline(self):
        if not self.prefs.get_string("wallet_type"):
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

    def _splash_done(self, timer):
        """Called after splash duration. Fade out splash and show appropriate screen."""
        WidgetAnimator.hide_widget(self.splash_container, duration=500)
        # Show cached data immediately while waiting for network
        self._load_and_display_cache()
        cm = ConnectivityManager.get()
        self.network_changed(cm.is_online())

    def _load_and_display_cache(self):
        """Load cached wallet data and display it immediately."""
        if not self.prefs.get_string("wallet_type"):
            return  # no wallet configured, nothing to show
        self.show_wallet_screen()
        cached_balance = wallet_cache.load_cached_balance()
        if cached_balance is not None:
            print(f"Cache: displaying cached balance {cached_balance}")
            self.display_balance(cached_balance)
        cached_payments = wallet_cache.load_cached_payments()
        if cached_payments is not None and len(cached_payments) > 0:
            print(f"Cache: displaying {len(cached_payments)} cached payments")
            self.payments_label.set_text(str(cached_payments))
        cached_receive_code = wallet_cache.load_cached_static_receive_code()
        if cached_receive_code:
            print(f"Cache: displaying cached QR code")
            self.receive_qr_data = cached_receive_code
            self.receive_qr.update(cached_receive_code, len(cached_receive_code))

    def _icon_color(self):
        """Return icon color based on current theme."""
        if not AppearanceManager.is_light_mode():
            return lv.color_white()
        return lv.color_black()

    def _bitcoin_symbol_path(self):
        """Return path to theme-appropriate Bitcoin symbol image."""
        if not AppearanceManager.is_light_mode():
            return f"{self.ASSET_PATH}bitcoin_symbol_white.png"
        return f"{self.ASSET_PATH}bitcoin_symbol_black.png"

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
        # Refresh bitcoin symbol and re-render balance (setting or theme may have changed)
        self.bitcoin_symbol.set_src(self._bitcoin_symbol_path())
        if hasattr(self, '_last_balance'):
            self.display_balance(self._last_balance)

    def update_payments_label_font(self):
        self.payments_label.set_style_text_font(self.payments_label_fonts[self.payments_label_current_font], lv.PART.MAIN)

    def payments_label_clicked(self, event):
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
         if denom in ("sats", "symbol"):
             sats = int(round(balance))
             formatted = NumberFormat.format_number(sats) if _has_number_format else str(sats)
             if denom == "symbol":
                 balance_text = formatted
                 self.bitcoin_symbol.set_src(self._bitcoin_symbol_path())
                 self.bitcoin_symbol.remove_flag(lv.obj.FLAG.HIDDEN)
                 self.balance_label.align(lv.ALIGN.TOP_LEFT, 24, 0)
             else:
                 balance_text = formatted + (" sat" if sats == 1 else " sats")
                 self.bitcoin_symbol.add_flag(lv.obj.FLAG.HIDDEN)
                 self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
         elif denom == "bits":
             self.bitcoin_symbol.add_flag(lv.obj.FLAG.HIDDEN)
             self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
             balance_bits = round(balance / 100, 2)
             balance_text = self.float_to_string(balance_bits, 2) + " bit"
             if balance_bits != 1:
                 balance_text += "s"
         elif denom == "ubtc":
             self.bitcoin_symbol.add_flag(lv.obj.FLAG.HIDDEN)
             self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
             balance_ubtc = round(balance / 100, 2)
             balance_text = self.float_to_string(balance_ubtc, 2) + " micro-BTC"
         elif denom == "mbtc":
             self.bitcoin_symbol.add_flag(lv.obj.FLAG.HIDDEN)
             self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
             balance_mbtc = round(balance / 100000, 5)
             balance_text = self.float_to_string(balance_mbtc, 5) + " milli-BTC"
         elif denom == "btc":
             self.bitcoin_symbol.add_flag(lv.obj.FLAG.HIDDEN)
             self.balance_label.align(lv.ALIGN.TOP_LEFT, 2, 0)
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
                cached = wallet_cache.load_cached_payments()
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
        # static receive code from settings takes priority:
        wallet_type = self.prefs.get_string("wallet_type")
        if wallet_type == "nwc":
            self.receive_qr_data = self.prefs.get_string("nwc_static_receive_code")
        elif wallet_type == "lnbits":
            self.receive_qr_data = self.prefs.get_string("lnbits_static_receive_code")
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

    def send_button_tap(self, event):
        print("send_button clicked")
        self.confetti.start() # for testing the receive animation

    def settings_button_tap(self, event):
        self.destination = MainSettingsActivity  # prevent wallet.stop() in onPause
        intent = Intent(activity_class=MainSettingsActivity)
        intent.putExtra("prefs", self.prefs)
        intent.putExtra("settings", [
            {"title": "Wallet", "key": "wallet_type", "ui": "activity",
             "activity_class": WalletSettingsActivity,
             "placeholder": self.prefs.get_string("wallet_type", "not configured")},
            {"title": "Balance Denomination", "key": "balance_denomination", "ui": "activity",
             "activity_class": DenominationSettingsActivity,
             "placeholder": self.prefs.get_string("balance_denomination", "sats"),
             "changed_callback": self._on_denomination_changed},
        ])
        self.startActivity(intent)

    def _on_denomination_changed(self, new_value):
        """Called when balance denomination setting changes."""
        if hasattr(self, '_last_balance'):
            self.display_balance(self._last_balance)

    def main_ui_set_defaults(self):
        self.balance_label.set_text("Welcome!")
        self.payments_label.set_text(lv.SYMBOL.REFRESH)

    def qr_clicked_cb(self, event):
        print("QR clicked")
        if not self.receive_qr_data:
            return
        self.destination = FullscreenQR
        self.startActivity(Intent(activity_class=self.fullscreenqr).putExtra("receive_qr_data", self.receive_qr_data))
