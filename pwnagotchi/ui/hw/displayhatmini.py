import logging

import pwnagotchi.ui.fonts as fonts
from pwnagotchi.ui.hw.base import DisplayImpl


class DisplayHatMini(DisplayImpl):
    def __init__(self, config):
        super(DisplayHatMini, self).__init__(config, 'displayhatmini')
        self._display = None

    def layout(self):
        fonts.setup(12, 10, 12, 70, 25, 9)
        self._layout['width'] = 320
        self._layout['height'] = 240
        self._layout['face'] = (35, 50)
        self._layout['name'] = (5, 20)
        self._layout['channel'] = (0, 0)
        self._layout['aps'] = (40, 0)
        self._layout['uptime'] = (240, 0)
        self._layout['line1'] = [0, 14, 320, 14]
        self._layout['line2'] = [0, 220, 320, 220]
        self._layout['shakes'] = (0, 220)
        self._layout['mode'] = (280, 220)
        self._layout['status'] = {
            'pos': (80, 160),
            'font': fonts.status_font(fonts.Medium),
            'max': 20
        }

        return self._layout

    def initialize(self):
        logging.info("initializing Display Hat Mini")
        from pwnagotchi.ui.hw.libs.pimoroni.displayhatmini.ST7789 import ST7789
        self._display = ST7789(0,1,9,13)

    def render(self, canvas):
        self._display.display(canvas)

    def clear(self):
        self._display.clear()

    def set_backlight(self, value):
        if self._display:
            self._display.set_backlight(value)

    def get_backlight(self):
        if self._display:
            self._display.get_backlight(value)
