"""End-to-end through HA's real BluetoothManager (adverts injected as a scanner would).

These prove the integration's callback registrations work against the current
bluetooth stack, not just its internal handler.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from unittest.mock import patch
import warnings

import pytest

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)

from custom_components.ble_button.const import DUPLICATE_WINDOW_SECONDS

from . import BINARY_ID, LAST_PRESSED_ID, inject_advertisement, setup_entry


async def _finish_pulse(hass: HomeAssistant) -> None:
    async_fire_time_changed_exact(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()


async def test_non_connectable_advert_is_a_press(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """Typical advert-only button: arrives via the address callback."""
    coordinator = await setup_entry(hass, mock_entry)
    inject_advertisement(connectable=False, rssi=-71)
    await hass.async_block_till_done()

    assert hass.states.get(BINARY_ID).state == STATE_ON
    assert len(press_events) == 1
    assert press_events[0].data["path"] == "address_callback"
    assert press_events[0].data["rssi"] == -71
    assert coordinator.data.address_callback_hits == 1
    assert hass.states.get(LAST_PRESSED_ID).state != "unknown"
    await _finish_pulse(hass)
    assert hass.states.get(BINARY_ID).state == STATE_OFF


async def test_connectable_advert_hits_all_paths_but_counts_once(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """Every registered path fires; the de-dup window keeps it to one press."""
    coordinator = await setup_entry(hass, mock_entry)
    inject_advertisement(connectable=True)
    await hass.async_block_till_done()

    data = coordinator.data
    assert data.broad_callback_hits == 1
    assert data.address_callback_hits == 1
    assert data.press_count == 1
    assert data.ignored_duplicate == 1
    assert len(press_events) == 1
    await _finish_pulse(hass)


async def test_changed_payload_presses_are_all_seen(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """Buttons with a rolling counter in the payload: every press is delivered."""
    coordinator = await setup_entry(hass, mock_entry)
    for counter in range(3):
        inject_advertisement(manufacturer_data={0x1234: bytes([counter])})
        await hass.async_block_till_done()
        await asyncio.sleep(DUPLICATE_WINDOW_SECONDS + 0.02)
    assert coordinator.data.press_count == 3
    assert len(press_events) == 3
    await _finish_pulse(hass)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HA's BluetoothManager drops adverts whose payload is unchanged before "
        "async_register_callback callbacks run, so a button that sends an "
        "identical payload on every press only registers the first press "
        "(until HA marks the device stale). Limitation of the callback API used."
    ),
)
async def test_identical_payload_presses_are_all_seen(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    coordinator = await setup_entry(hass, mock_entry)
    for _ in range(3):
        inject_advertisement()
        await hass.async_block_till_done()
        await asyncio.sleep(DUPLICATE_WINDOW_SECONDS + 0.02)
    try:
        assert len(press_events) == 3, f"only {len(press_events)} press(es) seen"
    finally:
        await _finish_pulse(hass)
        assert coordinator.data.press_count == len(press_events)


async def test_no_deprecation_warnings_against_current_ha(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Setup + a press must not trip HA/habluetooth deprecation reporting."""
    caplog.set_level(logging.WARNING)
    # report_usage() logs each offending call site only once per process.
    with (
        patch("homeassistant.helpers.frame._REPORTED_INTEGRATIONS", set()),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        await setup_entry(hass, mock_entry)
        inject_advertisement()
        await hass.async_block_till_done()
        await _finish_pulse(hass)

    logged = [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and "deprecated" in r.getMessage()
    ]
    raised = [
        f"{w.filename}:{w.lineno}: {w.message}"
        for w in caught
        if issubclass(w.category, DeprecationWarning) and "ble_button" in w.filename
    ]
    assert not logged and not raised, "\n".join(logged + raised)
