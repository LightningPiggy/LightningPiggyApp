from mpos.apps import Activity, Intent
import mpos.config

from wallet import LNBitsWallet, NWCWallet
from captureqr import Camera

class DisplayWallet(Activity):

    wallet = None
    receive_qr_data = None
    destination = None

    # widgets
    balance_label = None
    receive_qr = None
    payments_label = None

    def onCreate(self):
        main_screen = lv.obj()
        main_screen.set_style_pad_all(10, 0)
        self.balance_label = lv.label(main_screen)
        self.balance_label.set_text("")
        self.balance_label.align(lv.ALIGN.TOP_LEFT, 0, 0)
        self.balance_label.set_style_text_font(lv.font_montserrat_22, 0)
        self.receive_qr = lv.qrcode(main_screen)
        self.receive_qr.set_size(80)
        #self.receive_qr.set_size(240) bigger will result in simpler code (less error correction?)
        self.receive_qr.set_dark_color(lv.color_black())
        self.receive_qr.set_light_color(lv.color_white())
        self.receive_qr.align(lv.ALIGN.TOP_RIGHT,0,0)
        self.receive_qr.set_style_border_color(lv.color_white(), 0)
        self.receive_qr.set_style_border_width(1, 0);
        self.receive_qr.add_flag(lv.obj.FLAG.CLICKABLE)
        self.receive_qr.add_event_cb(self.qr_clicked_cb,lv.EVENT.CLICKED,None)
        balance_line = lv.line(main_screen)
        balance_line.set_points([{'x':0,'y':35},{'x':200,'y':35}],2)
        self.payments_label = lv.label(main_screen)
        self.payments_label.set_text("")
        self.payments_label.align_to(balance_line,lv.ALIGN.OUT_BOTTOM_LEFT,0,10)
        self.payments_label.set_style_text_font(lv.font_montserrat_16, 0)
        settings_button = lv.button(main_screen)
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        snap_label = lv.label(settings_button)
        snap_label.set_text(lv.SYMBOL.SETTINGS)
        snap_label.center()
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        self.setContentView(main_screen)

    def onStart(self, main_screen):
        self.main_ui_set_defaults()
    
    def onResume(self, main_screen):
        if self.wallet and self.wallet.is_running():
            return # wallet is already running, nothing to do
        config = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        if not config:
            return # nothing is configured, nothing to do
        wallet_type = config.get_string("wallet_type")
        if not wallet_type:
            return # don't know what wallet to use so can't start it, nothing to do

        if wallet_type == "lnbits":
            try:
                self.wallet = LNBitsWallet(config.get_string("lnbits_url"), config.get_string("lnbits_readkey"))
            except Exception as e:
                self.payments_label.set_text(f"Couldn't initialize LNBitsWallet\nbecause: {e}")
        elif wallet_type == "nwc":
            try:
                self.wallet = NWCWallet(config.get_string("nwc_url"))
            except Exception as e:
                self.payments_label.set_text(f"Couldn't initialize NWCWallet\nbecause: {e}")
        else:
            self.payments_label.set_text(f"No or unsupported wallet\ntype configured: '{wallet_type}'")
        can_check_network = True
        try:
            import network
        except Exception as e:
            can_check_network = False
        if can_check_network and not network.WLAN(network.STA_IF).isconnected():
            self.payments_label.set_text(f"WiFi is not connected, can't\ntalk to {wallet_type} backend.")
        else:
            if self.wallet:
                self.payments_label.set_text(f"Connecting to {wallet_type} backend...")
                self.wallet.start(self.redraw_balance_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb)
            else:
                self.payments_label.set_text(f"Could not start {wallet_type}  backend.")

    def onStop(self, main_screen):
        if self.wallet and self.destination != FullscreenQR:
            self.wallet.stop()
        self.destination = None

    def redraw_balance_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        lv.async_call(lambda l: self.balance_label.set_text(str(self.wallet.last_known_balance)), None)
    
    def redraw_payments_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        lv.async_call(lambda l: self.payments_label.set_text(str(self.wallet.payment_list)), None)

    def redraw_static_receive_code_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        self.receive_qr_data = self.wallet.static_receive_code
        lv.async_call(lambda l: self.receive_qr.update(self.receive_qr_data, len(self.receive_qr_data)), None)

    def settings_button_tap(self, event):
        self.startActivity(Intent(activity_class=SettingsActivity))
    
    def main_ui_set_defaults(self):
        self.balance_label.set_text(lv.SYMBOL.REFRESH)
        self.payments_label.set_text(lv.SYMBOL.REFRESH)
        #self.receive_qr.update("EMPTY PLACEHOLDER", len("EMPTY PLACEHOLDER"))
    
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
        self.prefs = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        self.settings = [
            {"title": "Wallet Type", "key": "wallet_type", "value_label": None, "cont": None},
            {"title": "LNBits URL", "key": "lnbits_url", "value_label": None, "cont": None},
            {"title": "LNBits Read Key", "key": "lnbits_readkey", "value_label": None, "cont": None},
            {"title": "Static receive code", "key": "lnbits_static_receive_code", "value_label": None, "cont": None},
            {"title": "NWC URL", "key": "nwc_url", "value_label": None, "cont": None},
        ]
        self.keyboard = None
        self.textarea = None
        self.radio_container = None
        self.active_radio_index = 0  # Track active radio button index

    def onCreate(self):
        screen = lv.obj()
        print("creating SettingsActivity ui...")
        screen.set_size(lv.pct(100), lv.pct(100))
        screen.set_style_pad_all(10, 0)
        screen.set_flex_flow(lv.FLEX_FLOW.COLUMN)
        screen.set_style_border_width(0, 0)
        
        # Create settings entries
        for setting in self.settings:
            # Container for each setting
            setting_cont = lv.obj(screen)
            setting_cont.set_width(lv.pct(100))
            setting_cont.set_height(lv.SIZE_CONTENT)
            setting_cont.set_style_border_width(1, 0)
            setting_cont.set_style_border_side(lv.BORDER_SIDE.BOTTOM, 0)
            setting_cont.set_style_pad_all(8, 0)
            setting_cont.add_flag(lv.obj.FLAG.CLICKABLE)
            setting["cont"] = setting_cont  # Store container reference for visibility control

            # Title label (bold, larger)
            title = lv.label(setting_cont)
            title.set_text(setting["title"])
            title.set_style_text_font(lv.font_montserrat_16, 0)
            title.set_pos(0, 0)

            # Value label (smaller, below title)
            value = lv.label(setting_cont)
            value.set_text(self.prefs.get_string(setting["key"], "Not set"))
            value.set_style_text_font(lv.font_montserrat_12, 0)
            value.set_style_text_color(lv.color_hex(0x666666), 0)
            value.set_pos(0, 20)
            setting["value_label"] = value  # Store reference for updating
            setting_cont.add_event_cb(
                lambda e, s=setting: self.startSettingActivity(s), lv.EVENT.CLICKED, None
            )
        self.setContentView(screen)

    def onResume(self, screen):
        wallet_type = self.prefs.get_string("wallet_type", "lnbits")
        # update setting visibility based on wallet_type:
        for setting in self.settings:
            if setting["key"].startswith("lnbits_"):
                if wallet_type != "lnbits":
                    setting["cont"].add_flag(lv.obj.FLAG.HIDDEN)
                else:
                    setting["cont"].remove_flag(lv.obj.FLAG.HIDDEN)
            elif setting["key"].startswith("nwc_"):
                if wallet_type != "nwc":
                    setting["cont"].add_flag(lv.obj.FLAG.HIDDEN)
                else:
                    setting["cont"].remove_flag(lv.obj.FLAG.HIDDEN)

    def startSettingActivity(self, setting):
        intent = Intent(activity_class=SettingActivity)
        intent.putExtra("setting", setting)
        self.startActivity(intent)

