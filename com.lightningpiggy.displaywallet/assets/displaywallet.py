from mpos.apps import Activity, Intent
import mpos.config
import mpos.ui

from wallet import LNBitsWallet, NWCWallet
from camera_app import CameraApp

class DisplayWallet(Activity):

    wallet = None
    receive_qr_data = None
    destination = None
    balance_mode_btc = False # show BTC or sats?
    stop_receive_animation_timer = None

    # screens:
    main_screen = None

    # widgets
    balance_label = None
    receive_qr = None
    payments_label = None
    receive_animation_gif = None

    def onCreate(self):
        self.main_screen = lv.obj()
        self.main_screen.set_style_pad_all(10, 0)
        self.balance_label = lv.label(self.main_screen)
        self.balance_label.set_text("")
        self.balance_label.align(lv.ALIGN.TOP_LEFT, 0, 0)
        self.balance_label.set_style_text_font(lv.font_montserrat_26, 0)
        self.balance_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.balance_label.set_width(mpos.ui.pct_of_display_width(75)) # 100 - receive_qr
        self.balance_label.add_event_cb(self.balance_label_clicked_cb,lv.EVENT.CLICKED,None)
        self.receive_qr = lv.qrcode(self.main_screen)
        self.receive_qr.set_size(mpos.ui.pct_of_display_width(20)) # bigger QR results in simpler code (less error correction?)
        self.receive_qr.set_dark_color(lv.color_black())
        self.receive_qr.set_light_color(lv.color_white())
        self.receive_qr.align(lv.ALIGN.TOP_RIGHT,0,0)
        self.receive_qr.set_style_border_color(lv.color_white(), 0)
        self.receive_qr.set_style_border_width(1, 0);
        self.receive_qr.add_flag(lv.obj.FLAG.CLICKABLE)
        self.receive_qr.add_event_cb(self.qr_clicked_cb,lv.EVENT.CLICKED,None)
        balance_line = lv.line(self.main_screen)
        balance_line.set_points([{'x':0,'y':35},{'x':200,'y':35}],2)
        self.payments_label = lv.label(self.main_screen)
        self.payments_label.set_text("")
        self.payments_label.align_to(balance_line,lv.ALIGN.OUT_BOTTOM_LEFT,0,10)
        self.payments_label.set_style_text_font(lv.font_montserrat_16, 0)
        self.payments_label.set_width(mpos.ui.pct_of_display_width(75)) # 100 - receive_qr
        settings_button = lv.button(self.main_screen)
        settings_button.set_size(lv.pct(20), lv.pct(25))
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        settings_label = lv.label(settings_button)
        settings_label.set_text(lv.SYMBOL.SETTINGS)
        settings_label.set_style_text_font(lv.font_montserrat_26, 0)
        settings_label.center()
        send_button = lv.button(self.main_screen)
        send_button.set_size(lv.pct(20), lv.pct(25))
        send_button.align_to(settings_button, lv.ALIGN.OUT_TOP_MID, 0, -mpos.ui.pct_of_display_height(2))
        send_button.add_event_cb(self.send_button_tap,lv.EVENT.CLICKED,None)
        send_label = lv.label(send_button)
        send_label.set_text(lv.SYMBOL.UPLOAD)
        send_label.set_style_text_font(lv.font_montserrat_26, 0)
        send_label.center()
        self.setContentView(self.main_screen)

    def onStart(self, main_screen):
        self.main_ui_set_defaults()
    
    def onResume(self, main_screen):
        if self.wallet and self.wallet.is_running():
            return # wallet is already running, nothing to do
        config = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        wallet_type = config.get_string("wallet_type")
        if not wallet_type:
            self.payments_label.set_text(f"Please go into the settings\n to set a Wallet Type.")
            return # nothing is configured, nothing to do
        if wallet_type == "lnbits":
            try:
                self.wallet = LNBitsWallet(config.get_string("lnbits_url"), config.get_string("lnbits_readkey"))
            except Exception as e:
                self.payments_label.set_text(f"Couldn't initialize\nLNBits wallet because\n{e}")
                return
        elif wallet_type == "nwc":
            try:
                self.wallet = NWCWallet(config.get_string("nwc_url"))
                self.wallet.static_receive_code = config.get_string("nwc_static_receive_code")
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.payments_label.set_text(f"Couldn't initialize\nNWC Wallet because\n{e}")
                return
        else:
            self.payments_label.set_text(f"No or unsupported wallet\ntype configured: '{wallet_type}'")
            return

        can_check_network = True
        try:
            import network
        except Exception as e:
            can_check_network = False
        if can_check_network and not network.WLAN(network.STA_IF).isconnected():
            self.payments_label.set_text(f"WiFi is not connected, can't\ntalk to {wallet_type} backend.")
        else: # by now, self.wallet can be assumed
            self.balance_label.set_text(lv.SYMBOL.REFRESH)
            self.payments_label.set_text(f"Connecting\nto {wallet_type} backend...\n\nIf this takes too long, it might be\ndown or something's wrong with\nthe settings.")
            self.wallet.start(self.redraw_balance_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb)

    def onStop(self, main_screen):
        if self.wallet and self.destination != FullscreenQR:
            self.wallet.stop()
        self.destination = None
        self.stop_receive_animation()

    def float_to_string(self, value):
        # Format float to string with fixed-point notation, up to 6 decimal places
        s = "{:.8f}".format(value)
        # Remove trailing zeros and decimal point if no decimals remain
        return s.rstrip("0").rstrip(".")

    def redraw_balance_cb(self):
        print("Redrawing balance...")
        #balance_text = "Unknown Balance"
        balance = self.wallet.last_known_balance
        if balance and balance != -1:
            if self.balance_mode_btc:
                balance = balance / 100000000
                #balance_text = "₿ " + str(balance) # font doesnt support it - although it should https://fonts.google.com/specimen/Montserrat
                balance_text = self.float_to_string(balance) + " BTC"
            else:
                #balance_text = "丰 " + str(balance) # font doesnt support it
                balance_text = str(balance) + " sat"
                if balance > 1:
                    balance_text += "s"
            # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
            lv.async_call(lambda l: self.balance_label.set_text(balance_text), None)
    
    def redraw_payments_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        lv.async_call(lambda l: self.payments_label.set_text(str(self.wallet.payment_list)), None)

    def redraw_static_receive_code_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        self.receive_qr_data = self.wallet.static_receive_code
        lv.async_call(lambda l: self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data)), None)

    def send_button_tap(self, event):
        self.stop_receive_animation()
        self.receive_animation_gif = lv.gif(lv.layer_top())
        self.receive_animation_gif.add_flag(lv.obj.FLAG.HIDDEN)
        self.receive_animation_gif.set_pos(0,0)
        self.receive_animation_gif.set_src("M:data/images/raining_gold_coins2_cropped.gif")
        #self.receive_animation_gif.set_src("M:data/images/party_popper1_320x240.gif")
        mpos.ui.anim.smooth_show(self.receive_animation_gif)
        self.stop_receive_animation_timer = lv.timer_create(self.stop_receive_animation,10000,None)
        self.stop_receive_animation_timer.set_repeat_count(1)

    def stop_receive_animation(self, timer=None):
        print("Stopping receive_animation_gif")
        try:
            if self.receive_animation_gif:
                mpos.ui.anim.smooth_hide(self.receive_animation_gif)
                #self.receive_animation_gif.add_flag(lv.obj.FLAG.HIDDEN)
                #self.receive_animation_gif.set_src(None)
                #self.receive_animation_gif.delete()
        except Exception as e:
            print(f"stop_receive_animation gif delete got exception: {e}")

    def settings_button_tap(self, event):
        self.startActivity(Intent(activity_class=SettingsActivity))
    
    def main_ui_set_defaults(self):
        self.balance_label.set_text("Welcome!")
        self.payments_label.set_text(lv.SYMBOL.REFRESH)

    def balance_label_clicked_cb(self, event):
        print("Balance clicked")
        self.balance_mode_btc = not self.balance_mode_btc
        self.redraw_balance_cb()

    def qr_clicked_cb(self, event):
        print("QR clicked")
        if not self.receive_qr_data:
            return
        self.destination = FullscreenQR
        self.startActivity(Intent(activity_class=FullscreenQR).putExtra("receive_qr_data", self.receive_qr_data))

