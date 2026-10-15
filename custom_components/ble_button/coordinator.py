# /config/custom_components/ble_button/coordinator.py

from __future__ import annotations

import asyncio
import copy
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .clicks import ClickDetector
from .const import (
    CONF_CLICK_WINDOW,
    CONF_MODE,
    CONF_PRESS_RESET_DELAY,
    DEFAULT_CLICK_WINDOW,
    DEFAULT_MODE,
    DEFAULT_PRESS_RESET_DELAY,
    DUPLICATE_WINDOW_SECONDS,
    DOMAIN,
    EVENT_BLE_BUTTON_CLICK,
    EVENT_BLE_BUTTON_DEBUG,
    EVENT_BLE_BUTTON_PRESS,
    MAX_COUNTER_STEP,
    MODE_MULTI_CLICK,
    SOURCE_ANY,
)
from .decoder import DecodedAdvert, decode


@dataclass
class BleButtonData:
    """Runtime/debug data for one BLE button."""

    pressed: bool = False

    last_seen: str | None = None
    last_press_time: str | None = None
    last_seen_address: str | None = None
    last_rssi: int | None = None
    last_source: str | None = None
    last_name: str | None = None
    last_path: str | None = None

    press_count: int = 0
    press_id: int = 0

    # Click detection
    protocol: str | None = None
    last_counter: int | None = None
    last_click_type: str | None = None
    click_count: int = 0

    # Listener-path counters
    broad_callback_hits: int = 0
    address_callback_hits: int = 0

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

    It registers two listening paths simultaneously:
    1. HA Bluetooth broad callback
    2. HA Bluetooth exact address callback (connectable or not)

    Any changed advert from the configured MAC/source is a press:
    off -> on -> off. In multi-click mode presses are grouped into single /
    double / triple / long clicks (clicks.py). Both work for any button; a
    button profile (decoder.py) only adds accuracy for formats it knows.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        logger: logging.Logger,
        entry: ConfigEntry,
        address: str,
        accepted_source: str,
    ) -> None:
        super().__init__(
            hass=hass,
            logger=logger,
            config_entry=entry,
            name=f"BLE Button {entry.entry_id}",
        )

        self.entry = entry
        self.address = address.upper()
        self.accepted_source = (
            accepted_source if accepted_source == SOURCE_ANY else accepted_source.upper()
        )
        self.press_reset_delay = float(
            entry.options.get(CONF_PRESS_RESET_DELAY, DEFAULT_PRESS_RESET_DELAY)
        )
        self.click_window = float(
            entry.options.get(CONF_CLICK_WINDOW, DEFAULT_CLICK_WINDOW)
        )
        self.mode = entry.options.get(CONF_MODE, DEFAULT_MODE)
        self.multi_click = self.mode == MODE_MULTI_CLICK

        self.data = BleButtonData()
        self._reset_task: asyncio.Task | None = None
        self._last_accept_monotonic = 0.0
        self._replaying = False
        self._last_counter: int | None = None
        self._long_press_counter: int | None = None
        self._clicks = ClickDetector(hass, self.click_window, self._emit_click)
        self._click_listeners: set[Callable[[str], None]] = set()

    @callback
    def async_add_click_listener(
        self, listener: Callable[[str], None]
    ) -> Callable[[], None]:
        """Call ``listener(click_type)`` on every detected click."""
        self._click_listeners.add(listener)
        return lambda: self._click_listeners.discard(listener)

    def _device_id(self) -> str | None:
        devices = dr.async_entries_for_config_entry(
            dr.async_get(self.hass), self.entry.entry_id
        )
        return devices[0].id if devices else None

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

        # HA replays cached adverts to new callbacks synchronously inside
        # async_register_callback; those are not presses.
        self._replaying = True
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
        self._replaying = False

        # Multi-click on HA 2026.10+: also see the identical repeats a held
        # button sends, which the change-based callbacks above filter out.
        register_every_advert = getattr(
            bluetooth, "async_register_advertisement_callback", None
        )
        if self.multi_click and register_every_advert is not None:
            unload_callbacks.append(
                register_every_advert(self.hass, self._handle_every_advert, self.address)
            )
            self._clicks.tracks_activity = True

        self.logger.debug(
            "BLE Button listeners registered: name=%s mac=%s source=%s mode=%s "
            "every_advert=%s",
            self.entry.title,
            self.address,
            self.accepted_source,
            self.mode,
            self._clicks.tracks_activity,
        )

        def _unload() -> None:
            for unload in unload_callbacks:
                try:
                    unload()
                except Exception:  # noqa: BLE001
                    pass
            if self._reset_task and not self._reset_task.done():
                self._reset_task.cancel()
            self._clicks.cancel()

        return _unload

    @callback
    def _handle_every_advert(self, service_info: Any) -> None:
        """Note that the button is (still) transmitting, repeats included."""
        if self.accepted_source != SOURCE_ANY and (
            (getattr(service_info, "source", None) or "").upper()
            not in ("", self.accepted_source)
        ):
            return
        self._clicks.note_activity()

    @callback
    def _handle_service_info(self, path: str, service_info: Any) -> None:
        """Handle Home Assistant BluetoothServiceInfoBleak."""
        seen_address = (getattr(service_info, "address", "") or "").upper()
        decoded = decode(getattr(service_info, "manufacturer_data", None) or {})

        if self._replaying:
            # Not a press, but remember the button's counter so the first real
            # press after a reload/restart isn't counted as several.
            if decoded is not None and seen_address == self.address:
                self._last_counter = decoded.counter
                if decoded.long_press:
                    self._long_press_counter = decoded.counter
            return

        data: BleButtonData = copy.deepcopy(self.data or BleButtonData())

        if path == "broad_callback":
            data.broad_callback_hits += 1
        elif path == "address_callback":
            data.address_callback_hits += 1

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
            decoded=decoded,
        )

    def _process_advert(
        self,
        data: BleButtonData,
        path: str,
        seen_address: str,
        seen_source: str,
        rssi: int | None,
        name: str | None,
        decoded: DecodedAdvert | None = None,
    ) -> None:
        """Process one advertisement from any listener path."""
        now = datetime.now(timezone.utc).isoformat()

        if seen_address != self.address:
            # Counted silently; publishing here would write a recorder row for
            # unrelated nearby BLE traffic. Counters show on the next press.
            data.ignored_wrong_mac += 1
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
            self.logger.debug(
                "BLE Button ignored source: path=%s name=%s mac=%s configured_source=%s seen_source=%s rssi=%s",
                path,
                self.entry.title,
                self.address,
                self.accepted_source,
                seen_source,
                rssi,
            )
            return

        if decoded is not None:
            presses, long_press = self._decoded_presses(decoded)
            data.protocol = decoded.protocol
            data.last_counter = decoded.counter
        else:
            now_mono = time.monotonic()
            if now_mono - self._last_accept_monotonic < DUPLICATE_WINDOW_SECONDS:
                presses = 0
            else:
                self._last_accept_monotonic = now_mono
                presses = 1
            long_press = False

        if self.multi_click:
            if long_press:
                self._clicks.long_press()
            elif presses and not self._clicks.press(
                presses,
                certain=decoded is not None,
                may_be_held=decoded is not None,
            ):
                presses = 0  # payload changed while the button is held

        if not presses:
            # Repeat of a press already handled, or only its long-press flag.
            if not long_press:
                data.ignored_duplicate += 1
            self._publish(data)
            self._fire_debug(data, "long_press" if long_press else "ignored_duplicate")
            return

        # A press while still "on" is published as off -> on so state
        # triggers fire for every press.
        if data.pressed:
            data.pressed = False
            self._publish(data)

        data.pressed = True
        data.accepted_adverts_seen += 1
        data.press_count += presses
        data.press_id += 1
        data.last_press_time = now

        self.hass.bus.async_fire(
            EVENT_BLE_BUTTON_PRESS,
            {
                "device_id": self._device_id(),
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

        self.logger.debug(
            "BLE Button accepted press: path=%s name=%s mac=%s source=%s rssi=%s press_id=%s",
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

        self._reset_task = self.entry.async_create_background_task(
            self.hass,
            self._async_reset_state(data.press_id),
            name=f"ble_button reset {self.address}",
        )

    def _decoded_presses(self, decoded: DecodedAdvert) -> tuple[int, bool]:
        """Return (new presses, new long press) from a decoded advert."""
        if self._last_counter is None:
            presses = 1
        else:
            presses = (decoded.counter - self._last_counter) % 256
            if presses > MAX_COUNTER_STEP:
                presses = 1
        self._last_counter = decoded.counter

        long_press = (
            decoded.long_press and decoded.counter != self._long_press_counter
        )
        if long_press:
            self._long_press_counter = decoded.counter
        return presses, long_press

    @callback
    def _emit_click(self, click_type: str) -> None:
        """Publish a detected click to the bus, triggers and event entity."""
        data: BleButtonData = copy.deepcopy(self.data)
        data.last_click_type = click_type
        data.click_count += 1
        self.data = data

        self.hass.bus.async_fire(
            EVENT_BLE_BUTTON_CLICK,
            {
                "device_id": self._device_id(),
                "name": self.entry.title,
                "mac": self.address,
                "click_type": click_type,
            },
        )
        for listener in list(self._click_listeners):
            listener(click_type)

        self.logger.debug(
            "BLE Button click: name=%s mac=%s type=%s",
            self.entry.title,
            self.address,
            click_type,
        )

    def _fire_debug(self, data: BleButtonData, decision: str) -> None:
        data.debug_event_count += 1
        self.hass.bus.async_fire(
            EVENT_BLE_BUTTON_DEBUG,
            {
                "name": self.entry.title,
                "mac": self.address,
                "decision": decision,
                "state": "on" if data.pressed else "off",
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
            },
        )

    async def _async_reset_state(self, press_id: int) -> None:
        """Reset state to off after pulse."""
        try:
            await asyncio.sleep(self.press_reset_delay)
        except asyncio.CancelledError:
            return

        data: BleButtonData = copy.deepcopy(self.data or BleButtonData())

        if data.press_id != press_id:
            return

        data.pressed = False
        self._publish(data)
