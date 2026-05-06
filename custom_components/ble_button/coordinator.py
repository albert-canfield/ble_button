# /config/custom_components/ble_button/coordinator.py

from __future__ import annotations

import asyncio
import copy
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_PRESS_RESET_DELAY,
    DEFAULT_PRESS_RESET_DELAY,
    DUPLICATE_WINDOW_SECONDS,
    EVENT_BLE_BUTTON_DEBUG,
    EVENT_BLE_BUTTON_PRESS,
    SOURCE_ANY,
    STATE_NONE,
    STATE_PRESS,
)


@dataclass
class BleButtonData:
    """Runtime/debug data for one BLE button."""

    state: str = STATE_NONE

    last_seen: str | None = None
    last_press_time: str | None = None
    last_seen_address: str | None = None
    last_rssi: int | None = None
    last_source: str | None = None
    last_name: str | None = None
    last_path: str | None = None

    press_count: int = 0
    press_id: int = 0

    # Listener-path counters
    broad_callback_hits: int = 0
    address_callback_hits: int = 0
    shared_scanner_hits: int = 0

    # Match/decision counters
    matching_mac_seen: int = 0
    accepted_adverts_seen: int = 0
    ignored_wrong_mac: int = 0
    ignored_wrong_source: int = 0
    ignored_duplicate: int = 0

    # Entity/debug counters
    entity_publish_count: int = 0
    debug_event_count: int = 0