# Used to list and edit all settings:
class SettingsActivity(Activity):
    def __init__(self):
        super().__init__()
        self.prefs = None
        self.settings = [
            {"title": "Wallet Type", "key": "wallet_type", "value_label": None, "cont": None},
            {"title": "LNBits URL", "key": "lnbits_url", "value_label": None, "cont": None, "placeholder": "https://demo.lnpiggy.com"},
            {"title": "LNBits Read Key", "key": "lnbits_readkey", "value_label": None, "cont": None, "placeholder": "fd92e3f8168ba314dc22e54182784045"},
            {"title": "Optional LN Address", "key": "lnbits_static_receive_code", "value_label": None, "cont": None, "placeholder": "Will be fetched if empty."},
            {"title": "Nost Wallet Connect", "key": "nwc_url", "value_label": None, "cont": None, "placeholder": "nostr+walletconnect://69effe7b..."},
            {"title": "Optional LN Address", "key": "nwc_static_receive_code", "value_label": None, "cont": None, "placeholder": "Optional if present in NWC URL."},
        ]

    def onCreate(self):
        screen = lv.obj()
        print("creating SettingsActivity ui...")
        screen.set_style_pad_all(mpos.ui.pct_of_display_width(2), 0)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, 0)
        self.setContentView(screen)

    def onResume(self, screen):
        # reload settings because the SettingsActivity might have changed them - could be optimized to only load if it did:
        self.prefs = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        wallet_type = self.prefs.get_string("wallet_type")

        # Create settings entries
        screen.clean()
        for setting in self.settings:
            if wallet_type != "lnbits" and setting["key"].startswith("lnbits_"):
                continue
            if wallet_type != "nwc" and setting["key"].startswith("nwc_"):
                continue
            # Container for each setting
            setting_cont = lv.obj(screen)
            setting_cont.set_width(lv.pct(100))
            setting_cont.set_height(lv.SIZE_CONTENT)
            setting_cont.set_style_border_width(1, 0)
            setting_cont.set_style_border_side(lv.BORDER_SIDE.BOTTOM, 0)
            setting_cont.set_style_pad_all(mpos.ui.pct_of_display_width(2), 0)
            setting_cont.add_flag(lv.obj.FLAG.CLICKABLE)
            setting["cont"] = setting_cont  # Store container reference for visibility control

            # Title label (bold, larger)
            title = lv.label(setting_cont)
            title.set_text(setting["title"])
            title.set_style_text_font(lv.font_montserrat_16, 0)
            title.set_pos(0, 0)

            # Value label (smaller, below title)
            value = lv.label(setting_cont)
            value.set_text(self.prefs.get_string(setting["key"], "(not set)"))
            value.set_style_text_font(lv.font_montserrat_12, 0)
            value.set_style_text_color(lv.color_hex(0x666666), 0)
            value.set_pos(0, 20)
            setting["value_label"] = value  # Store reference for updating
            setting_cont.add_event_cb(
                lambda e, s=setting: self.startSettingActivity(s), lv.EVENT.CLICKED, None
            )

    def startSettingActivity(self, setting):
        intent = Intent(activity_class=SettingActivity)
        intent.putExtra("setting", setting)
        self.startActivity(intent)

