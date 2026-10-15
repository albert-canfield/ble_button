"""Device trigger: listed for the device and fires automations on press."""

from __future__ import annotations

from datetime import timedelta

import pytest

from homeassistant.components import automation
from homeassistant.components.device_automation import DeviceAutomationType
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
    async_get_device_automations,
)

from custom_components.ble_button.const import DOMAIN

from . import OTHER_MAC, get_device, make_entry, press, setup_entry


async def test_get_triggers(hass: HomeAssistant, mock_entry: MockConfigEntry) -> None:
    await setup_entry(hass, mock_entry)
    device = get_device(hass, mock_entry)

    triggers = await async_get_device_automations(
        hass, DeviceAutomationType.TRIGGER, device.id
    )
    ours = [t for t in triggers if t["domain"] == DOMAIN]
    assert len(ours) == 1
    assert ours[0]["platform"] == "device"
    assert ours[0]["device_id"] == device.id
    assert ours[0]["type"] == "press"


async def test_device_trigger_fires_automation(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    service_calls: list[ServiceCall],
) -> None:
    """A press of this button runs the automation; other buttons/MACs don't."""
    coordinator = await setup_entry(hass, mock_entry)
    device = get_device(hass, mock_entry)

    other_entry = make_entry(mac=OTHER_MAC, name="Other Button")
    other_coordinator = await setup_entry(hass, other_entry)

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
                            "type": "press",
                        }
                    ],
                    "actions": [
                        {
                            "action": "test.automation",
                            "data_template": {
                                "press_count": "{{ trigger.event.data.press_count }}",
                                "mac": "{{ trigger.event.data.mac }}",
                            },
                        }
                    ],
                }
            ]
        },
    )
    await hass.async_block_till_done()

    def automation_calls() -> list[ServiceCall]:
        return [c for c in service_calls if c.domain == "test"]

    press(coordinator, address=OTHER_MAC)  # wrong MAC for this entry
    press(other_coordinator, address=OTHER_MAC)  # a different button
    await hass.async_block_till_done()
    assert automation_calls() == []

    press(coordinator)
    await hass.async_block_till_done()
    assert len(automation_calls()) == 1
    assert automation_calls()[0].data == {"press_count": 1, "mac": "AA:BB:CC:DD:EE:FF"}

    async_fire_time_changed_exact(hass, dt_util.utcnow() + timedelta(seconds=1))
    await hass.async_block_till_done()


async def test_invalid_trigger_type_rejected(
    hass: HomeAssistant, mock_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    await setup_entry(hass, mock_entry)
    device = get_device(hass, mock_entry)
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
                            "type": "double_press",
                        }
                    ],
                    "actions": [{"action": "test.automation"}],
                }
            ]
        },
    )
    await hass.async_block_till_done()
    assert "value must be one of ['press'] at 'type'" in caplog.text
    state = hass.states.get("automation.unnamed_automation")
    assert state is None or state.state == "unavailable"
