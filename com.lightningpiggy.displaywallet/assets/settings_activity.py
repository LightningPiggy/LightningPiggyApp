import lvgl as lv

from mpos.apps import Activity, Intent
import mpos.config
import mpos.ui

from setting_activity import SettingActivity

# Used to list and edit all settings:
class SettingsActivity(Activity):
    def __init__(self):
        super().__init__()
        self.prefs = None
        self.settings = [
            {"title": "Wallet Type", "key": "wallet_type", "value_label": None, "cont": None, "ui": "radiobuttons", "ui_options": [("LNBits", "lnbits"), ("Nostr Wallet Connect", "nwc")]},
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
