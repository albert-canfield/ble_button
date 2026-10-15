# /config/custom_components/ble_button/sensor.py

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import BleButtonCoordinator
from .entity import BleButtonEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BLE Button companion sensors."""
    coordinator: BleButtonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            BleButtonLastPressedSensor(entry, coordinator),
            BleButtonSignalStrengthSensor(entry, coordinator),
        ]
    )


class BleButtonLastPressedSensor(BleButtonEntity, RestoreSensor):
    """Time of the last accepted press, kept across restarts."""

    _attr_translation_key = "last_pressed"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, entry: ConfigEntry, coordinator: BleButtonCoordinator) -> None:
        super().__init__(entry, coordinator, "last_pressed")
        self._restored: datetime | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, datetime):
            self._restored = last.native_value

    @property
    def native_value(self) -> datetime | None:
        last_press_time = self.coordinator.data.last_press_time
        if last_press_time is None:
            return self._restored
        return dt_util.parse_datetime(last_press_time)


class BleButtonSignalStrengthSensor(BleButtonEntity, SensorEntity):
    """RSSI of the last advertisement received from the button."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, entry: ConfigEntry, coordinator: BleButtonCoordinator) -> None:
        super().__init__(entry, coordinator, "signal_strength")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.last_rssi
