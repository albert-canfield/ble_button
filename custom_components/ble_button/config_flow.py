# /config/custom_components/ble_button/config_flow.py

from __future__ import annotations

import asyncio
import re
import time

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.const import CONF_NAME

from .const import (
    CONF_MAC,
    CONF_PRESS_RESET_DELAY,
    CONF_SOURCE,
    DEFAULT_DISCOVERY_SECONDS,
    DEFAULT_PRESS_RESET_DELAY,
    DOMAIN,
    SOURCE_ANY,
)

MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _normalise_mac(mac: str) -> str:
    return mac.strip().upper()


def _normalise_name(name: str) -> str:
    return name.strip()


def _entry_unique_id(mac: str, source: str) -> str:
    return f"{_normalise_mac(mac)}_{source if source == SOURCE_ANY else _normalise_mac(source)}"


def _get_scanner_attr(scanner, attr_name: str):
    try:
        return getattr(scanner, attr_name, None)
    except Exception:
        return None


def _scanner_friendly_name(scanner, source: str) -> str:
    name = (
        _get_scanner_attr(scanner, "name")
        or _get_scanner_attr(scanner, "display_name")
        or _get_scanner_attr(scanner, "title")
        or _get_scanner_attr(scanner, "scanner_name")
    )

    details = _get_scanner_attr(scanner, "scanner_details")
    if isinstance(details, dict):
        for key in ("name", "device_name", "scanner", "adapter", "source_name"):
            if details.get(key):
                name = str(details[key])
                break

    source_upper = source.upper()
    if not name or name == source:
        name = "Bluetooth adapter/proxy"

    return f"{name} ({source_upper})"


def _scanner_choices(hass) -> dict[str, str]:
    choices: dict[str, str] = {SOURCE_ANY: "Any Bluetooth adapter/proxy"}

    try:
        scanners = bluetooth.async_current_scanners(hass)
    except Exception:
        scanners = []

    seen_sources: set[str] = set()

    for scanner in scanners:
        source = _get_scanner_attr(scanner, "source")
        if not source:
            continue

        source_upper = str(source).upper()
        if source_upper in seen_sources:
            continue

        seen_sources.add(source_upper)
        choices[source_upper] = _scanner_friendly_name(scanner, source_upper)

    return choices


def _manual_schema(hass) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=""): str,
            vol.Required(CONF_MAC, default=""): str,
            vol.Optional(CONF_SOURCE, default=SOURCE_ANY): vol.In(_scanner_choices(hass)),
            vol.Optional(CONF_PRESS_RESET_DELAY, default=DEFAULT_PRESS_RESET_DELAY): vol.Coerce(float),
        }
    )


def _discovered_label(item: dict) -> str:
    name = item.get("name") or "Unknown BLE device"
    address = item["address"]
    source = item.get("source") or "unknown source"
    rssi = item.get("rssi")
    age = max(0, int(time.time() - item["last_seen_ts"]))
    rssi_label = f"{rssi} dBm" if rssi is not None else "RSSI unknown"
    return f"{name} — {address} — via {source} — {rssi_label} — {age}s ago"


class BleButtonConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovered: dict[str, dict] = {}
        self._selected: dict | None = None

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            method = user_input["method"]
            if method == "discover":
                return await self.async_step_discover()
            return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required("method", default="discover"): vol.In({
                    "discover": "Add from recent BLE advertisements",
                    "manual": "Add manually",
                })}
            ),
        )

    async def async_step_discover(self, user_input=None):
        if user_input is not None:
            selected_key = user_input["discovered_device"]
            if selected_key == "__refresh__":
                return await self.async_step_discover()
            if selected_key == "__manual__":
                return await self.async_step_manual()
            self._selected = self._discovered.get(selected_key)
            if not self._selected:
                return await self.async_step_discover()
            return await self.async_step_confirm_discovered()

        self._discovered = await self._async_collect_advertisements(DEFAULT_DISCOVERY_SECONDS)

        choices = {
            key: _discovered_label(item)
            for key, item in sorted(
                self._discovered.items(),
                key=lambda pair: pair[1]["last_seen_ts"],
                reverse=True,
            )
        }
        choices["__refresh__"] = "Scan again"
        choices["__manual__"] = "Add manually"

        if not self._discovered:
            choices = {"__refresh__": "No advertisements found — scan again", "__manual__": "Add manually"}

        return self.async_show_form(
            step_id="discover",
            data_schema=vol.Schema({vol.Required("discovered_device"): vol.In(choices)}),
            description_placeholders={"seconds": str(DEFAULT_DISCOVERY_SECONDS)},
        )

    async def async_step_confirm_discovered(self, user_input=None):
        errors = {}

        if not self._selected:
            return await self.async_step_discover()

        discovered_name = self._selected.get("name") or "BLE Button"
        discovered_mac = self._selected["address"]
        discovered_source = self._selected.get("source") or SOURCE_ANY

        if user_input is not None:
            name = _normalise_name(user_input[CONF_NAME])
            source_mode = user_input.get(CONF_SOURCE, discovered_source)
            source = SOURCE_ANY if source_mode == SOURCE_ANY else _normalise_mac(source_mode)
            reset_delay = float(user_input[CONF_PRESS_RESET_DELAY])

            if not name:
                errors[CONF_NAME] = "name_required"
            elif source != SOURCE_ANY and not MAC_RE.match(source):
                errors[CONF_SOURCE] = "invalid_source"
            elif reset_delay <= 0:
                errors[CONF_PRESS_RESET_DELAY] = "invalid_reset_delay"
            else:
                await self.async_set_unique_id(_entry_unique_id(discovered_mac, source))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={CONF_NAME: name, CONF_MAC: discovered_mac, CONF_SOURCE: source},
                    options={CONF_PRESS_RESET_DELAY: reset_delay},
                )

        source_choices = _scanner_choices(self.hass)
        if discovered_source and discovered_source != SOURCE_ANY:
            source_choices.setdefault(discovered_source, f"Detected source ({discovered_source})")

        return self.async_show_form(
            step_id="confirm_discovered",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME, default=discovered_name): str,
                vol.Required(CONF_SOURCE, default=discovered_source): vol.In(source_choices),
                vol.Optional(CONF_PRESS_RESET_DELAY, default=DEFAULT_PRESS_RESET_DELAY): vol.Coerce(float),
            }),
            errors=errors,
            description_placeholders={"mac": discovered_mac, "source": discovered_source, "rssi": str(self._selected.get("rssi"))},
        )

    async def async_step_manual(self, user_input=None):
        errors = {}

        if user_input is not None:
            name = _normalise_name(user_input[CONF_NAME])
            mac = _normalise_mac(user_input[CONF_MAC])
            source = user_input.get(CONF_SOURCE, SOURCE_ANY)
            source = SOURCE_ANY if source == SOURCE_ANY else _normalise_mac(source)
            reset_delay = float(user_input[CONF_PRESS_RESET_DELAY])

            if not name:
                errors[CONF_NAME] = "name_required"
            elif not MAC_RE.match(mac):
                errors[CONF_MAC] = "invalid_mac"
            elif source != SOURCE_ANY and not MAC_RE.match(source):
                errors[CONF_SOURCE] = "invalid_source"
            elif reset_delay <= 0:
                errors[CONF_PRESS_RESET_DELAY] = "invalid_reset_delay"
            else:
                await self.async_set_unique_id(_entry_unique_id(mac, source))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=name,
                    data={CONF_NAME: name, CONF_MAC: mac, CONF_SOURCE: source},
                    options={CONF_PRESS_RESET_DELAY: reset_delay},
                )

        return self.async_show_form(step_id="manual", data_schema=_manual_schema(self.hass), errors=errors)

    @staticmethod
    def async_get_options_flow(config_entry):
        return BleButtonOptionsFlow()

    async def _async_collect_advertisements(self, seconds: int) -> dict[str, dict]:
        discovered: dict[str, dict] = {}

        def _callback(service_info, change) -> None:
            address = (getattr(service_info, "address", None) or "").upper()
            if not address:
                return
            source = (getattr(service_info, "source", None) or "").upper()
            name = getattr(service_info, "name", None)
            rssi = getattr(service_info, "rssi", None)
            key = f"{address}|{source or ''}"
            discovered[key] = {
                "address": address,
                "source": source or SOURCE_ANY,
                "name": name,
                "rssi": rssi,
                "last_seen_ts": time.time(),
            }

        cancel = bluetooth.async_register_callback(
            self.hass,
            _callback,
            {},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        try:
            await asyncio.sleep(seconds)
        finally:
            cancel()

        return discovered


class BleButtonOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        errors = {}
        entry = self.config_entry

        name = entry.data[CONF_NAME]
        mac = entry.data[CONF_MAC]
        current_source = entry.data.get(CONF_SOURCE, SOURCE_ANY)
        current_reset_delay = entry.options.get(CONF_PRESS_RESET_DELAY, DEFAULT_PRESS_RESET_DELAY)

        if user_input is not None:
            source = user_input.get(CONF_SOURCE, current_source)
            source = SOURCE_ANY if source == SOURCE_ANY else _normalise_mac(source)
            reset_delay = float(user_input[CONF_PRESS_RESET_DELAY])

            if source != SOURCE_ANY and not MAC_RE.match(source):
                errors[CONF_SOURCE] = "invalid_source"
            elif reset_delay <= 0:
                errors[CONF_PRESS_RESET_DELAY] = "invalid_reset_delay"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={CONF_NAME: name, CONF_MAC: mac, CONF_SOURCE: source},
                    options={CONF_PRESS_RESET_DELAY: reset_delay},
                )
                return self.async_create_entry(title="", data={})

        source_choices = _scanner_choices(self.hass)
        if current_source != SOURCE_ANY:
            source_choices.setdefault(current_source, f"Current source ({current_source})")

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SOURCE, default=current_source): vol.In(source_choices),
                vol.Optional(CONF_PRESS_RESET_DELAY, default=current_reset_delay): vol.Coerce(float),
            }),
            errors=errors,
            description_placeholders={"name": name, "mac": mac},
        )
