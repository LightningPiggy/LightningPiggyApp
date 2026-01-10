import lvgl as lv

from mpos.apps import Activity, Intent
import mpos.config
import mpos.ui
from mpos.ui.keyboard import MposKeyboard

from camera_app import CameraApp

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
            # Initialize keyboard (hidden initially)
            self.keyboard = MposKeyboard(settings_screen_detail)
            self.keyboard.set_textarea(self.textarea)
            self.keyboard.add_flag(lv.obj.FLAG.HIDDEN)

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
        self.startActivityForResult(Intent(activity_class=CameraApp).putExtra("scanqr_intent", True), self.gotqr_result_callback)

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
