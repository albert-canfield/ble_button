"""Shared fixtures for BLE Button tests.

The real Home Assistant ``bluetooth`` stack is used (phcc's ``enable_bluetooth``
fixture: real BluetoothManager, mocked scanner start and adapters). Adverts are
either fed straight into the coordinator or injected into the real manager, so
the integration's own callback registrations are exercised end to end.
"""

from __future__ import annotations

import pytest

from homeassistant.core import Event, HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from . import make_entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading custom_components/ in every test."""


@pytest.fixture(autouse=True)
async def auto_enable_bluetooth(enable_bluetooth: None) -> None:
    """Bring up HA's real bluetooth integration (scanner/adapters mocked)."""


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """Default config entry: any source, default 0.6 s reset delay."""
    return make_entry()


@pytest.fixture
def multi_click_entry() -> MockConfigEntry:
    """A button in multi-click mode."""
    return make_entry(mode="multi_click")


@pytest.fixture
def press_events(hass: HomeAssistant) -> list[Event]:
    """Capture ble_button_press events."""
    return async_capture_events(hass, "ble_button_press")
