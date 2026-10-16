"""Config entry diagnostics."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)
from homeassistant.helpers.json import json_dumps
from homeassistant.util.json import json_loads

from custom_components.ble_button.const import SOURCE_ANY
from custom_components.ble_button.diagnostics import (
    async_get_config_entry_diagnostics,
)

from . import MAC, OTHER_MAC, PROXY, press, setup_entry


async def get_diagnostics_for_config_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> dict:
    """An entry's diagnostics as the downloaded file would contain them.

    Round-trips through HA's JSON encoder, like the download does, so
    anything that can't be serialised fails here.
    """
    return json_loads(json_dumps(await async_get_config_entry_diagnostics(hass, entry)))


async def test_entry_diagnostics(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
) -> None:
    coordinator = await setup_entry(hass, mock_entry)
    press(coordinator, rssi=-50)
    press(coordinator, address=OTHER_MAC)
    await hass.async_block_till_done()

    diag = await get_diagnostics_for_config_entry(hass, mock_entry)

    assert diag["entry"] == {
        "title": "Desk Button",
        "data": {"name": "Desk Button", "mac": MAC, "source": SOURCE_ANY},
        "options": {"press_reset_delay": 0.6},
    }
    assert diag["coordinator"] == {
        "address": MAC,
        "accepted_source": SOURCE_ANY,
        "press_reset_delay": 0.6,
        "mode": "instant",
        "click_window": 2.0,
        "tracks_every_advert": False,
    }
    data = diag["data"]
    assert data["press_count"] == 1
    assert data["pressed"] is True
    assert data["last_rssi"] == -50
    assert data["last_source"] == PROXY
    assert data["address_callback_hits"] == 2
    assert data["ignored_wrong_mac"] == 1
    for key in (
        "broad_callback_hits",
        "matching_mac_seen",
        "accepted_adverts_seen",
        "ignored_wrong_source",
        "ignored_duplicate",
        "entity_publish_count",
        "debug_event_count",
        "last_press_time",
    ):
        assert key in data

    async_fire_time_changed_exact(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()
