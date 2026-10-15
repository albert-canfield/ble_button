# /config/custom_components/ble_button/device_trigger.py

from __future__ import annotations

import voluptuous as vol

from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import (
    CLICK_TYPES,
    CONF_MODE,
    DEFAULT_MODE,
    DOMAIN,
    EVENT_BLE_BUTTON_CLICK,
    EVENT_BLE_BUTTON_PRESS,
    MODE_MULTI_CLICK,
)

# Instant mode: "press" fires straight away on every press. Multi-click mode:
# the click types fire once the click sequence is over (long: while held).
TRIGGER_PRESS = "press"
TRIGGER_TYPES = [TRIGGER_PRESS, *CLICK_TYPES]

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """List the triggers of a BLE Button device for its mode."""
    mode = DEFAULT_MODE
    if device := dr.async_get(hass).async_get(device_id):
        for entry_id in device.config_entries:
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN:
                mode = entry.options.get(CONF_MODE, DEFAULT_MODE)
    trigger_types = CLICK_TYPES if mode == MODE_MULTI_CLICK else [TRIGGER_PRESS]
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in trigger_types
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Fire on ble_button_press / ble_button_click events from this device."""
    if config[CONF_TYPE] == TRIGGER_PRESS:
        event_type = EVENT_BLE_BUTTON_PRESS
        event_data = {CONF_DEVICE_ID: config[CONF_DEVICE_ID]}
    else:
        event_type = EVENT_BLE_BUTTON_CLICK
        event_data = {
            CONF_DEVICE_ID: config[CONF_DEVICE_ID],
            "click_type": config[CONF_TYPE],
        }

    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: event_type,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
