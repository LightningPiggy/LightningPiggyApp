import time
import random
import lvgl as lv

from mpos.ui.keyboard import MposKeyboard
from mpos.apps import Activity, Intent
import mpos.config
import mpos.ui
import mpos.ui.theme

from wallet import LNBitsWallet, NWCWallet
from camera_app import CameraApp

class DisplayWallet(Activity):

    wallet = None
    receive_qr_data = None
    destination = None
    balance_mode_btc = False # show BTC or sats?
    payments_label_current_font = 2
    payments_label_fonts = [ lv.font_montserrat_10, lv.font_unscii_8, lv.font_montserrat_16, lv.font_montserrat_24, lv.font_unscii_16, lv.font_montserrat_30, lv.font_montserrat_40]

    # screens:
    main_screen = None

    # widgets
    balance_label = None
    receive_qr = None
    payments_label = None

    # confetti:
    SCREEN_WIDTH = None
    SCREEN_HEIGHT = None
    ASSET_PATH = "M:apps/com.lightningpiggy.displaywallet/res/drawable-mdpi/"
    ICON_PATH = "M:apps/com.lightningpiggy.displaywallet/res/mipmap-mdpi/"
    MAX_CONFETTI = 21
    GRAVITY = 100  # pixels/sec²

    def onCreate(self):
        self.main_screen = lv.obj()
        self.main_screen.set_style_pad_all(10, 0)
        # This line needs to be drawn first, otherwise it's over the balance label and steals all the clicks!
        balance_line = lv.line(self.main_screen)
        balance_line.set_points([{'x':0,'y':35},{'x':200,'y':35}],2)
        balance_line.add_flag(lv.obj.FLAG.CLICKABLE)
        balance_line.add_event_cb(self.send_button_tap,lv.EVENT.CLICKED,None)
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
        self.payments_label = lv.label(self.main_screen)
        self.payments_label.set_text("")
        self.payments_label.align_to(balance_line,lv.ALIGN.OUT_BOTTOM_LEFT,0,10)
        self.update_payments_label_font()
        self.payments_label.set_width(mpos.ui.pct_of_display_width(75)) # 100 - receive_qr
        self.payments_label.add_flag(lv.obj.FLAG.CLICKABLE)
        self.payments_label.add_event_cb(self.payments_label_clicked,lv.EVENT.CLICKED,None)
        settings_button = lv.button(self.main_screen)
        settings_button.set_size(lv.pct(20), lv.pct(25))
        settings_button.align(lv.ALIGN.BOTTOM_RIGHT, 0, 0)
        settings_button.add_event_cb(self.settings_button_tap,lv.EVENT.CLICKED,None)
        settings_label = lv.label(settings_button)
        settings_label.set_text(lv.SYMBOL.SETTINGS)
        settings_label.set_style_text_font(lv.font_montserrat_26, 0)
        settings_label.center()
        if False: # send button disabled for now, not implemented
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

        # Confetti
        self.SCREEN_WIDTH = main_screen.get_display().get_horizontal_resolution()
        self.SCREEN_HEIGHT = main_screen.get_display().get_vertical_resolution()
        self.last_time = time.ticks_ms()
        self.confetti_paused = True
        self.confetti_pieces = []
        self.confetti_images = []
        self.used_img_indices = set()  # Track which image slots are in use

        # Pre-create LVGL image objects
        iconimages = 2
        for _ in range(iconimages):
            img = lv.image(lv.layer_top())
            img.set_src(f"{self.ICON_PATH}icon_64x64.png")
            img.add_flag(lv.obj.FLAG.HIDDEN)
            self.confetti_images.append(img)
        for i in range(self.MAX_CONFETTI-iconimages): # leave space for the iconimages
            img = lv.image(lv.layer_top())
            img.set_src(f"{self.ASSET_PATH}confetti{random.randint(0,4)}.png")
            img.add_flag(lv.obj.FLAG.HIDDEN)
            self.confetti_images.append(img)

    def onResume(self, main_screen):
        super().onResume(main_screen)
        if self.wallet and self.wallet.is_running():
            print("wallet is already running, nothing to do") # might have come from the QR activity
            return
        config = mpos.config.SharedPreferences("com.lightningpiggy.displaywallet")
        wallet_type = config.get_string("wallet_type")
        if not wallet_type:
            self.payments_label.set_text(f"Please go into the settings to set a Wallet Type.")
            return # nothing is configured, nothing to do
        if wallet_type == "lnbits":
            try:
                self.wallet = LNBitsWallet(config.get_string("lnbits_url"), config.get_string("lnbits_readkey"))
            except Exception as e:
                self.error_cb(f"Couldn't initialize LNBits wallet because: {e}")
                return
        elif wallet_type == "nwc":
            try:
                self.wallet = NWCWallet(config.get_string("nwc_url"))
                self.wallet.static_receive_code = config.get_string("nwc_static_receive_code")
                self.redraw_static_receive_code_cb()
            except Exception as e:
                self.error_cb(f"Couldn't initialize NWC Wallet because: {e}")
                return
        else:
            self.error_cb(f"No or unsupported wallet type configured: '{wallet_type}'")
            return

        can_check_network = True
        try:
            import network
        except Exception as e:
            can_check_network = False
        if can_check_network and not network.WLAN(network.STA_IF).isconnected():
            self.payments_label.set_text(f"WiFi is not connected, can't talk to {wallet_type} backend.")
        else: # by now, self.wallet can be assumed
            self.balance_label.set_text(lv.SYMBOL.REFRESH)
            self.payments_label.set_text(f"\nConnecting to {wallet_type} backend.\n\nIf this takes too long, it might be down or something's wrong with the settings.")
            self.wallet.start(self.redraw_balance_cb, self.redraw_payments_cb, self.redraw_static_receive_code_cb, self.error_cb)

    def onPause(self, main_screen):
        if self.wallet and self.destination != FullscreenQR:
            self.wallet.stop() # don't stop the wallet for the fullscreen QR activity
            self.stop_receive_animation()
        self.destination = None

    def onDestroy(self, main_screen):
        pass # would be good to cleanup lv.layer_top() of those confetti images

    def update_payments_label_font(self):
        self.payments_label.set_style_text_font(self.payments_label_fonts[self.payments_label_current_font], 0)

    def payments_label_clicked(self, event):
        self.payments_label_current_font = (self.payments_label_current_font + 1) % len(self.payments_label_fonts)
        self.update_payments_label_font()

    def float_to_string(self, value):
        # Format float to string with fixed-point notation, up to 6 decimal places
        s = "{:.8f}".format(value)
        # Remove trailing zeros and decimal point if no decimals remain
        return s.rstrip("0").rstrip(".")

    def redraw_balance_cb(self, sats_added=0):
        print(f"Redrawing balance for sats_added {sats_added}")
        if sats_added > 0:
            self.start_receive_animation()
        balance = self.wallet.last_known_balance
        if balance is not None and balance != -1:
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
            self.update_ui_threadsafe_if_foreground(self.balance_label.set_text, balance_text)
        else:
            print("Not drawing balance because it's None or -1")
    
    def redraw_payments_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        self.update_ui_threadsafe_if_foreground(self.payments_label.set_text, str(self.wallet.payment_list))

    def redraw_static_receive_code_cb(self):
        # this gets called from another thread (the wallet) so make sure it happens in the LVGL thread using lv.async_call():
        self.receive_qr_data = self.wallet.static_receive_code
        if self.receive_qr_data:
            self.update_ui_threadsafe_if_foreground(self.receive_qr.update, self.receive_qr_data, len(self.receive_qr_data))
        else:
            print("Warning: redraw_static_receive_code_cb() was called while self.wallet.static_receive_code is None...")

    def error_cb(self, error):
        if self.wallet and self.wallet.is_running():
            self.update_ui_threadsafe_if_foreground(self.payments_label.set_text, str(error))

    def send_button_tap(self, event):
        print("send_button clicked")
        if self.confetti_paused:
            self.start_receive_animation() # for testing the receive animation

    def start_receive_animation(self, event=None):
        self.confetti_paused = False
        self._clear_confetti()

        # Staggered spawn control
        self.spawn_timer = 0
        self.spawn_interval = 0.15  # seconds
        self.animation_start = time.ticks_ms() / 1000.0

        # Initial burst
        for _ in range(10):
            self._spawn_one()

        mpos.ui.task_handler.add_event_cb(self.update_frame, 1)

        # Stop spawning after 15 seconds
        lv.timer_create(self.stop_receive_animation, 15000, None).set_repeat_count(1)

    def stop_receive_animation(self, timer=None):
        self.confetti_paused = True

    def _clear_confetti(self):
        for img in self.confetti_images:
            img.add_flag(lv.obj.FLAG.HIDDEN)
        self.confetti_pieces = []
        self.used_img_indices.clear()

    def update_frame(self, a, b):
        current_time = time.ticks_ms()
        delta_time = time.ticks_diff(current_time, self.last_time) / 1000.0
        self.last_time = current_time

        # === STAGGERED SPAWNING ===
        if not self.confetti_paused:
            self.spawn_timer += delta_time
            if self.spawn_timer >= self.spawn_interval:
                self.spawn_timer = 0
                for _ in range(random.randint(1, 2)):
                    if len(self.confetti_pieces) < self.MAX_CONFETTI:
                        self._spawn_one()

        # === UPDATE ALL PIECES ===
        new_pieces = []
        for piece in self.confetti_pieces:
            # Physics
            piece['age'] += delta_time
            piece['x'] += piece['vx'] * delta_time
            piece['y'] += piece['vy'] * delta_time
            piece['vy'] += self.GRAVITY * delta_time
            piece['rotation'] += piece['spin'] * delta_time
            piece['scale'] = max(0.3, 1.0 - (piece['age'] / piece['lifetime']) * 0.7)

            # Render
            img = self.confetti_images[piece['img_idx']]
            img.remove_flag(lv.obj.FLAG.HIDDEN)
            img.set_pos(int(piece['x']), int(piece['y']))
            img.set_rotation(int(piece['rotation'] * 10))
            orig = img.get_width()
            if orig >= 64:
                img.set_scale(int(256 * piece['scale'] / 1.5))
            elif orig < 32:
                img.set_scale(int(256 * piece['scale'] * 1.5))
            else:
                img.set_scale(int(256 * piece['scale']))

            # Death check
            dead = (
                piece['x'] < -60 or piece['x'] > self.SCREEN_WIDTH + 60 or
                piece['y'] > self.SCREEN_HEIGHT + 60 or
                piece['age'] > piece['lifetime']
            )

            if dead:
                img.add_flag(lv.obj.FLAG.HIDDEN)
                self.used_img_indices.discard(piece['img_idx'])
            else:
                new_pieces.append(piece)

        self.confetti_pieces = new_pieces

        # Full stop when empty and paused
        if not self.confetti_pieces and self.confetti_paused:
            print("Confetti finished")
            mpos.ui.task_handler.remove_event_cb(self.update_frame)

    def _spawn_one(self):
        if self.confetti_paused:
            return

        # Find a free image slot
        for idx, img in enumerate(self.confetti_images):
            if img.has_flag(lv.obj.FLAG.HIDDEN) and idx not in self.used_img_indices:
                break
        else:
            return  # No free slot

        piece = {
            'img_idx': idx,
            'x': random.uniform(-50, self.SCREEN_WIDTH + 50),
            'y': random.uniform(50, 100),  # Start above screen
            'vx': random.uniform(-80, 80),
            'vy': random.uniform(-150, 0),
            'spin': random.uniform(-500, 500),
            'age': 0.0,
            'lifetime': random.uniform(5.0, 10.0),  # Long enough to fill 10s
            'rotation': random.uniform(0, 360),
            'scale': 1.0
        }
        self.confetti_pieces.append(piece)
        self.used_img_indices.add(idx)

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
#            {"title": "Payments To Show", "key": "payments_to_show", "value_label": None, "cont": None, "placeholder": "6"},
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
        # Get the group for focusable objects
        focusgroup = lv.group_get_default()
        if not focusgroup:
            print("WARNING: could not get default focusgroup")

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
            #setting_cont.set_style_border_side(lv.BORDER_SIDE.BOTTOM, 0)
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
            setting_cont.add_event_cb(lambda e, s=setting: self.startSettingActivity(s), lv.EVENT.CLICKED, None)
            setting_cont.add_event_cb(lambda e, container=setting_cont: self.focus_container(container),lv.EVENT.FOCUSED,None)
            setting_cont.add_event_cb(lambda e, container=setting_cont: self.defocus_container(container),lv.EVENT.DEFOCUSED,None)
            if focusgroup:
                focusgroup.add_obj(setting_cont)

    def focus_container(self, container):
        print(f"container {container} focused, setting border...")
        container.set_style_border_color(lv.theme_get_color_primary(None),lv.PART.MAIN)
        container.set_style_border_width(1, lv.PART.MAIN)
        container.scroll_to_view(True) # scroll to bring it into view

    def defocus_container(self, container):
        print(f"container {container} defocused, unsetting border...")
        container.set_style_border_width(0, lv.PART.MAIN)

    def startSettingActivity(self, setting):
        intent = Intent(activity_class=SettingActivity)
        intent.putExtra("setting", setting)
        self.startActivity(intent)

