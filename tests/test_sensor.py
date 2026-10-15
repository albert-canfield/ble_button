"""Last pressed (restore) and Signal strength (disabled diagnostic) sensors."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    STATE_UNKNOWN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_fire_time_changed_exact,
    mock_restore_cache_with_extra_data,
)

from custom_components.ble_button.const import DOMAIN

from . import LAST_PRESSED_ID, SIGNAL_ID, press, setup_entry

RESTORED = "2026-10-01T12:00:00+00:00"


async def _finish_pulse(hass: HomeAssistant) -> None:
    async_fire_time_changed_exact(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()


async def test_last_pressed_updates_on_press(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    coordinator = await setup_entry(hass, mock_entry)
    state = hass.states.get(LAST_PRESSED_ID)
    assert state.state == STATE_UNKNOWN
    assert state.attributes["device_class"] == "timestamp"
    assert state.attributes["friendly_name"] == "Desk Button Last pressed"

    before = dt_util.utcnow()
    press(coordinator)
    await hass.async_block_till_done()
    value = dt_util.parse_datetime(hass.states.get(LAST_PRESSED_ID).state)
    assert value is not None and value.tzinfo is not None
    assert before - timedelta(seconds=1) <= value <= dt_util.utcnow()

    # The pulse reset does not touch the timestamp.
    await _finish_pulse(hass)
    assert dt_util.parse_datetime(hass.states.get(LAST_PRESSED_ID).state) == value


async def test_last_pressed_restored_after_restart(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """RestoreSensor brings back the last press time; a new press overrides it."""
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(LAST_PRESSED_ID, RESTORED),
                {
                    "native_value": {
                        "__type": "<class 'datetime.datetime'>",
                        "isoformat": RESTORED,
                    },
                    "native_unit_of_measurement": None,
                },
            ),
        ),
    )
    coordinator = await setup_entry(hass, mock_entry)
    assert hass.states.get(LAST_PRESSED_ID).state == RESTORED

    press(coordinator)
    await hass.async_block_till_done()
    new_value = dt_util.parse_datetime(hass.states.get(LAST_PRESSED_ID).state)
    assert new_value > dt_util.parse_datetime(RESTORED)
    await _finish_pulse(hass)


async def test_signal_strength_disabled_by_default(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """RSSI sensor: diagnostic, disabled by the integration, enable -> reports dBm."""
    await setup_entry(hass, mock_entry)

    reg = entity_registry.async_get(SIGNAL_ID)
    assert reg is not None
    assert reg.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert reg.entity_category is EntityCategory.DIAGNOSTIC
    assert hass.states.get(SIGNAL_ID) is None

    # Enabling it reloads the entry after HA's standard delay.
    entity_registry.async_update_entity(SIGNAL_ID, disabled_by=None)
    await hass.async_block_till_done()
    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1)
    )
    await hass.async_block_till_done()

    state = hass.states.get(SIGNAL_ID)
    assert state is not None
    assert state.state == STATE_UNKNOWN
    assert state.attributes["unit_of_measurement"] == SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    assert state.attributes["device_class"] == "signal_strength"
    assert state.attributes["state_class"] == "measurement"

    coordinator = hass.data[DOMAIN][mock_entry.entry_id]
    press(coordinator, rssi=-42)
    await hass.async_block_till_done()
    assert hass.states.get(SIGNAL_ID).state == "-42"
    await _finish_pulse(hass)
