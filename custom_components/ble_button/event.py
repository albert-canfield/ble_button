# /config/custom_components/ble_button/event.py

from __future__ import annotations

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CLICK_TYPES, DOMAIN, MODE_MULTI_CLICK
from .coordinator import BleButtonCoordinator
from .entity import BleButtonEntity, entry_mode


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the click event entity (multi-click mode)."""
    if entry_mode(entry) != MODE_MULTI_CLICK:
        return
    coordinator: BleButtonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BleButtonClickEvent(entry, coordinator)])


class BleButtonClickEvent(BleButtonEntity, EventEntity):
    """The button in multi-click mode: single / double / triple / long.

    Named after the device (event.<button_name>); the "click" translation key
    labels the event types.
    """

    _attr_name = None
    _attr_translation_key = "click"
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_event_types = CLICK_TYPES

    def __init__(self, entry: ConfigEntry, coordinator: BleButtonCoordinator) -> None:
        super().__init__(entry, coordinator, "click")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_click_listener(self._async_handle_click)
        )

    @callback
    def _async_handle_click(self, click_type: str) -> None:
        self._trigger_event(click_type)
        self.async_write_ha_state()
