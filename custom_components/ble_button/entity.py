# /config/custom_components/ble_button/entity.py

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MAC, CONF_SOURCE, DOMAIN, SOURCE_ANY
from .coordinator import BleButtonCoordinator


def entity_unique_id(mac: str, source: str, key: str) -> str:
    """Unique ID shared by every entity of one button/source pair."""
    source_id = "any" if source == SOURCE_ANY else source.replace(":", "").lower()
    return f"{DOMAIN}_{mac.replace(':', '').lower()}_{source_id}_{key}"


class BleButtonEntity(CoordinatorEntity[BleButtonCoordinator]):
    """Base entity: one device per config entry."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, entry: ConfigEntry, coordinator: BleButtonCoordinator, key: str
    ) -> None:
        super().__init__(coordinator)
        mac = entry.data[CONF_MAC].upper()
        source = entry.data.get(CONF_SOURCE, SOURCE_ANY)
        source = source if source == SOURCE_ANY else source.upper()

        self._attr_unique_id = entity_unique_id(mac, source, key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.data[CONF_NAME],
            manufacturer="Generic BLE",
            model="Advertisement Button",
            connections={(CONNECTION_BLUETOOTH, mac)},
        )
