import lvgl as lv

from mpos import Activity, DisplayMetrics
try:
    from mpos import AppearanceManager
    _has_appearance = True
except ImportError:
    _has_appearance = False

class FullscreenQR(Activity):
    # No __init__() so super.__init__() will be called automatically

    def onCreate(self):
        receive_qr_data = self.getIntent().extras.get("receive_qr_data")
        qr_screen = lv.obj()
        qr_screen.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)
        qr_screen.set_scroll_dir(lv.DIR.NONE)
        qr_screen.add_event_cb(lambda e: self.finish(),lv.EVENT.CLICKED,None)
        big_receive_qr = lv.qrcode(qr_screen)
        big_receive_qr.set_size(round(DisplayMetrics.min_dimension()*0.9))
        if _has_appearance and not AppearanceManager.is_light_mode():
            big_receive_qr.set_dark_color(lv.color_white())
            big_receive_qr.set_light_color(lv.color_hex(0x15171A))
            border_color = lv.color_hex(0x15171A)
        else:
            big_receive_qr.set_dark_color(lv.color_black())
            big_receive_qr.set_light_color(lv.color_white())
            border_color = lv.color_white()
        big_receive_qr.center()
        big_receive_qr.set_style_border_color(border_color, lv.PART.MAIN)
        big_receive_qr.set_style_border_width(round(DisplayMetrics.min_dimension()*0.1), lv.PART.MAIN);
        big_receive_qr.update(receive_qr_data, len(receive_qr_data))
        self.setContentView(qr_screen)
