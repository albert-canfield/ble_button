# /config/custom_components/ble_button/__init__.py

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_MAC, CONF_SOURCE, DOMAIN, PLATFORMS, SOURCE_ANY
from .coordinator import BleButtonCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one BLE Button config entry."""
    hass.data.setdefault(DOMAIN, {})

    coordinator = BleButtonCoordinator(
        hass=hass,
        logger=_LOGGER,
        entry=entry,
        address=entry.data[CONF_MAC],
        accepted_source=entry.data.get(CONF_SOURCE, SOURCE_ANY),
    )

    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.async_start())

    _LOGGER.warning(
        "BLE Button DEBUG started: name=%s mac=%s source=%s",
        entry.title,
        entry.data[CONF_MAC],
        entry.data.get(CONF_SOURCE, SOURCE_ANY),
    )

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload BLE Button."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
