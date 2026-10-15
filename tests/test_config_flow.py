"""Config flow and options flow tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ble_button.const import (
    CONF_CLICK_WINDOW,
    CONF_MAC,
    CONF_MODE,
    CONF_PRESS_RESET_DELAY,
    CONF_SOURCE,
    DEFAULT_CLICK_WINDOW,
    DEFAULT_DISCOVERY_SECONDS,
    DOMAIN,
    SOURCE_ANY,
)

from . import MAC, OTHER_MAC, PROXY, inject_advertisement, make_entry, setup_entry

MANUAL_INPUT = {
    CONF_NAME: "  Desk Button  ",
    CONF_MAC: "aa:bb:cc:dd:ee:ff",
    CONF_SOURCE: SOURCE_ANY,
    CONF_PRESS_RESET_DELAY: 0.8,
}


async def _start_manual(hass: HomeAssistant) -> dict:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"method": "manual"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {}
    return result


async def test_manual_flow_creates_entry(hass: HomeAssistant) -> None:
    """User -> manual -> entry with normalised data/options, which then loads."""
    result = await _start_manual(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MANUAL_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Desk Button"
    assert result["data"] == {
        CONF_NAME: "Desk Button",
        CONF_MAC: MAC,
        CONF_SOURCE: SOURCE_ANY,
    }
    assert result["options"] == {
        CONF_MODE: "instant",
        CONF_PRESS_RESET_DELAY: 0.8,
        CONF_CLICK_WINDOW: DEFAULT_CLICK_WINDOW,
    }
    assert result["result"].unique_id == f"{MAC}_{SOURCE_ANY}"
    assert result["result"].state is ConfigEntryState.LOADED
    assert hass.states.get("binary_sensor.desk_button").state == "off"


@pytest.mark.parametrize(
    ("user_input", "field", "error"),
    [
        ({CONF_MAC: "AA:BB:CC:DD:EE"}, CONF_MAC, "invalid_mac"),
        ({CONF_MAC: "not-a-mac"}, CONF_MAC, "invalid_mac"),
        ({CONF_NAME: "   "}, CONF_NAME, "name_required"),
        ({CONF_PRESS_RESET_DELAY: 0}, CONF_PRESS_RESET_DELAY, "invalid_reset_delay"),
    ],
)
async def test_manual_flow_errors(
    hass: HomeAssistant, user_input: dict, field: str, error: str
) -> None:
    """Invalid input re-shows the form with the right error, then recovers."""
    result = await _start_manual(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**MANUAL_INPUT, **user_input}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"
    assert result["errors"] == {field: error}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MANUAL_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_manual_flow_duplicate_aborts(hass: HomeAssistant) -> None:
    """Same MAC + source as an existing entry aborts already_configured."""
    make_entry().add_to_hass(hass)  # unique_id AA:BB:CC:DD:EE:FF_any
    result = await _start_manual(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], MANUAL_INPUT
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _discovery_choices(result: dict) -> dict[str, str]:
    return result["data_schema"].schema["discovered_device"].container


async def _run_discovery(hass: HomeAssistant, adverts: list[dict]) -> dict:
    """Run user -> discover, injecting adverts live during the scan window."""

    async def _fake_sleep(seconds: float) -> None:
        assert seconds == DEFAULT_DISCOVERY_SECONDS
        for advert in adverts:
            inject_advertisement(**advert)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    # Only the flow module's asyncio is replaced; the event loop is untouched.
    with patch(
        "custom_components.ble_button.config_flow.asyncio",
        SimpleNamespace(sleep=_fake_sleep),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"method": "discover"}
        )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discover"
    return result


async def test_discovery_flow_creates_entry(hass: HomeAssistant) -> None:
    """Discover -> pick device -> confirm -> entry bound to the seen source."""
    result = await _run_discovery(
        hass, [{"address": MAC, "source": PROXY, "connectable": True, "rssi": -55}]
    )
    key = f"{MAC}|{PROXY}"
    choices = _discovery_choices(result)
    assert key in choices
    assert "__refresh__" in choices and "__manual__" in choices

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"discovered_device": key}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "confirm_discovered"
    assert result["description_placeholders"]["mac"] == MAC

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_NAME: "Desk Button", CONF_SOURCE: PROXY, CONF_PRESS_RESET_DELAY: 0.6},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_NAME: "Desk Button", CONF_MAC: MAC, CONF_SOURCE: PROXY}
    assert result["result"].unique_id == f"{MAC}_{PROXY}"


async def test_discovery_lists_non_connectable_buttons(hass: HomeAssistant) -> None:
    """Advert-only buttons (non-connectable, e.g. via passive proxies) must be listed.

    HA's bluetooth manager only delivers connectable adverts to callbacks whose
    matcher does not say ``connectable: False``; the discovery collector
    registers with ``{}``.
    """
    result = await _run_discovery(
        hass,
        [
            {"address": OTHER_MAC, "source": PROXY, "connectable": True},
            {"address": MAC, "source": PROXY, "connectable": False},
        ],
    )
    choices = _discovery_choices(result)
    assert f"{OTHER_MAC}|{PROXY}" in choices
    assert f"{MAC}|{PROXY}" in choices, (
        f"non-connectable button missing from discovery list: {list(choices)}"
    )


async def test_discovery_nothing_found_offers_manual(hass: HomeAssistant) -> None:
    """An empty scan offers rescan/manual, and manual works from there."""
    result = await _run_discovery(hass, [])
    assert set(_discovery_choices(result)) == {"__refresh__", "__manual__"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"discovered_device": "__manual__"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


async def test_options_flow_updates_delay_and_source(hass: HomeAssistant) -> None:
    """Options flow stores the new reset delay/source and reloads the entry."""
    entry: MockConfigEntry = make_entry(reset_delay=0.6)
    await setup_entry(hass, entry)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SOURCE: SOURCE_ANY, CONF_PRESS_RESET_DELAY: 1.5}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    assert entry.data[CONF_SOURCE] == SOURCE_ANY
    assert entry.options.get(CONF_PRESS_RESET_DELAY) == 1.5, (
        f"reset delay lost after options flow, options={dict(entry.options)}"
    )
    assert hass.data[DOMAIN][entry.entry_id].press_reset_delay == 1.5
