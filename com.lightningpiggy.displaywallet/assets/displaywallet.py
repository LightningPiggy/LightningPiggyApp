import lvgl as lv

from mpos import Activity, Intent, ConnectivityManager, MposKeyboard, DisplayMetrics, SharedPreferences, SettingsActivity, WidgetAnimator

from confetti import Confetti
from fullscreen_qr import FullscreenQR

# Import wallet modules at the top so they're available when sys.path is restored
# This prevents ImportError when switching wallet types after the app has started
from lnbits_wallet import LNBitsWallet
from nwc_wallet import NWCWallet

class DisplayWallet(Activity):

    wallet = None
    receive_qr_data = None
    destination = None
    receive_qr_pct_of_display = 30 # could be a setting
    balance_mode = 0  # 0=sats, 1=bits, 2=μBTC, 3=mBTC, 4=BTC
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
        self.main_screen.set_style_pad_all(0, lv.PART.MAIN)
        # This line needs to be drawn first, otherwise it's over the balance label and steals all the clicks!
        balance_line = lv.line(self.main_screen)
        balance_line.set_points([{'x':0,'y':35},{'x':DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display*1.2),'y':35}],2)
        balance_line.add_flag(lv.obj.FLAG.CLICKABLE)
        balance_line.add_event_cb(self.send_button_tap,lv.EVENT.CLICKED,None)
        self.balance_label = lv.label(self.main_screen)
        self.balance_label.set_text("")
        self.balance_label.align(lv.ALIGN.TOP_LEFT, 0, 0)
        self.balance_label.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        self.balance_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.balance_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display)) # 100 - receive_qr
        self.balance_label.add_event_cb(self.balance_label_clicked_cb,lv.EVENT.CLICKED,None)
        self.receive_qr = lv.qrcode(self.main_screen)
        self.receive_qr.set_size(DisplayMetrics.pct_of_width(self.receive_qr_pct_of_display)) # bigger QR results in simpler code (less error correction?)
        self.receive_qr.set_dark_color(lv.color_black())
        self.receive_qr.set_light_color(lv.color_white())
        self.receive_qr.align(lv.ALIGN.TOP_RIGHT,0,0)
        self.receive_qr.set_style_border_color(lv.color_white(), lv.PART.MAIN)
        self.receive_qr.set_style_border_width(8, lv.PART.MAIN);
        self.receive_qr.add_flag(lv.obj.FLAG.CLICKABLE)
        self.receive_qr.add_event_cb(self.qr_clicked_cb,lv.EVENT.CLICKED,None)
        self.payments_label = lv.label(self.main_screen)
        self.payments_label.set_text("")
        self.payments_label.align_to(balance_line,lv.ALIGN.OUT_BOTTOM_LEFT, 0, 10)
        self.update_payments_label_font()
        self.payments_label.set_width(DisplayMetrics.pct_of_width(100-self.receive_qr_pct_of_display)) # 100 - receive_qr
        self.payments_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.payments_label.add_event_cb(self.payments_label_clicked,lv.EVENT.CLICKED,None)
        settings_button = lv.button(self.main_screen)
        settings_button.set_size(lv.pct(20), lv.pct(25))
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        settings_label = lv.label(settings_button)
        settings_label.set_text(lv.SYMBOL.SETTINGS)
        settings_label.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        settings_label.center()
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
        self.welcome_container.set_flex_align(lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER, lv.FLEX_ALIGN.CENTER)
        self.welcome_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        self.welcome_container.add_flag(lv.obj.FLAG.HIDDEN)

        welcome_title = lv.label(self.welcome_container)
        welcome_title.set_text("Lightning Piggy")
        welcome_title.set_style_text_font(lv.font_montserrat_24, lv.PART.MAIN)
        welcome_title.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)

        welcome_subtitle = lv.label(self.welcome_container)
        welcome_subtitle.set_text("An electronic piggy bank that accepts\nBitcoin sent over lightning")
        welcome_subtitle.set_style_text_font(lv.font_montserrat_12, lv.PART.MAIN)
        welcome_subtitle.set_style_text_color(lv.color_hex(0x888888), lv.PART.MAIN)
        welcome_subtitle.set_long_mode(lv.label.LONG_MODE.WRAP)
        welcome_subtitle.set_width(lv.pct(90))
        welcome_subtitle.set_style_text_align(lv.TEXT_ALIGN.CENTER, lv.PART.MAIN)

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

        welcome_qr_label = lv.label(self.welcome_container)
        welcome_qr_label.set_text("Scan for more info:")
        welcome_qr_label.set_style_text_font(lv.font_montserrat_10, lv.PART.MAIN)
        welcome_qr_label.set_style_text_color(lv.color_hex(0x888888), lv.PART.MAIN)
        welcome_qr_label.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)

        welcome_qr = lv.qrcode(self.welcome_container)
        welcome_qr.set_size(round(DisplayMetrics.min_dimension() * 0.25))
        welcome_qr.set_dark_color(lv.color_black())
        welcome_qr.set_light_color(lv.color_white())
        welcome_qr.set_style_border_color(lv.color_white(), lv.PART.MAIN)
        welcome_qr.set_style_border_width(4, lv.PART.MAIN)
        welcome_url = "https://lightningpiggy.com/build"
        welcome_qr.update(welcome_url, len(welcome_url))

        welcome_setup_btn = lv.button(self.welcome_container)
        welcome_setup_btn.set_size(lv.pct(60), lv.SIZE_CONTENT)
        welcome_setup_btn.set_style_margin_top(DisplayMetrics.pct_of_height(2), lv.PART.MAIN)
        welcome_setup_btn.add_event_cb(self.settings_button_tap, lv.EVENT.CLICKED, None)
        welcome_setup_label = lv.label(welcome_setup_btn)
        welcome_setup_label.set_text(lv.SYMBOL.SETTINGS + " Setup")
        welcome_setup_label.set_style_text_font(lv.font_montserrat_16, lv.PART.MAIN)
        welcome_setup_label.center()

        self.setContentView(self.main_screen)

    def onStart(self, main_screen):
        self.main_ui_set_defaults()

        # Initialize Confetti
        self.confetti = Confetti(main_screen, self.ICON_PATH, self.ASSET_PATH, self.confetti_duration)

    def onResume(self, main_screen):
        super().onResume(main_screen)
        cm = ConnectivityManager.get()
        cm.register_callback(self.network_changed)
        self.network_changed(cm.is_online())

    def onPause(self, main_screen):
        if self.wallet and self.destination != FullscreenQR:
            self.wallet.stop() # don't stop the wallet for the fullscreen QR activity
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
        self.balance_label.set_text(lv.SYMBOL.REFRESH)
        self.payments_label.set_text(f"\nConnecting to {wallet_type} backend.\n\nIf this takes too long, it might be down or something's wrong with the settings.")
        # by now, self.wallet can be assumed
        self.wallet.start(self.balance_updated_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb, self.error_cb)

    def went_offline(self):
        if not self.prefs.get_string("wallet_type"):
            self.show_welcome_screen()
            return
        if self.wallet:
            self.wallet.stop() # don't stop the wallet for the fullscreen QR activity
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

    def update_payments_label_font(self):
        self.payments_label.set_style_text_font(self.payments_label_fonts[self.payments_label_current_font], lv.PART.MAIN)

    def payments_label_clicked(self, event):
        self.payments_label_current_font = (self.payments_label_current_font + 1) % len(self.payments_label_fonts)
        self.update_payments_label_font()

    def float_to_string(self, value, decimals):
        # Format float to string with fixed-point notation and specified decimal places
        s = "{:.{}f}".format(value, decimals)
        # Remove trailing zeros and decimal point if no decimals remain
        return s.rstrip("0").rstrip(".")

    def display_balance(self, balance):
         #print(f"displaying balance {balance}")
         if self.balance_mode == 0:  # sats
             #balance_text = "丰 " + str(balance) # font doesnt support it
             balance_text = str(int(round(balance))) + " sat"
             if balance > 1:
                 balance_text += "s"
         elif self.balance_mode == 1:  # bits (1 bit = 100 sats)
             balance_bits = round(balance / 100, 2)
             balance_text = self.float_to_string(balance_bits, 2) + " bit"
             if balance_bits != 1:
                 balance_text += "s"
         elif self.balance_mode == 2:  # micro-BTC (1 μBTC = 100 sats)
             balance_ubtc = round(balance / 100, 2)
             balance_text = self.float_to_string(balance_ubtc, 2) + " micro-BTC"
         elif self.balance_mode == 3:  # milli-BTC (1 mBTC = 100000 sats)
             balance_mbtc = round(balance / 100000, 5)
             balance_text = self.float_to_string(balance_mbtc, 5) + " milli-BTC"
         elif self.balance_mode == 4:  # BTC (1 BTC = 100000000 sats)
             balance_btc = round(balance / 100000000, 8)
             #balance_text = "₿ " + str(balance) # font doesnt support it - although it should https://fonts.google.com/specimen/Montserrat
             balance_text = self.float_to_string(balance_btc, 8) + " BTC"
         self.balance_label.set_text(balance_text)
         #print("done displaying balance")

    def balance_updated_cb(self, sats_added=0):
        print(f"balance_updated_cb(sats_added={sats_added})")
        if self.fullscreenqr.has_foreground():
            self.fullscreenqr.finish()
        if sats_added > 0:
            self.confetti.start()
        balance = self.wallet.last_known_balance
        print(f"balance: {balance}")
        if balance is not None:
            WidgetAnimator.change_widget(self.balance_label, anim_type="interpolate", duration=self.confetti_duration, delay=0, begin_value=balance-sats_added, end_value=balance, display_change=self.display_balance)
        else:
            print("Not drawing balance because it's None")
    
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
            self.payments_label.set_text(str(error))

    def send_button_tap(self, event):
        print("send_button clicked")
        self.confetti.start() # for testing the receive animation

    def should_show_setting(self, setting):
        if setting["key"] == "wallet_type":
            return True
        wallet_type = self.prefs.get_string("wallet_type")
        if wallet_type != "lnbits" and setting["key"].startswith("lnbits_"):
            return False
        if wallet_type != "nwc" and setting["key"].startswith("nwc_"):
            return False
        return True

    def settings_button_tap(self, event):
        intent = Intent(activity_class=SettingsActivity)
        intent.putExtra("prefs", self.prefs)
        intent.putExtra("settings", [
            {"title": "Wallet Type", "key": "wallet_type", "ui": "radiobuttons", "ui_options": [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc")]},
            {"title": "LNBits URL", "key": "lnbits_url", "placeholder": "https://demo.lnpiggy.com", "should_show": self.should_show_setting},
            {"title": "LNBits Read Key", "key": "lnbits_readkey", "placeholder": "fd92e3f8168ba314dc22e54182784045", "should_show": self.should_show_setting},
            {"title": "Optional LN Address", "key": "lnbits_static_receive_code", "placeholder": "Will be fetched if empty.", "should_show": self.should_show_setting},
            {"title": "Nost Wallet Connect", "key": "nwc_url", "placeholder": "nostr+walletconnect://69effe7b...", "should_show": self.should_show_setting},
            {"title": "Optional LN Address", "key": "nwc_static_receive_code", "placeholder": "Optional if present in NWC URL.", "should_show": self.should_show_setting},
        ])
        self.startActivity(intent)

    def main_ui_set_defaults(self):
        self.balance_label.set_text("Welcome!")
        self.payments_label.set_text(lv.SYMBOL.REFRESH)

    def balance_label_clicked_cb(self, event):
         print("Balance clicked")
         self.balance_mode = (self.balance_mode + 1) % 5
         self.display_balance(self.wallet.last_known_balance)

    def qr_clicked_cb(self, event):
        print("QR clicked")
        if not self.receive_qr_data:
            return
        self.destination = FullscreenQR
        self.startActivity(Intent(activity_class=self.fullscreenqr).putExtra("receive_qr_data", self.receive_qr_data))
