"""Press binary_sensor behaviour: pulse, filtering, de-duplication."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.const import EVENT_STATE_CHANGED, STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed_exact,
)

from custom_components.ble_button.const import (
    DEFAULT_PRESS_RESET_DELAY,
    DUPLICATE_WINDOW_SECONDS,
    SOURCE_ANY,
)

from . import (
    BINARY_ID,
    BUTTON_NAME,
    MAC,
    OTHER_MAC,
    OTHER_PROXY,
    PROXY,
    get_device,
    make_entry,
    press,
    setup_entry,
)


async def advance(hass: HomeAssistant, seconds: float) -> None:
    """Run loop timers due within ``seconds`` (drives the reset asyncio.sleep)."""
    async_fire_time_changed_exact(hass, dt_util.utcnow() + timedelta(seconds=seconds))
    await hass.async_block_till_done()


def binary_transitions(events: list[Event]) -> list[tuple[str | None, str]]:
    return [
        (e.data["old_state"].state if e.data["old_state"] else None, e.data["new_state"].state)
        for e in events
        if e.data["entity_id"] == BINARY_ID
    ]


async def test_press_pulses_on_then_off(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """One advert -> on + press event -> off after the default 0.6 s."""
    coordinator = await setup_entry(hass, mock_entry)
    device = get_device(hass, mock_entry)
    states = async_capture_events(hass, EVENT_STATE_CHANGED)

    press(coordinator, rssi=-47)
    await hass.async_block_till_done()

    assert hass.states.get(BINARY_ID).state == STATE_ON
    assert len(press_events) == 1
    assert press_events[0].data == {
        "device_id": device.id,
        "name": BUTTON_NAME,
        "mac": MAC,
        "accepted_source": SOURCE_ANY,
        "path": "address_callback",
        "source": PROXY,
        "rssi": -47,
        "press_count": 1,
        "press_id": 1,
    }

    # Still on just before the reset delay...
    await advance(hass, DEFAULT_PRESS_RESET_DELAY - 0.2)
    assert hass.states.get(BINARY_ID).state == STATE_ON
    # ...off once it has elapsed.
    await advance(hass, DEFAULT_PRESS_RESET_DELAY + 0.1)
    assert hass.states.get(BINARY_ID).state == STATE_OFF

    assert binary_transitions(states) == [(STATE_OFF, STATE_ON), (STATE_ON, STATE_OFF)]
    assert coordinator.data.press_count == 1
    assert coordinator.data.pressed is False


async def test_custom_reset_delay_real_time(
    hass: HomeAssistant, press_events: list[Event]
) -> None:
    """The reset delay comes from entry options (real wall-clock wait)."""
    coordinator = await setup_entry(hass, make_entry(reset_delay=0.05))
    assert coordinator.press_reset_delay == 0.05

    press(coordinator)
    assert hass.states.get(BINARY_ID).state == STATE_ON
    await asyncio.sleep(0.15)
    await hass.async_block_till_done()
    assert hass.states.get(BINARY_ID).state == STATE_OFF
    assert len(press_events) == 1


async def test_wrong_mac_ignored(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """Adverts from other devices never change state or fire events."""
    coordinator = await setup_entry(hass, mock_entry)
    states = async_capture_events(hass, EVENT_STATE_CHANGED)

    press(coordinator, address=OTHER_MAC)
    await hass.async_block_till_done()

    assert hass.states.get(BINARY_ID).state == STATE_OFF
    assert press_events == []
    assert binary_transitions(states) == []
    assert coordinator.data.ignored_wrong_mac == 1
    assert coordinator.data.press_count == 0


async def test_mac_match_is_case_insensitive(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    coordinator = await setup_entry(hass, mock_entry)
    press(coordinator, address=MAC.lower())
    assert hass.states.get(BINARY_ID).state == STATE_ON
    assert len(press_events) == 1
    await advance(hass, 1)


async def test_wrong_source_ignored(
    hass: HomeAssistant, press_events: list[Event]
) -> None:
    """With a specific source configured, other adapters/proxies are ignored."""
    coordinator = await setup_entry(hass, make_entry(source=PROXY))

    press(coordinator, source=OTHER_PROXY)
    await hass.async_block_till_done()
    assert hass.states.get(BINARY_ID).state == STATE_OFF
    assert press_events == []
    assert coordinator.data.ignored_wrong_source == 1

    # The configured source (any case) is accepted.
    press(coordinator, source=PROXY.lower())
    await hass.async_block_till_done()
    assert hass.states.get(BINARY_ID).state == STATE_ON
    assert len(press_events) == 1
    assert press_events[0].data["accepted_source"] == PROXY
    await advance(hass, 1)


async def test_specific_source_accepts_advert_without_source(
    hass: HomeAssistant, press_events: list[Event]
) -> None:
    """Documented behaviour: a path that exposes no source is accepted on MAC."""
    coordinator = await setup_entry(hass, make_entry(source=PROXY))
    press(coordinator, source="")
    assert hass.states.get(BINARY_ID).state == STATE_ON
    assert len(press_events) == 1
    await advance(hass, 1)


async def test_press_outside_window_retriggers_while_on(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """A second press > 0.15 s later, while still on, is published off -> on."""
    coordinator = await setup_entry(hass, mock_entry)
    states = async_capture_events(hass, EVENT_STATE_CHANGED)

    press(coordinator)
    await asyncio.sleep(DUPLICATE_WINDOW_SECONDS + 0.05)  # real time, < 0.6 s reset
    assert hass.states.get(BINARY_ID).state == STATE_ON
    press(coordinator)
    await hass.async_block_till_done()

    assert hass.states.get(BINARY_ID).state == STATE_ON
    assert [e.data["press_count"] for e in press_events] == [1, 2]
    assert [e.data["press_id"] for e in press_events] == [1, 2]
    assert binary_transitions(states) == [
        (STATE_OFF, STATE_ON),
        (STATE_ON, STATE_OFF),
        (STATE_OFF, STATE_ON),
    ]

    # Only the second press's reset survives; it turns the sensor off once.
    await advance(hass, DEFAULT_PRESS_RESET_DELAY + 0.1)
    assert hass.states.get(BINARY_ID).state == STATE_OFF
    assert binary_transitions(states)[-1] == (STATE_ON, STATE_OFF)
    assert len(binary_transitions(states)) == 4


async def test_press_inside_window_is_duplicate(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list[Event]
) -> None:
    """Two adverts within 0.15 s count as one press."""
    coordinator = await setup_entry(hass, mock_entry)
    states = async_capture_events(hass, EVENT_STATE_CHANGED)

    press(coordinator)
    press(coordinator, source=OTHER_PROXY)  # same burst heard by a 2nd proxy
    await hass.async_block_till_done()

    assert len(press_events) == 1
    assert coordinator.data.ignored_duplicate == 1
    assert coordinator.data.press_count == 1
    assert binary_transitions(states) == [(STATE_OFF, STATE_ON)]
    await advance(hass, 1)
    assert hass.states.get(BINARY_ID).state == STATE_OFF