# Used to edit one setting:
class SettingActivity(Activity):
    def __init__(self):
        super().__init__()
        self.prefs = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        self.setting = None

    def onCreate(self):
        setting = self.getIntent().extras.get("setting")
        settings_screen_detail = lv.obj()
        settings_screen_detail.set_style_pad_all(10, 0)
        settings_screen_detail.set_flex_flow(lv.FLEX_FLOW.COLUMN)

        top_cont = lv.obj(settings_screen_detail)
        top_cont.set_width(lv.pct(100))
        top_cont.set_height(lv.SIZE_CONTENT)
        top_cont.set_style_pad_all(0, 0)
        top_cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        top_cont.set_style_flex_main_place(lv.FLEX_ALIGN.SPACE_BETWEEN, 0)

        setting_label = lv.label(top_cont)
        setting_label.set_text(setting["title"])
        setting_label.align(lv.ALIGN.TOP_LEFT,0,0)
        setting_label.set_style_text_font(lv.font_montserrat_22, 0)

        # Camera for text
        cambutton = lv.button(top_cont)
        cambutton.align(lv.ALIGN.TOP_RIGHT,0,0)
        cambuttonlabel = lv.label(cambutton)
        cambuttonlabel.set_text("SCAN QR")
        cambuttonlabel.center()
        cambutton.add_event_cb(self.cambutton_cb, lv.EVENT.CLICKED, None)

        if setting["key"] == "wallet_type":
            cambutton.add_flag(lv.obj.FLAG.HIDDEN)
            # Create container for radio buttons
            self.radio_container = lv.obj(settings_screen_detail)
            self.radio_container.set_width(lv.pct(100))
            self.radio_container.set_height(lv.SIZE_CONTENT)
            self.radio_container.set_flex_flow(lv.FLEX_FLOW.COLUMN)
            self.radio_container.add_event_cb(self.radio_event_handler, lv.EVENT.CLICKED, None)

            # Create radio buttons
            options = [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc")]
            current_wallet = self.prefs.get_string("wallet_type", "lnbits")
            self.active_radio_index = 0 if current_wallet == "lnbits" else 1

            for i, (text, _) in enumerate(options):
                cb = self.create_radio_button(self.radio_container, text, i)
                if i == self.active_radio_index:
                    cb.add_state(lv.STATE.CHECKED)
        else:
            # Textarea for other settings
            self.textarea = lv.textarea(settings_screen_detail)
            self.textarea.set_width(lv.pct(100))
            self.textarea.set_height(lv.SIZE_CONTENT)
            self.textarea.set_text(self.prefs.get_string(setting["key"], ""))
            self.textarea.add_event_cb(self.show_keyboard, lv.EVENT.CLICKED, None)
            self.textarea.add_event_cb(self.show_keyboard, lv.EVENT.FOCUSED, None)
            self.textarea.add_event_cb(self.hide_keyboard, lv.EVENT.DEFOCUSED, None)
            # Initialize keyboard (hidden initially)
            self.keyboard = lv.keyboard(lv.layer_sys())
            self.keyboard.set_size(lv.pct(100), lv.pct(40))
            self.keyboard.align(lv.ALIGN.BOTTOM_MID, 0, 0)
            self.keyboard.add_flag(lv.obj.FLAG.HIDDEN)
            self.keyboard.add_event_cb(self.keyboard_cb, lv.EVENT.READY, None)
            self.keyboard.add_event_cb(self.keyboard_cb, lv.EVENT.CANCEL, None)
            self.keyboard.set_textarea(self.textarea)

        # Button container
        btn_cont = lv.obj(settings_screen_detail)
        btn_cont.set_width(lv.pct(100))
        btn_cont.set_height(lv.SIZE_CONTENT)
        btn_cont.set_style_pad_all(5, 0)
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
        self.setContentView(settings_screen_detail)

    def hide_keyboard(self, event=None):
        print("hide_keyboard: hiding keyboard")
        self.keyboard.add_flag(lv.obj.FLAG.HIDDEN)

    def show_keyboard(self, event):
        print("showing keyboard")
        self.keyboard.remove_flag(lv.obj.FLAG.HIDDEN)

    def keyboard_cb(self, event=None):
        print("keyboard_cb: Keyboard event triggered")
        code = event.get_code()
        if code == lv.EVENT.READY or code == lv.EVENT.CANCEL:
            print("keyboard_cb: READY or CANCEL or RETURN clicked, hiding keyboard")
            self.hide_keyboard()

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
        self.startActivityForResult(Intent(activity_class=Camera).putExtra("scanqr_mode", True), self.gotqr_result_callback)

    def save_setting(self, setting):
        if setting["key"] == "wallet_type" and self.radio_container:
            selected_idx = self.active_radio_index
            new_value = "lnbits" if selected_idx == 0 else "nwc"
        elif self.textarea:
            new_value = self.textarea.get_text()
        else:
            new_value = ""
        editor = self.prefs.edit()
        editor.put_string(setting["key"], new_value)
        editor.commit()
        setting["value_label"].set_text(new_value if new_value else "Not set")
        self.finish()

class FullscreenQR(Activity):
    # No __init__() so super.__init__() will be called automatically

    def onCreate(self):
        receive_qr_data = self.getIntent().extras.get("receive_qr_data")
        qr_screen = lv.obj()
        qr_screen.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        qr_screen.set_scroll_dir(lv.DIR.NONE)
        big_receive_qr = lv.qrcode(qr_screen)
        big_receive_qr.set_size(240) # TODO: make this dynamic
        big_receive_qr.set_dark_color(lv.color_black())
        big_receive_qr.set_light_color(lv.color_white())
        big_receive_qr.center()
        big_receive_qr.set_style_border_color(lv.color_white(), 0)
        big_receive_qr.set_style_border_width(0, 0);
        big_receive_qr.update(receive_qr_data, len(receive_qr_data))
        close_button = lv.button(qr_screen)
        close_button.set_size(round((320-240)/2),round((320-240)/2)) # TODO: make this dynamic
        close_button.align(lv.ALIGN.TOP_RIGHT, 0, round(mpos.ui.NOTIFICATION_BAR_HEIGHT/2))
        close_label = lv.label(close_button)
        close_label.set_text(lv.SYMBOL.CLOSE)
        close_label.center()
        close_button.add_event_cb(lambda e: self.finish(),lv.EVENT.CLICKED,None)
        self.setContentView(qr_screen)