# Used to edit one setting:
class SettingActivity(Activity):

    keyboard = None
    textarea = None
    radio_container = None
    active_radio_index = 0  # Track active radio button index

    def __init__(self):
        super().__init__()
        self.prefs = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        self.setting = None

    def onCreate(self):
        setting = self.getIntent().extras.get("setting")
        settings_screen_detail = lv.obj()
        settings_screen_detail.set_style_pad_all(mpos.ui.pct_of_display_width(2), 0)
        settings_screen_detail.set_flex_flow(lv.FLEX_FLOW.COLUMN)

        top_cont = lv.obj(settings_screen_detail)
        top_cont.set_width(lv.pct(100))
        top_cont.set_style_border_width(0, 0)
        top_cont.set_height(lv.SIZE_CONTENT)
        top_cont.set_style_pad_all(mpos.ui.pct_of_display_width(1), 0)
        top_cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        top_cont.set_style_flex_main_place(lv.FLEX_ALIGN.SPACE_BETWEEN, 0)

        setting_label = lv.label(top_cont)
        setting_label.set_text(setting["title"])
        setting_label.align(lv.ALIGN.TOP_LEFT,0,0)
        setting_label.set_style_text_font(lv.font_montserrat_26, 0)

        if setting["key"] == "wallet_type":
            # Create container for radio buttons
            self.radio_container = lv.obj(settings_screen_detail)
            self.radio_container.set_width(lv.pct(100))
            self.radio_container.set_height(lv.SIZE_CONTENT)
            self.radio_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            self.radio_container.add_event_cb(self.radio_event_handler, lv.EVENT.CLICKED, None)

            # Create radio buttons
            options = [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc")]
            current_wallet = self.prefs.get_string("wallet_type")
            self.active_radio_index = -1 # none
            if current_wallet == "lnbits":
                self.active_radio_index = 0
            elif current_wallet == "nwc":
                self.active_radio_index = 1

            for i, (text, _) in enumerate(options):
                cb = self.create_radio_button(self.radio_container, text, i)
                if i == self.active_radio_index:
                    cb.add_state(lv.STATE.CHECKED)
        else:
            # Textarea for other settings
            self.textarea = lv.textarea(settings_screen_detail)
            self.textarea.set_width(lv.pct(100))
            self.textarea.set_height(lv.SIZE_CONTENT)
            self.textarea.align_to(top_cont, lv.ALIGN.OUT_BOTTOM_MID, 0, 0)
            current = self.prefs.get_string(setting["key"])
            if current:
                self.textarea.set_text(current)
            placeholder = setting.get("placeholder")
            if placeholder:
                self.textarea.set_placeholder_text(placeholder)
            self.textarea.add_event_cb(lambda *args: mpos.ui.anim.smooth_show(self.keyboard), lv.EVENT.CLICKED, None) # it might be focused, but keyboard hidden (because ready/cancel clicked)
            self.textarea.add_event_cb(lambda *args: mpos.ui.anim.smooth_hide(self.keyboard), lv.EVENT.DEFOCUSED, None)
            # Initialize keyboard (hidden initially)
            self.keyboard = lv.keyboard(lv.layer_sys())
            self.keyboard.align(lv.ALIGN.BOTTOM_MID, 0, 0)
            self.keyboard.set_style_min_height(150, 0)
            self.keyboard.add_flag(lv.obj.FLAG.HIDDEN)
            self.keyboard.add_event_cb(lambda *args: mpos.ui.anim.smooth_hide(self.keyboard), lv.EVENT.READY, None)
            self.keyboard.add_event_cb(lambda *args: mpos.ui.anim.smooth_hide(self.keyboard), lv.EVENT.CANCEL, None)
            self.keyboard.set_textarea(self.textarea)

        # Button container
        btn_cont = lv.obj(settings_screen_detail)
        btn_cont.set_width(lv.pct(100))
        btn_cont.set_style_border_width(0, 0)
        btn_cont.set_height(lv.SIZE_CONTENT)
        btn_cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        btn_cont.set_style_flex_main_place(lv.FLEX_ALIGN.SPACE_BETWEEN, 0)
        # Save button
        save_btn = lv.button(btn_cont)
        save_btn.set_size(lv.pct(45), lv.SIZE_CONTENT)
        save_label = lv.label(save_btn)
        save_label.set_text("Save")
        save_label.center()
        save_btn.add_event_cb(lambda e, s=setting: self.save_setting(s), lv.EVENT.CLICKED, None)
        # Cancel button
        cancel_btn = lv.button(btn_cont)
        cancel_btn.set_size(lv.pct(45), lv.SIZE_CONTENT)
        cancel_label = lv.label(cancel_btn)
        cancel_label.set_text("Cancel")
        cancel_label.center()
        cancel_btn.add_event_cb(lambda e: self.finish(), lv.EVENT.CLICKED, None)

        if setting["key"] != "wallet_type":
            # Scan QR button for text settings
            cambutton = lv.button(settings_screen_detail)
            cambutton.align(lv.ALIGN.BOTTOM_MID,0,0)
            cambutton.set_size(lv.pct(100), lv.pct(30))
            cambuttonlabel = lv.label(cambutton)
            cambuttonlabel.set_text("Scan data from QR code")
            cambuttonlabel.set_style_text_font(lv.font_montserrat_18, 0)
            cambuttonlabel.align(lv.ALIGN.TOP_MID, 0, 0)
            cambuttonlabel2 = lv.label(cambutton)
            cambuttonlabel2.set_text("Tip: Create your own QR code,\nusing https://genqrcode.com or another tool.")
            cambuttonlabel2.set_style_text_font(lv.font_montserrat_10, 0)
            cambuttonlabel2.align(lv.ALIGN.BOTTOM_MID, 0, 0)
            cambutton.add_event_cb(self.cambutton_cb, lv.EVENT.CLICKED, None)

        self.setContentView(settings_screen_detail)

    def onStop(self, screen):
        if self.keyboard:
            mpos.ui.anim.smooth_hide(self.keyboard)

    def radio_event_handler(self, event):
        old_cb = self.radio_container.get_child(self.active_radio_index)
        old_cb.remove_state(lv.STATE.CHECKED)
        self.active_radio_index = -1
        for childnr in range(self.radio_container.get_child_count()):
            child = self.radio_container.get_child(childnr)
            state = child.get_state()
            print(f"radio_container child's state: {state}")
            if state != lv.STATE.DEFAULT: # State can be something like 19 = lv.STATE.HOVERED & lv.STATE.CHECKED & lv.STATE.FOCUSED
                self.active_radio_index = childnr
                break
        print(f"active_radio_index is now {self.active_radio_index}")

    def create_radio_button(self, parent, text, index):
        cb = lv.checkbox(parent)
        cb.set_text(text)
        cb.add_flag(lv.obj.FLAG.EVENT_BUBBLE)
        # Add circular style to indicator for radio button appearance
        style_radio = lv.style_t()
        style_radio.init()
        style_radio.set_radius(lv.RADIUS_CIRCLE)
        cb.add_style(style_radio, lv.PART.INDICATOR)
        style_radio_chk = lv.style_t()
        style_radio_chk.init()
        style_radio_chk.set_bg_image_src(None)
        cb.add_style(style_radio_chk, lv.PART.INDICATOR | lv.STATE.CHECKED)
        return cb

    def gotqr_result_callback(self, result):
        print(f"QR capture finished, result: {result}")
        if result.get("result_code"):
            data = result.get("data")
            print(f"Setting textarea data: {data}")
            self.textarea.set_text(data)

    def cambutton_cb(self, event):
        print("cambutton clicked!")
        self.startActivityForResult(Intent(activity_class=CameraApp).putExtra("scanqr_mode", True), self.gotqr_result_callback)

    def save_setting(self, setting):
        if setting["key"] == "wallet_type" and self.radio_container:
            selected_idx = self.active_radio_index
            if selected_idx == 0:
                new_value = "lnbits"
            elif selected_idx == 1:
                new_value = "nwc"
            else:
                return # nothing to save
        elif self.textarea:
            new_value = self.textarea.get_text()
        else:
            new_value = ""
        editor = self.prefs.edit()
        editor.put_string(setting["key"], new_value)
        editor.commit()
        setting["value_label"].set_text(new_value if new_value else "(not set)")
        self.finish()

class FullscreenQR(Activity):
    # No __init__() so super.__init__() will be called automatically

    def onCreate(self):
        receive_qr_data = self.getIntent().extras.get("receive_qr_data")
        qr_screen = lv.obj()
        qr_screen.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        qr_screen.set_scroll_dir(lv.DIR.NONE)
        big_receive_qr = lv.qrcode(qr_screen)
        big_receive_qr.set_size(mpos.ui.min_resolution())
        big_receive_qr.set_dark_color(lv.color_black())
        big_receive_qr.set_light_color(lv.color_white())
        big_receive_qr.center()
        big_receive_qr.set_style_border_color(lv.color_white(), 0)
        big_receive_qr.set_style_border_width(0, 0);
        big_receive_qr.update(receive_qr_data, len(receive_qr_data))
        close_button = lv.button(qr_screen)
        close_button.set_size(round((mpos.ui.max_resolution()-mpos.ui.min_resolution())/2),round((mpos.ui.max_resolution()-mpos.ui.min_resolution())/2))
        close_button.align(lv.ALIGN.TOP_RIGHT, 0, round(mpos.ui.NOTIFICATION_BAR_HEIGHT/2))
        close_label = lv.label(close_button)
        close_label.set_text(lv.SYMBOL.CLOSE)
        close_label.center()
        close_button.add_event_cb(lambda e: self.finish(),lv.EVENT.CLICKED,None)
        self.setContentView(qr_screen)
