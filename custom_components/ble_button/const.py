# /config/custom_components/ble_button/const.py

from homeassistant.const import Platform

DOMAIN = "ble_button"

CONF_MAC = "mac"
CONF_SOURCE = "source"
CONF_PRESS_RESET_DELAY = "press_reset_delay"

SOURCE_ANY = "any"

DEFAULT_PRESS_RESET_DELAY = 0.60
DEFAULT_DISCOVERY_SECONDS = 8
DUPLICATE_WINDOW_SECONDS = 0.15

STATE_NONE = "none"
STATE_PRESS = "press"

EVENT_BLE_BUTTON_PRESS = "ble_button_press"
EVENT_BLE_BUTTON_DEBUG = "ble_button_debug"

PLATFORMS = [Platform.SENSOR]
