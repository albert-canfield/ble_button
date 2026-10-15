"""Tests for the BLE Button custom integration (shared helpers)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bluetooth_data_tools import monotonic_time_coarse
from habluetooth import BluetoothServiceInfoBleak, get_manager

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ble_button.const import (
    CONF_MAC,
    CONF_PRESS_RESET_DELAY,
    CONF_SOURCE,
    DEFAULT_PRESS_RESET_DELAY,
    DOMAIN,
    SOURCE_ANY,
)
from custom_components.ble_button.coordinator import BleButtonCoordinator

BUTTON_NAME = "Desk Button"
MAC = "AA:BB:CC:DD:EE:FF"
OTHER_MAC = "11:22:33:44:55:66"
PROXY = "C0:FF:EE:00:00:01"
OTHER_PROXY = "C0:FF:EE:00:00:02"

BINARY_ID = "binary_sensor.desk_button"
LAST_PRESSED_ID = "sensor.desk_button_last_pressed"
SIGNAL_ID = "sensor.desk_button_signal_strength"

PRESS_UID = "ble_button_aabbccddeeff_any_press"
LAST_PRESSED_UID = "ble_button_aabbccddeeff_any_last_pressed"
SIGNAL_UID = "ble_button_aabbccddeeff_any_signal_strength"


def make_entry(
    *,
    mac: str = MAC,
    source: str = SOURCE_ANY,
    name: str = BUTTON_NAME,
    reset_delay: float = DEFAULT_PRESS_RESET_DELAY,
) -> MockConfigEntry:
    """Build a config entry shaped like the one the config flow creates."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        unique_id=f"{mac}_{source}",
        data={CONF_NAME: name, CONF_MAC: mac, CONF_SOURCE: source},
        options={CONF_PRESS_RESET_DELAY: reset_delay},
    )


async def setup_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> BleButtonCoordinator:
    """Add (if needed) and set up an entry, returning its coordinator."""
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return hass.data[DOMAIN][entry.entry_id]


def get_device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Return the single device of an entry (non-deprecated registry lookup)."""
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    assert len(devices) == 1
    return devices[0]


def fake_service_info(
    address: str = MAC, source: str = PROXY, rssi: int = -60, name: str = "Button"
) -> Any:
    """Minimal stand-in for BluetoothServiceInfoBleak."""
    return SimpleNamespace(address=address, source=source, rssi=rssi, name=name)


def press(coordinator: BleButtonCoordinator, **kwargs: Any) -> None:
    """Feed one advert straight into the coordinator's address-callback path."""
    coordinator._handle_service_info("address_callback", fake_service_info(**kwargs))


def inject_advertisement(
    address: str = MAC,
    source: str = PROXY,
    rssi: int = -60,
    name: str = "Button",
    connectable: bool = False,
    manufacturer_data: dict[int, bytes] | None = None,
) -> None:
    """Inject an advert into HA's real BluetoothManager, as a scanner would."""
    # 0x1234 matches no HA integration matcher (0xFFFF would trigger kegtron).
    manufacturer_data = manufacturer_data or {0x1234: b"\x01\x02"}
    adv = AdvertisementData(
        local_name=name,
        manufacturer_data=manufacturer_data,
        service_data={},
        service_uuids=[],
        tx_power=None,
        rssi=rssi,
        platform_data=(),
    )
    device = BLEDevice(address, name, {"source": source})
    get_manager().scanner_adv_received(
        BluetoothServiceInfoBleak(
            name=name,
            address=address,
            rssi=rssi,
            manufacturer_data=manufacturer_data,
            service_data={},
            service_uuids=[],
            source=source,
            device=device,
            advertisement=adv,
            connectable=connectable,
            time=monotonic_time_coarse(),
            tx_power=None,
        )
    )