# Used to edit one setting:
class SettingActivity(Activity):

    btn_cont = None
    cambutton = None
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
        settings_screen_detail.set_style_pad_all(0, 0)
        settings_screen_detail.set_scroll_dir(lv.DIR.NONE)
        settings_screen_detail.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        #settings_screen_detail.set_style_pad_all(mpos.ui.pct_of_display_width(1), 0)
        settings_screen_detail.set_flex_flow(lv.FLEX_FLOW.COLUMN)

        top_cont = lv.obj(settings_screen_detail)
        top_cont.set_width(lv.pct(100))
        top_cont.set_style_border_width(0, 0)
        top_cont.set_height(lv.SIZE_CONTENT)
        #top_cont.set_style_pad_all(mpos.ui.pct_of_display_width(5), 0)
        top_cont.set_style_pad_all(0, 0)
        top_cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        top_cont.set_style_flex_main_place(lv.FLEX_ALIGN.SPACE_BETWEEN, 0)

        #setting_label = lv.label(settings_screen_detail)
        setting_label = lv.label(top_cont)
        setting_label.set_text(setting["title"])
        setting_label.align(lv.ALIGN.TOP_LEFT,0,0)
        setting_label.set_style_text_font(lv.font_montserrat_20, 0)

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
            self.textarea.set_width(lv.pct(90))
            self.textarea.set_one_line(True) # might not be good for all settings but it's good for most
            current = self.prefs.get_string(setting["key"])
            if current:
                self.textarea.set_text(current)
            placeholder = setting.get("placeholder")
            if placeholder:
                self.textarea.set_placeholder_text(placeholder)
            self.textarea.add_event_cb(lambda *args: self.show_keyboard(), lv.EVENT.CLICKED, None)
            # Initialize keyboard (hidden initially)
            self.keyboard = MposKeyboard(settings_screen_detail)
            self.keyboard.align(lv.ALIGN.BOTTOM_MID, 0, 0)
            self.keyboard.set_textarea(self.textarea)
            self.keyboard.set_style_min_height(165, 0)
            self.keyboard.add_event_cb(lambda *args: self.hide_keyboard(), lv.EVENT.READY, None)
            self.keyboard.add_event_cb(lambda *args: self.hide_keyboard(), lv.EVENT.CANCEL, None)
            self.keyboard.add_flag(lv.obj.FLAG.HIDDEN)
            self.keyboard.add_event_cb(self.handle_keyboard_events, lv.EVENT.VALUE_CHANGED, None)

        # Button container
        self.btn_cont = lv.obj(settings_screen_detail)
        self.btn_cont.set_width(lv.pct(100))
        self.btn_cont.set_style_border_width(0, 0)
        self.btn_cont.set_height(lv.SIZE_CONTENT)
        self.btn_cont.set_flex_flow(lv.FLEX_FLOW.ROW)
        self.btn_cont.set_style_flex_main_place(lv.FLEX_ALIGN.SPACE_BETWEEN, 0)
        # Save button
        save_btn = lv.button(self.btn_cont)
        save_btn.set_size(lv.pct(45), lv.SIZE_CONTENT)
        save_label = lv.label(save_btn)
        save_label.set_text("Save")
        save_label.center()
        save_btn.add_event_cb(lambda e, s=setting: self.save_setting(s), lv.EVENT.CLICKED, None)
        # Cancel button
        cancel_btn = lv.button(self.btn_cont)
        cancel_btn.set_size(lv.pct(45), lv.SIZE_CONTENT)
        cancel_label = lv.label(cancel_btn)
        cancel_label.set_text("Cancel")
        cancel_label.center()
        cancel_btn.add_event_cb(lambda e: self.finish(), lv.EVENT.CLICKED, None)

        if setting["key"] != "wallet_type":
            # Scan QR button for text settings
            self.cambutton = lv.button(settings_screen_detail)
            self.cambutton.align(lv.ALIGN.BOTTOM_MID,0,0)
            self.cambutton.set_size(lv.pct(100), lv.pct(30))
            cambuttonlabel = lv.label(self.cambutton)
            cambuttonlabel.set_text("Scan data from QR code")
            cambuttonlabel.set_style_text_font(lv.font_montserrat_18, 0)
            cambuttonlabel.align(lv.ALIGN.TOP_MID, 0, 0)
            cambuttonlabel2 = lv.label(self.cambutton)
            cambuttonlabel2.set_text("Tip: Create your own QR code,\nusing https://genqrcode.com or another tool.")
            cambuttonlabel2.set_style_text_font(lv.font_montserrat_10, 0)
            cambuttonlabel2.align(lv.ALIGN.BOTTOM_MID, 0, 0)
            self.cambutton.add_event_cb(self.cambutton_cb, lv.EVENT.CLICKED, None)

        self.setContentView(settings_screen_detail)

    def onStop(self, screen):
        self.hide_keyboard()

    def show_keyboard(self):
        self.btn_cont.add_flag(lv.obj.FLAG.HIDDEN)
        if self.cambutton: # not always set
            self.cambutton.add_flag(lv.obj.FLAG.HIDDEN)
        mpos.ui.anim.smooth_show(self.keyboard)
        focusgroup = lv.group_get_default()
        if focusgroup:
            # move the focus to the keyboard to save the user a "next" button press (optional but nice)
            # this is focusing on the right thing (keyboard) but the focus is not "active" (shown or used) somehow
            print(f"current focus object: {lv.group_get_default().get_focused()}")
            focusgroup.focus_next()
            print(f"current focus object: {lv.group_get_default().get_focused()}")

    def hide_keyboard(self):
        if self.keyboard:
            self.btn_cont.remove_flag(lv.obj.FLAG.HIDDEN)
            self.cambutton.remove_flag(lv.obj.FLAG.HIDDEN)
            mpos.ui.anim.smooth_hide(self.keyboard)

    def handle_keyboard_events(self, event):
        target_obj=event.get_target_obj() # keyboard
        button = target_obj.get_selected_button()
        text = target_obj.get_button_text(button)
        #print(f"button {button} and text {text}")
        if text == lv.SYMBOL.NEW_LINE:
            print("Newline pressed, closing the keyboard...")
            self.hide_keyboard()

    def radio_event_handler(self, event):
        print("radio_event_handler called")
        if self.active_radio_index >= 0:
            print(f"removing old CHECKED state from child {self.active_radio_index}")
            old_cb = self.radio_container.get_child(self.active_radio_index)
            old_cb.remove_state(lv.STATE.CHECKED)
        self.active_radio_index = -1
        for childnr in range(self.radio_container.get_child_count()):
            child = self.radio_container.get_child(childnr)
            state = child.get_state()
            print(f"radio_container child's state: {state}")
            if state & lv.STATE.CHECKED: # State can be something like 19 = lv.STATE.HOVERED  (16) & lv.STATE.FOCUSED (2) & lv.STATE.CHECKED (1)
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
        qr_screen.add_event_cb(lambda e: self.finish(),lv.EVENT.CLICKED,None)
        big_receive_qr = lv.qrcode(qr_screen)
        big_receive_qr.set_size(mpos.ui.min_resolution())
        big_receive_qr.set_dark_color(lv.color_black())
        big_receive_qr.set_light_color(lv.color_white())
        big_receive_qr.center()
        big_receive_qr.set_style_border_color(lv.color_white(), 0)
        big_receive_qr.set_style_border_width(0, 0);
        big_receive_qr.update(receive_qr_data, len(receive_qr_data))
        self.setContentView(qr_screen)