class BleButtonCoordinator(DataUpdateCoordinator):
    """Debug coordinator for BLE advertisements.

    It registers THREE listening paths simultaneously:
    1. HA Bluetooth broad callback
    2. HA Bluetooth exact address callback
    3. Shared BleakScanner detection callback

    Payload is ignored. Any matching MAC/source advert becomes:
    none -> press -> none

    The debug attributes show which listener path is actually receiving data.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        entry: ConfigEntry,
        address: str,
        accepted_source: str,
    ) -> None:
        super().__init__(hass=hass, logger=logger, name=f"BLE Button {entry.entry_id}")

        self.entry = entry
        self.address = address.upper()
        self.accepted_source = (
            accepted_source if accepted_source == SOURCE_ANY else accepted_source.upper()
        )
        self.press_reset_delay = float(
            entry.options.get(CONF_PRESS_RESET_DELAY, DEFAULT_PRESS_RESET_DELAY)
        )

        self.data = BleButtonData()
        self._reset_task: asyncio.Task | None = None
        self._last_accept_monotonic = 0.0

    def _publish(self, data: BleButtonData) -> None:
        data.entity_publish_count += 1
        self.async_set_updated_data(copy.deepcopy(data))

    def async_start(self):
        """Start all debug listener paths."""
        unload_callbacks = []

        @callback
        def _broad_callback(service_info, change) -> None:
            self._handle_service_info("broad_callback", service_info)

        @callback
        def _address_callback(service_info, change) -> None:
            self._handle_service_info("address_callback", service_info)

        unload_callbacks.append(
            bluetooth.async_register_callback(
                self.hass,
                _broad_callback,
                {},
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )

        unload_callbacks.append(
            bluetooth.async_register_callback(
                self.hass,
                _address_callback,
                {"address": self.address, "connectable": False},
                bluetooth.BluetoothScanningMode.ACTIVE,
            )
        )

        # Also try the shared scanner path, if supported.
        try:
            scanner = bluetooth.async_get_scanner(self.hass)

            def _scanner_callback(device, advertisement_data) -> None:
                self.hass.loop.call_soon_threadsafe(
                    self._handle_scanner_advertisement,
                    device,
                    advertisement_data,
                )

            unload_callbacks.append(scanner.register_detection_callback(_scanner_callback))
            scanner_status = "registered"
        except Exception as err:  # noqa: BLE001
            scanner_status = f"failed: {err}"

        self.logger.warning(
            "BLE Button DEBUG listeners registered: name=%s mac=%s source=%s shared_scanner=%s",
            self.entry.title,
            self.address,
            self.accepted_source,
            scanner_status,
        )

        def _unload() -> None:
            for unload in unload_callbacks:
                try:
                    unload()
                except Exception:  # noqa: BLE001
                    pass
            if self._reset_task and not self._reset_task.done():
                self._reset_task.cancel()

        return _unload

    @callback
    def _handle_service_info(self, path: str, service_info: Any) -> None:
        """Handle Home Assistant BluetoothServiceInfoBleak."""
        data: BleButtonData = copy.deepcopy(self.data or BleButtonData())

        if path == "broad_callback":
            data.broad_callback_hits += 1
        elif path == "address_callback":
            data.address_callback_hits += 1

        seen_address = (getattr(service_info, "address", "") or "").upper()
        seen_source = (getattr(service_info, "source", None) or "").upper()
        rssi = getattr(service_info, "rssi", None)
        name = getattr(service_info, "name", None)

        self._process_advert(
            data=data,
            path=path,
            seen_address=seen_address,
            seen_source=seen_source,
            rssi=rssi,
            name=name,
        )

    def _handle_scanner_advertisement(self, device: Any, advertisement_data: Any) -> None:
        """Handle shared scanner callback."""
        data: BleButtonData = copy.deepcopy(self.data or BleButtonData())
        data.shared_scanner_hits += 1

        seen_address = (getattr(device, "address", "") or "").upper()
        seen_source = self._extract_source(device, advertisement_data) or ""
        name = getattr(advertisement_data, "local_name", None) or getattr(device, "name", None)
        rssi = getattr(advertisement_data, "rssi", None)
        if rssi is None:
            rssi = getattr(device, "rssi", None)

        self._process_advert(
            data=data,
            path="shared_scanner",
            seen_address=seen_address,
            seen_source=seen_source,
            rssi=rssi,
            name=name,
        )

    def _process_advert(
        self,
        data: BleButtonData,
        path: str,
        seen_address: str,
        seen_source: str,
        rssi: int | None,
        name: str | None,
    ) -> None:
        """Process one advertisement from any listener path."""
        now = datetime.now(timezone.utc).isoformat()

        if seen_address != self.address:
            data.ignored_wrong_mac += 1
            # Publish occasionally so the user knows listeners are alive.
            total_hits = (
                data.broad_callback_hits
                + data.address_callback_hits
                + data.shared_scanner_hits
            )
            if total_hits % 100 == 0:
                data.last_path = path
                data.last_seen_address = seen_address
                data.last_source = seen_source
                data.last_rssi = rssi
                data.last_name = name
                data.last_seen = now
                self._publish(data)
            else:
                self.data = data
            return

        data.matching_mac_seen += 1
        data.last_seen = now
        data.last_seen_address = seen_address
        data.last_source = seen_source or None
        data.last_rssi = rssi
        data.last_name = name
        data.last_path = path

        # Source filter is optional. If HA path does not expose source, accept MAC.
        if (
            self.accepted_source != SOURCE_ANY
            and seen_source
            and seen_source != self.accepted_source
        ):
            data.ignored_wrong_source += 1
            self._publish(data)
            self._fire_debug(data, "ignored_wrong_source")
            self.logger.warning(
                "BLE Button DEBUG ignored source: path=%s name=%s mac=%s configured_source=%s seen_source=%s rssi=%s",
                path,
                self.entry.title,
                self.address,
                self.accepted_source,
                seen_source,
                rssi,
            )
            return

        now_mono = time.monotonic()
        if now_mono - self._last_accept_monotonic < DUPLICATE_WINDOW_SECONDS:
            data.ignored_duplicate += 1
            self._publish(data)
            self._fire_debug(data, "ignored_duplicate")
            return

        self._last_accept_monotonic = now_mono

        if data.state != STATE_NONE:
            data.state = STATE_NONE
            self._publish(data)

        data.state = STATE_PRESS
        data.accepted_adverts_seen += 1
        data.press_count += 1
        data.press_id += 1
        data.last_press_time = now

        self.hass.bus.async_fire(
            EVENT_BLE_BUTTON_PRESS,
            {
                "name": self.entry.title,
                "mac": self.address,
                "accepted_source": self.accepted_source,
                "path": path,
                "source": data.last_source,
                "rssi": data.last_rssi,
                "press_count": data.press_count,
                "press_id": data.press_id,
            },
        )

        self._fire_debug(data, "accepted_press")

        self.logger.warning(
            "BLE Button DEBUG accepted press: path=%s name=%s mac=%s source=%s rssi=%s press_id=%s",
            path,
            self.entry.title,
            self.address,
            data.last_source,
            data.last_rssi,
            data.press_id,
        )

        if self._reset_task and not self._reset_task.done():
            self._reset_task.cancel()

        self._publish(data)

        self._reset_task = self.hass.loop.create_task(
            self._async_reset_state(data.press_id)
        )

    def _fire_debug(self, data: BleButtonData, decision: str) -> None:
        data.debug_event_count += 1
        self.hass.bus.async_fire(
            EVENT_BLE_BUTTON_DEBUG,
            {
                "name": self.entry.title,
                "mac": self.address,
                "decision": decision,
                "state": data.state,
                "last_path": data.last_path,
                "last_source": data.last_source,
                "last_rssi": data.last_rssi,
                "press_id": data.press_id,
                "press_count": data.press_count,
                "matching_mac_seen": data.matching_mac_seen,
                "accepted_adverts_seen": data.accepted_adverts_seen,
                "ignored_wrong_source": data.ignored_wrong_source,
                "ignored_duplicate": data.ignored_duplicate,
                "broad_callback_hits": data.broad_callback_hits,
                "address_callback_hits": data.address_callback_hits,
                "shared_scanner_hits": data.shared_scanner_hits,
            },
        )

    async def _async_reset_state(self, press_id: int) -> None:
        """Reset state to none after pulse."""
        try:
            await asyncio.sleep(self.press_reset_delay)
        except asyncio.CancelledError:
            return

        data: BleButtonData = copy.deepcopy(self.data or BleButtonData())

        if data.press_id != press_id:
            return

        data.state = STATE_NONE
        self._publish(data)

    def _extract_source(self, device: Any, advertisement_data: Any) -> str | None:
        for obj in (device, advertisement_data):
            source = getattr(obj, "source", None)
            if source:
                return str(source).upper()

        details = getattr(device, "details", None)
        if isinstance(details, dict):
            for key in ("source", "adapter", "scanner", "scanner_source"):
                if details.get(key):
                    return str(details[key]).upper()

        metadata = getattr(device, "metadata", None)
        if isinstance(metadata, dict):
            for key in ("source", "adapter", "scanner", "scanner_source"):
                if metadata.get(key):
                    return str(metadata[key]).upper()

        return None
