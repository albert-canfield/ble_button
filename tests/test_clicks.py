"""Single / double / triple / long click detection."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
import pytest

from homeassistant.components import automation, bluetooth
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed_exact,
)

from custom_components.ble_button.const import (
    CONF_CLICK_WINDOW,
    CONF_MODE,
    CONF_PRESS_RESET_DELAY,
    DOMAIN,
    EVENT_BLE_BUTTON_CLICK,
)
from custom_components.ble_button.decoder import decode

from . import CLICK_ID, MAC, get_device, inject_advertisement, setup_entry

HS = 0x5348

# Real capture from the user's button (macOS, 2026-10-15): seconds, payload.
# Pattern pressed: single, double, long (~4 s hold), triple, single.
REAL_CAPTURE = [
    (69.984, "43583359aa38c1a40b1401000034"),
    (70.605, "43583359aa38c1a40b1401000034"),
    (80.770, "43583359aa38c1a40b1401000035"),
    (80.833, "43583359aa38c1a40b1401000035"),
    (81.115, "43583359aa38c1a40b1401000035"),
    (81.967, "43583359aa38c1a40b1401000036"),
    (81.999, "43583359aa38c1a40b1401000036"),
    (94.326, "43583359aa38c1a40b1401000037"),
    (94.874, "43583359aa38c1a40b1401000037"),
    (94.906, "43583359aa38c1a40b1401000037"),
    (95.231, "43583359aa38c1a40b1401000037"),
    (95.530, "43583359aa38c1a40b1401000037"),
    (95.530, "43583359aa38c1a40b1401000037"),
    (95.825, "43583359aa38c1a40b1401000037"),
    (96.115, "43583359aa38c1a40b1401000037"),
    (96.435, "43583359aa38c1a40b1401000037"),
    (96.466, "43583359aa38c1a40b1401000037"),
    (96.983, "43583359aa38c1a40b8401000037"),
    (97.014, "43583359aa38c1a40b8401000037"),
    (97.046, "43583359aa38c1a40b8401000037"),
    (97.269, "43583359aa38c1a40b8401000037"),
    (97.300, "43583359aa38c1a40b8401000037"),
    (97.335, "43583359aa38c1a40b8401000037"),
    (97.603, "43583359aa38c1a40b8401000037"),
    (115.001, "43583359aa38c1a40b1401000038"),
    (115.034, "43583359aa38c1a40b1401000038"),
    (115.331, "43583359aa38c1a40b1401000039"),
    (115.625, "43583359aa38c1a40b140100003a"),
    (115.659, "43583359aa38c1a40b140100003a"),
    (115.887, "43583359aa38c1a40b140100003a"),
    (115.919, "43583359aa38c1a40b140100003a"),
    (116.219, "43583359aa38c1a40b140100003a"),
    (128.521, "43583359aa38c1a40b140100003b"),
    (128.785, "43583359aa38c1a40b140100003b"),
    (128.819, "43583359aa38c1a40b140100003b"),
    (128.852, "43583359aa38c1a40b140100003b"),
    (129.087, "43583359aa38c1a40b140100003b"),
]
EXPECTED_REAL_CLICKS = ["single", "double", "long", "triple", "single"]

STEP = 0.05


@pytest.fixture
def click_events(hass: HomeAssistant) -> list[Event]:
    return async_capture_events(hass, EVENT_BLE_BUTTON_CLICK)


class Clock:
    """Advance frozen time in small steps, firing due timers on the way."""

    def __init__(self, hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
        self.hass = hass
        self.freezer = freezer
        self.now = 0.0

    async def advance_to(self, target: float) -> None:
        while self.now < target:
            step = min(STEP, target - self.now)
            self.freezer.tick(timedelta(seconds=step))
            self.now += step
            async_fire_time_changed_exact(self.hass)
            await self.hass.async_block_till_done()


def hs_payload(counter: int, long_press: bool = False) -> dict[int, bytes]:
    flags = "84" if long_press else "14"
    return {HS: bytes.fromhex(f"43583359aa38c1a40b{flags}010000{counter:02x}")}


async def replay(
    hass: HomeAssistant, clock: Clock, capture: list[tuple[float, str]]
) -> None:
    start = capture[0][0]
    for t, payload in capture:
        await clock.advance_to(t - start)
        inject_advertisement(manufacturer_data={HS: bytes.fromhex(payload)})
        await hass.async_block_till_done()
    await clock.advance_to(clock.now + 15)


def test_decoder_reads_counter_and_long_flag() -> None:
    short = decode({HS: bytes.fromhex("43583359aa38c1a40b1401000037")})
    held = decode({HS: bytes.fromhex("43583359aa38c1a40b8401000037")})
    assert short is not None and held is not None
    assert (short.counter, short.long_press) == (0x37, False)
    assert (held.counter, held.long_press) == (0x37, True)
    assert short.protocol == "hs_counter"


@pytest.mark.parametrize(
    "manufacturer_data",
    [
        {},
        {0x1234: b"\x01\x02"},
        {HS: bytes.fromhex("43583359aa38c1a40b14010000")},  # too short
        {HS: bytes.fromhex("00003359aa38c1a40b1401000037")},  # wrong prefix
    ],
)
def test_decoder_ignores_unknown_formats(manufacturer_data: dict[int, bytes]) -> None:
    assert decode(manufacturer_data) is None


async def test_real_capture_gives_expected_clicks(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """The user's real press pattern, replayed through HA's Bluetooth stack."""
    coordinator = await setup_entry(hass, multi_click_entry)
    assert coordinator._clicks.tracks_activity  # HA 2026.10+ API in use

    await replay(hass, Clock(hass, freezer), REAL_CAPTURE)

    assert [e.data["click_type"] for e in click_events] == EXPECTED_REAL_CLICKS
    assert all(e.data["mac"] == MAC for e in click_events)
    assert coordinator.data.press_count == 8  # counters 0x34..0x3b
    state = hass.states.get(CLICK_ID)
    assert state.attributes["event_type"] == "single"


async def test_real_capture_without_activity_tracking(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HA < 2026.10: the window stretches so a hold isn't a single click."""
    monkeypatch.delattr(bluetooth, "async_register_advertisement_callback")
    coordinator = await setup_entry(hass, multi_click_entry)
    assert not coordinator._clicks.tracks_activity

    await replay(hass, Clock(hass, freezer), REAL_CAPTURE)

    assert [e.data["click_type"] for e in click_events] == EXPECTED_REAL_CLICKS


