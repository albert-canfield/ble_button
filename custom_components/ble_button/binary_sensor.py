# /config/custom_components/ble_button/binary_sensor.py

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import BleButtonCoordinator
from .entity import BleButtonEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one BLE Button press binary sensor from one coordinator."""
    coordinator: BleButtonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BleButtonPressBinarySensor(entry, coordinator)])


class BleButtonPressBinarySensor(BleButtonEntity, BinarySensorEntity):
    """The button itself: on while pressed, off otherwise.

    Named after the device (binary_sensor.<button_name>). The "press"
    translation key labels the states Pressed / Not pressed in the UI, while
    automations keep using the raw "on" / "off" states.
    """

    _attr_name = None
    _attr_translation_key = "press"

    def __init__(self, entry: ConfigEntry, coordinator: BleButtonCoordinator) -> None:
        super().__init__(entry, coordinator, "press")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.pressed
