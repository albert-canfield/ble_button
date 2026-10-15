# /config/custom_components/ble_button/diagnostics.py

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import BleButtonCoordinator


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return listener counters and last-seen details for one button."""
    coordinator: BleButtonCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": {
            "address": coordinator.address,
            "accepted_source": coordinator.accepted_source,
            "press_reset_delay": coordinator.press_reset_delay,
            "mode": coordinator.mode,
            "click_window": coordinator.click_window,
            "tracks_every_advert": coordinator._clicks.tracks_activity,
        },
        "data": asdict(coordinator.data),
    }
