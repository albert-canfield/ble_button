# /config/custom_components/ble_button/const.py

from homeassistant.const import Platform

DOMAIN = "ble_button"

CONF_MAC = "mac"
CONF_SOURCE = "source"
CONF_PRESS_RESET_DELAY = "press_reset_delay"
CONF_CLICK_WINDOW = "click_window"
CONF_MODE = "mode"

# Instant: a binary sensor that pulses on every press, no waiting.
# Multi-click: an event entity reporting single / double / triple / long,
# decided once the click window has passed.
MODE_INSTANT = "instant"
MODE_MULTI_CLICK = "multi_click"
MODES = [MODE_INSTANT, MODE_MULTI_CLICK]
DEFAULT_MODE = MODE_INSTANT

SOURCE_ANY = "any"

DEFAULT_PRESS_RESET_DELAY = 0.60
# Quiet time after the last press that ends a click sequence.
DEFAULT_CLICK_WINDOW = 2.0
# Many buttons keep repeating their packet while held. Still transmitting this
# long after a press = long press (multi-click mode, HA 2026.10+).
LONG_PRESS_TIME = 2.0
# A gap longer than this between repeats means the button was released.
HOLD_REPEAT_GAP = 1.0
# Never wait longer than this past the window for a held button.
HOLD_MAX_EXTRA_WAIT = 10.0
# Without per-advert tracking (HA < 2026.10), the click window for buttons
# whose profile flags long presses is stretched past their long-press time
# (~2.6 s for the hs_counter profile).
LONG_PRESS_FALLBACK_WINDOW = 3.5
DEFAULT_DISCOVERY_SECONDS = 8
DUPLICATE_WINDOW_SECONDS = 0.15
# A press counter that jumps further than this (button out of range, HA down)
# counts as one press, not as a burst of missed ones.
MAX_COUNTER_STEP = 5

EVENT_BLE_BUTTON_PRESS = "ble_button_press"
EVENT_BLE_BUTTON_CLICK = "ble_button_click"
EVENT_BLE_BUTTON_DEBUG = "ble_button_debug"

CLICK_SINGLE = "single"
CLICK_DOUBLE = "double"
CLICK_TRIPLE = "triple"
CLICK_LONG = "long"
CLICK_TYPES = [CLICK_SINGLE, CLICK_DOUBLE, CLICK_TRIPLE, CLICK_LONG]

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR]
