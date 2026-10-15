# /config/custom_components/ble_button/__init__.py

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_MAC, CONF_SOURCE, DOMAIN, PLATFORMS, SOURCE_ANY
from .coordinator import BleButtonCoordinator
from .entity import MODE_ENTITIES, entry_mode, entry_unique_id

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

    # Drop entities this button's mode doesn't create: the other mode's
    # entity after switching modes, and the v2.x text sensor (none/press).
    ent_reg = er.async_get(hass)
    wanted = {
        (platform, entry_unique_id(entry, key))
        for platform, key in MODE_ENTITIES[entry_mode(entry)]
    }
    for entity_entry in er.async_entries_for_config_entry(ent_reg, entry.entry_id):
        if (entity_entry.domain, entity_entry.unique_id) not in wanted:
            ent_reg.async_remove(entity_entry.entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entry.async_on_unload(coordinator.async_start())

    _LOGGER.debug(
        "BLE Button started: name=%s mac=%s source=%s",
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
