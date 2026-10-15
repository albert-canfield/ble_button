"""Setup, migration, unload, reload and translations."""

from __future__ import annotations

import json
from pathlib import Path

from habluetooth import get_manager

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_UNAVAILABLE, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
    translation,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ble_button.const import DOMAIN

from . import (
    BINARY_ID,
    BUTTON_NAME,
    LAST_PRESSED_ID,
    LAST_PRESSED_UID,
    MAC,
    PRESS_UID,
    PROXY,
    SIGNAL_ID,
    CLICK_ID,
    SIGNAL_UID,
    get_device,
    inject_advertisement,
    make_entry,
    press,
    setup_entry,
)

INTEGRATION_DIR = Path(__file__).parent.parent / "custom_components" / DOMAIN


async def test_setup_creates_entities(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Entry loads in real HA core and creates the expected entities/device."""
    await setup_entry(hass, mock_entry)

    entries = er.async_entries_for_config_entry(entity_registry, mock_entry.entry_id)
    by_id = {e.entity_id: e for e in entries}
    assert set(by_id) == {BINARY_ID, LAST_PRESSED_ID, SIGNAL_ID}

    binary = by_id[BINARY_ID]
    assert binary.domain == Platform.BINARY_SENSOR
    assert binary.platform == DOMAIN
    assert binary.unique_id == PRESS_UID
    assert binary.translation_key == "press"
    assert binary.has_entity_name is True
    assert binary.original_name is None  # named after the device
    assert by_id[LAST_PRESSED_ID].unique_id == LAST_PRESSED_UID
    assert by_id[LAST_PRESSED_ID].translation_key == "last_pressed"
    assert by_id[SIGNAL_ID].unique_id == SIGNAL_UID

    # Exactly one binary_sensor for the entry.
    assert [e for e in entries if e.domain == Platform.BINARY_SENSOR] == [binary]

    state = hass.states.get(BINARY_ID)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["friendly_name"] == BUTTON_NAME
    # The new spec dropped the diagnostic attributes from the entity.
    assert set(state.attributes) == {"friendly_name"}

    device = get_device(hass, mock_entry)
    assert (DOMAIN, mock_entry.entry_id) in device.identifiers
    assert device.name == BUTTON_NAME
    assert (dr.CONNECTION_BLUETOOTH, MAC) in device.connections
    assert binary.device_id == device.id


async def test_migration_removes_old_text_sensor(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The v2 text sensor (same unique_id, sensor domain) is removed on setup."""
    mock_entry.add_to_hass(hass)
    old = entity_registry.async_get_or_create(
        Platform.SENSOR,
        DOMAIN,
        PRESS_UID,
        config_entry=mock_entry,
        suggested_object_id="desk_button_press",
    )
    assert old.entity_id == "sensor.desk_button_press"

    await setup_entry(hass, mock_entry)

    assert entity_registry.async_get(old.entity_id) is None
    assert entity_registry.async_get_entity_id(Platform.SENSOR, DOMAIN, PRESS_UID) is None
    assert (
        entity_registry.async_get_entity_id(Platform.BINARY_SENSOR, DOMAIN, PRESS_UID)
        == BINARY_ID
    )
    # The new sensors survive the migration.
    assert entity_registry.async_get(LAST_PRESSED_ID) is not None
    assert entity_registry.async_get(SIGNAL_ID) is not None
    assert hass.states.get(BINARY_ID).state == STATE_OFF


async def test_migration_keeps_new_sensors_on_reload(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Re-running the migration on reload must not delete the new sensors."""
    def entity_ids() -> set[str]:
        return {
            e.entity_id
            for e in er.async_entries_for_config_entry(
                entity_registry, mock_entry.entry_id
            )
        }

    await setup_entry(hass, mock_entry)
    before = entity_ids()

    assert await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert entity_ids() == before == {BINARY_ID, LAST_PRESSED_ID, SIGNAL_ID}


async def test_migration_with_specific_source(
    hass: HomeAssistant, entity_registry: er.EntityRegistry
) -> None:
    """Source-bound entries use the source in the old unique_id too."""
    entry = make_entry(source=PROXY)
    entry.add_to_hass(hass)
    old_uid = "ble_button_aabbccddeeff_c0ffee000001_press"
    old = entity_registry.async_get_or_create(
        Platform.SENSOR, DOMAIN, old_uid, config_entry=entry
    )

    await setup_entry(hass, entry)

    assert entity_registry.async_get(old.entity_id) is None
    assert (
        entity_registry.async_get_entity_id(Platform.BINARY_SENSOR, DOMAIN, old_uid)
        == BINARY_ID
    )


async def test_unload_removes_listeners(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list
) -> None:
    """Unload is clean: coordinator dropped, BT callbacks gone, entities unavailable."""
    manager = get_manager()
    bleak_callbacks_before = len(manager._bleak_callbacks)
    coordinator = await setup_entry(hass, mock_entry)

    # Leave a pending reset task behind to prove unload cancels it.
    press(coordinator)
    assert hass.states.get(BINARY_ID).state == "on"
    reset_task = coordinator._reset_task
    assert reset_task is not None and not reset_task.done()

    assert await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.NOT_LOADED
    assert mock_entry.entry_id not in hass.data[DOMAIN]
    assert reset_task.cancelled() or reset_task.done()
    assert len(manager._bleak_callbacks) == bleak_callbacks_before
    assert hass.states.get(BINARY_ID).state == STATE_UNAVAILABLE

    # Adverts after unload reach nobody.
    press_events.clear()
    hits_before = coordinator.data.address_callback_hits
    inject_advertisement()
    await hass.async_block_till_done()
    assert press_events == []
    assert coordinator.data.address_callback_hits == hits_before


async def test_reload_does_not_replay_old_advert_as_press(
    hass: HomeAssistant, mock_entry: MockConfigEntry, press_events: list
) -> None:
    """Reloading the entry (e.g. after an options change) must not fake a press.

    HA's bluetooth manager replays the last known advert for an address to a
    newly registered callback (BluetoothCallbackReplay.OLDEST_FIRST default).
    """
    coordinator = await setup_entry(hass, mock_entry)
    inject_advertisement()  # one real press through the real BT stack
    await hass.async_block_till_done()
    assert len(press_events) == 1
    coordinator._reset_task.cancel()

    assert await hass.config_entries.async_reload(mock_entry.entry_id)
    await hass.async_block_till_done()
    new_coordinator = hass.data[DOMAIN][mock_entry.entry_id]
    if new_coordinator._reset_task:
        new_coordinator._reset_task.cancel()

    assert len(press_events) == 1, (
        "reload replayed the cached advert as a new press: "
        f"{[e.data for e in press_events]}"
    )
    assert hass.states.get(BINARY_ID).state == STATE_OFF


def test_translation_file_contents() -> None:
    """translations/en.json carries the state labels and names; matches strings.json."""
    en = json.loads((INTEGRATION_DIR / "translations" / "en.json").read_text())
    strings = json.loads((INTEGRATION_DIR / "strings.json").read_text())
    assert en == strings

    press_states = en["entity"]["binary_sensor"]["press"]["state"]
    assert press_states["on"] == "Pressed"
    assert press_states["off"] == "Not pressed"
    assert en["entity"]["sensor"]["last_pressed"]["name"] == "Last pressed"
    assert en["device_automation"]["trigger_type"]["press"] == "Button pressed"

    icons = json.loads((INTEGRATION_DIR / "icons.json").read_text())
    assert set(icons["entity"]["binary_sensor"]) == {"press"}
    assert set(icons["entity"]["sensor"]) == {"last_pressed"}


async def test_home_assistant_loads_translations(hass: HomeAssistant) -> None:
    """HA's translation loader actually picks up the custom integration's en.json."""
    entity = await translation.async_get_translations(hass, "en", "entity", [DOMAIN])
    prefix = f"component.{DOMAIN}.entity"
    assert entity[f"{prefix}.binary_sensor.press.state.on"] == "Pressed"
    assert entity[f"{prefix}.binary_sensor.press.state.off"] == "Not pressed"
    assert entity[f"{prefix}.sensor.last_pressed.name"] == "Last pressed"

    automation = await translation.async_get_translations(
        hass, "en", "device_automation", [DOMAIN]
    )
    assert (
        automation[f"component.{DOMAIN}.device_automation.trigger_type.press"]
        == "Button pressed"
    )

    config = await translation.async_get_translations(hass, "en", "config", [DOMAIN])
    assert config[f"component.{DOMAIN}.config.error.invalid_mac"].startswith(
        "Invalid button MAC address"
    )


async def test_mode_switch_swaps_entities(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """Options: instant -> multi-click replaces the binary sensor by the event."""
    await setup_entry(hass, mock_entry)
    entity_registry = er.async_get(hass)
    assert entity_registry.async_get(BINARY_ID) is not None

    result = await hass.config_entries.options.async_init(mock_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"mode": "multi_click", "source": "any"}
    )
    await hass.async_block_till_done()
    assert mock_entry.options["mode"] == "multi_click"

    ids = {
        e.entity_id
        for e in er.async_entries_for_config_entry(entity_registry, mock_entry.entry_id)
    }
    assert ids == {CLICK_ID, LAST_PRESSED_ID, SIGNAL_ID}
    assert hass.states.get(BINARY_ID) is None
    assert hass.states.get(CLICK_ID) is not None
