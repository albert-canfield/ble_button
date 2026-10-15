# BLE Button: Home Assistant custom integration

Passive BLE-advertisement button → `binary_sensor` pulse + `ble_button_press` event + device trigger. Distributed through HACS as a custom repository (`albert-canfield/ble_button`). Domain: `ble_button`.

## Layout

- `custom_components/ble_button/`: the integration (this folder is what HACS installs).
  - `coordinator.py`: listens for adverts, matches MAC/source, debounces, pulses `pressed`, fires events. `BleButtonData` is copied on every publish (`_publish` deep-copies).
  - `entity.py`: base entity + `entity_unique_id(mac, source, key)`. **Never change the unique-ID format**; it would orphan every user's entities.
  - `binary_sensor.py`: the button (`_attr_name = None`, so it's named after the device; `translation_key="press"`).
  - `sensor.py`: Last pressed (timestamp, `RestoreSensor`) and Signal strength (diagnostic, disabled by default).
  - `device_trigger.py`: "Button pressed" → listens to `ble_button_press` filtered by `device_id`.
  - `diagnostics.py`: all debug counters live here, not in entity attributes.
  - `config_flow.py`: user → discover (8 s live scan) / manual → confirm; options flow edits source + press delay.
  - `strings.json` **and** `translations/en.json`: keep them identical. Custom integrations only load `translations/en.json` at runtime; `strings.json` is for hassfest/tooling.
  - `icons.json`: state-based icons (no `_attr_icon` on entities, it would override these).
  - `brand/`: `icon.png` 256², `icon@2x.png` 512², `logo.png`/`logo@2x.png`. Read by HA 2026.3+ and by the HACS validator. Custom integrations can't go into the home-assistant/brands repo any more.
- `tests/`: pytest-homeassistant-custom-component suite.
- `docs/images/`: README hero GIF and stills; `docs/hero/` has the HTML source and render script to regenerate them.
- `.github/workflows/`: hassfest + HACS validation + tests.

## Design decisions to preserve

- **Binary sensor, not text sensor.** The user explicitly wants `on`/`off` states with UI labels Pressed / Not pressed (via translations), so automations use `to: "on"`. Don't reintroduce custom state strings.
- **Two listener paths in the coordinator** (broad callback + address callback with `connectable: False`). The old shared-`BleakScanner` path was removed in 3.0: habluetooth only dispatches bleak callbacks *after* its identical-advert short-circuit and only for connectable adverts, so it saw a strict subset (and it's deprecated). Don't remove the address callback; it's the one that receives non-connectable adverts.
- **Replay guard:** HA synchronously replays the cached advert to a newly registered callback. `_replaying` is set around `async_register_callback` so that replay isn't treated as a press (it would fire automations on every reload/restart). Keep it.
- **HA drops byte-identical consecutive adverts** before change-based callbacks run (`habluetooth/manager.py`, "If the advertisement data is the same"). Buttons with a rolling counter in the payload work; buttons that send an identical payload every press register only the first. `tests/test_bluetooth_stack.py` has a strict xfail documenting this.
- A press arriving while still `on` publishes `off` then `on`, so state triggers fire for every press.
- Don't publish coordinator updates for non-matching MACs (every publish can become a recorder write).
- Logging: nothing above `debug` per advert/press.
- No frequently changing entity attributes; diagnostics go in `diagnostics.py`.

## Commands

```bash
# one-time (phcc needs Python >= 3.14)
python3.14 -m venv .venv && . .venv/bin/activate && pip install -r requirements_test.txt
# run tests
pytest
```

Tests use the real HA Bluetooth stack (phcc `enable_bluetooth`); inject adverts with `habluetooth.get_manager().scanner_adv_received(...)` (see `tests/__init__.py`) to exercise the integration's real callback registrations.

CI (`.github/workflows/`) runs hassfest (`home-assistant/actions/hassfest`), HACS validation (`hacs/action`, category integration) and pytest. All three must pass before a release.

## Releasing

1. Bump `version` in `custom_components/ble_button/manifest.json` and add a `CHANGELOG.md` entry.
2. Merge to `main`, wait for CI to pass.
3. `gh release create vX.Y.Z --title "vX.Y.Z" --notes-file <notes>`. HACS offers users the GitHub **releases**, so the tag must be semver with a `v` prefix.
4. Breaking changes (entity IDs, states, unique IDs) need a major bump and an "Upgrading" note in the README.

`hacs.json` `homeassistant` is the minimum HA version HACS will install on; raise it if code starts using newer core APIs.

## Conventions

- Match the existing style: a path comment on line 1 of each module, `from __future__ import annotations`, HA helpers over hand-rolled code.
- The README is the product page (HACS renders it). Keep the YAML examples in modern syntax (`triggers:` / `trigger:` / `actions:` / `action:`).
- Branch before committing; don't push to `main` or create releases without the user asking.
