# /config/custom_components/ble_button/sensor.py

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, CONF_SOURCE, DOMAIN, SOURCE_ANY, STATE_NONE
from .coordinator import BleButtonCoordinator, BleButtonData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one BLE Button press sensor from one coordinator."""
    coordinator: BleButtonCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([BleButtonPressSensor(entry, coordinator)])


class BleButtonPressSensor(CoordinatorEntity, SensorEntity):
    """BLE button press sensor with debug attributes."""

    _attr_should_poll = False
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, entry: ConfigEntry, coordinator: BleButtonCoordinator) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._button_name = entry.data[CONF_NAME]
        self._mac = entry.data[CONF_MAC].upper()
        self._source = entry.data.get(CONF_SOURCE, SOURCE_ANY)
        self._source = self._source if self._source == SOURCE_ANY else self._source.upper()
        source_id = "any" if self._source == SOURCE_ANY else self._source.replace(":", "").lower()

        self._attr_name = f"{self._button_name} Press"
        self._attr_unique_id = f"{DOMAIN}_{self._mac.replace(':', '').lower()}_{source_id}_press"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.entry.entry_id)},
            name=self._button_name,
            manufacturer="Generic BLE",
            model="Advertisement Button",
            connections={("bluetooth", self._mac)},
        )

    @property
    def native_value(self) -> str:
        data: BleButtonData | None = self.coordinator.data
        if data is None:
            return STATE_NONE
        return data.state

    @property
    def extra_state_attributes(self) -> dict:
        data: BleButtonData | None = self.coordinator.data

        if data is None:
            return {
                "configured_mac": self._mac,
                "accepted_source": self._source,
                "state_note": "coordinator has no data yet",
            }

        return {
            "configured_mac": self._mac,
            "accepted_source": self._source,
            "last_seen": data.last_seen,
            "last_press_time": data.last_press_time,
            "last_seen_address": data.last_seen_address,
            "last_rssi": data.last_rssi,
            "last_source": data.last_source,
            "last_name": data.last_name,
            "last_path": data.last_path,
            "press_reset_delay": self.coordinator.press_reset_delay,
            "press_count": data.press_count,
            "press_id": data.press_id,
            "broad_callback_hits": data.broad_callback_hits,
            "address_callback_hits": data.address_callback_hits,
            "shared_scanner_hits": data.shared_scanner_hits,
            "matching_mac_seen": data.matching_mac_seen,
            "accepted_adverts_seen": data.accepted_adverts_seen,
            "ignored_wrong_mac": data.ignored_wrong_mac,
            "ignored_wrong_source": data.ignored_wrong_source,
            "ignored_duplicate": data.ignored_duplicate,
            "entity_publish_count": data.entity_publish_count,
            "debug_event_count": data.debug_event_count,
        }