async def test_single_click_is_reported_after_the_window(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data=hs_payload(1))
    await hass.async_block_till_done()
    await clock.advance_to(1.9)
    assert click_events == []
    await clock.advance_to(2.1)
    assert [e.data["click_type"] for e in click_events] == ["single"]


async def test_held_profile_button_long_press_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """Held: repeats past the window give one long press, not single + long."""
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    t = 0.0
    while t < 2.7:
        await clock.advance_to(t)
        inject_advertisement(manufacturer_data=hs_payload(1))
        await hass.async_block_till_done()
        t += 0.3
    # The button's own long-press flag arrives later; it must not fire again.
    inject_advertisement(manufacturer_data=hs_payload(1, long_press=True))
    await hass.async_block_till_done()
    await clock.advance_to(10)
    assert [e.data["click_type"] for e in click_events] == ["long"]


async def test_generic_held_button_long_press(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """Any brand: still transmitting 2 s after a press is a long press."""
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    t = 0.0
    while t < 3.5:
        await clock.advance_to(t)
        if t >= 2.1:  # reported while still held
            assert [e.data["click_type"] for e in click_events] == ["long"]
        payload = b"\x01" if t < 2.5 else b"\x81"  # unknown format, changes mid-hold
        inject_advertisement(manufacturer_data={0x1234: payload})
        await hass.async_block_till_done()
        t += 0.3
    await clock.advance_to(10)
    assert [e.data["click_type"] for e in click_events] == ["long"]


async def test_real_capture_without_profile(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The generic rules alone classify the user's real presses correctly."""
    monkeypatch.setattr(
        "custom_components.ble_button.coordinator.decode", lambda _data: None
    )
    await setup_entry(hass, multi_click_entry)

    await replay(hass, Clock(hass, freezer), REAL_CAPTURE)

    assert [e.data["click_type"] for e in click_events] == EXPECTED_REAL_CLICKS


async def test_instant_mode_has_no_clicks(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    mock_entry: MockConfigEntry,
    click_events: list[Event],
    press_events: list[Event],
) -> None:
    """Instant mode: every press is reported at once; no click detection."""
    coordinator = await setup_entry(hass, mock_entry)
    assert not coordinator._clicks.tracks_activity
    assert hass.states.get(CLICK_ID) is None

    await replay(hass, Clock(hass, freezer), REAL_CAPTURE)

    assert click_events == []
    # 8 presses; the long-press flag packet is recognised as the same press.
    assert len(press_events) == 8


async def test_counter_jump_counts_missed_presses(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """Press 1 seen, press 2 missed, press 3 seen: still a triple click."""
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data=hs_payload(10))
    await clock.advance_to(0.6)
    inject_advertisement(manufacturer_data=hs_payload(12))
    await clock.advance_to(5)
    assert [e.data["click_type"] for e in click_events] == ["triple"]


async def test_large_counter_jump_is_one_press(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """Button pressed while out of range: the next press is just one press."""
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data=hs_payload(10))
    await clock.advance_to(5)
    inject_advertisement(manufacturer_data=hs_payload(40))
    await clock.advance_to(10)
    assert [e.data["click_type"] for e in click_events] == ["single", "single"]


async def test_counter_wraps_around(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data=hs_payload(0xFF))
    await clock.advance_to(0.5)
    inject_advertisement(manufacturer_data=hs_payload(0x00))
    await clock.advance_to(5)
    assert [e.data["click_type"] for e in click_events] == ["double"]


async def test_cached_advert_seeds_counter_after_reload(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """The replayed cached advert sets the counter but isn't a press."""
    inject_advertisement(manufacturer_data=hs_payload(0x34))
    await hass.async_block_till_done()
    coordinator = await setup_entry(hass, multi_click_entry)
    assert coordinator.data.press_count == 0

    clock = Clock(hass, freezer)
    inject_advertisement(manufacturer_data=hs_payload(0x36))  # 0x35 was missed
    await clock.advance_to(5)
    assert [e.data["click_type"] for e in click_events] == ["double"]


async def test_generic_button_counts_changed_adverts(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    click_events: list[Event],
) -> None:
    """Unknown payload format: every changed advert is one press, no long press."""
    await setup_entry(hass, multi_click_entry)
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data={0x1234: b"\x01"})
    await clock.advance_to(0.5)
    inject_advertisement(manufacturer_data={0x1234: b"\x02"})
    await clock.advance_to(5)
    inject_advertisement(manufacturer_data={0x1234: b"\x03"})
    await clock.advance_to(10)
    assert [e.data["click_type"] for e in click_events] == ["double", "single"]


async def test_click_window_option(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    click_events: list[Event],
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Desk Button",
        unique_id=f"{MAC}_any",
        data={"name": "Desk Button", "mac": MAC, "source": "any"},
        options={
            CONF_MODE: "multi_click",
            CONF_PRESS_RESET_DELAY: 0.6,
            CONF_CLICK_WINDOW: 0.5,
        },
    )
    await setup_entry(hass, entry)
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data={0x1234: b"\x01"})
    await clock.advance_to(0.8)  # past the 0.5 s window
    inject_advertisement(manufacturer_data={0x1234: b"\x02"})
    await clock.advance_to(3)
    assert [e.data["click_type"] for e in click_events] == ["single", "single"]


async def test_double_click_device_trigger(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    multi_click_entry: MockConfigEntry,
    service_calls: list[ServiceCall],
) -> None:
    await setup_entry(hass, multi_click_entry)
    device = get_device(hass, multi_click_entry)
    assert await async_setup_component(
        hass,
        automation.DOMAIN,
        {
            automation.DOMAIN: [
                {
                    "triggers": [
                        {
                            "trigger": "device",
                            "domain": DOMAIN,
                            "device_id": device.id,
                            "type": click_type,
                        }
                    ],
                    "actions": [
                        {"action": "test.automation", "data": {"type": click_type}}
                    ],
                }
                for click_type in ("single", "double", "long")
            ]
        },
    )
    clock = Clock(hass, freezer)

    inject_advertisement(manufacturer_data=hs_payload(1))
    await clock.advance_to(0.4)
    inject_advertisement(manufacturer_data=hs_payload(2))
    await clock.advance_to(5)

    assert [c.data["type"] for c in service_calls] == ["double"]
