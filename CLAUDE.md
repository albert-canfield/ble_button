# BLE Button: Home Assistant custom integration

Passive BLE-advertisement button → Home Assistant triggers, in one of two modes per button (stored in `entry.options["mode"]`, default `instant`):

- **instant**: `binary_sensor.<name>` pulses on every press + `ble_button_press` event + "Button pressed" device trigger. Fastest; the user relies on this being immediate.
- **multi_click**: `event.<name>` with single / double / triple / long + `ble_button_click` event + per-type device triggers.

Distributed through HACS as a custom repository (`albert-canfield/ble_button`). Domain: `ble_button`.

## Layout

- `custom_components/ble_button/`: the integration (this folder is what HACS installs).
  - `coordinator.py`: listens for adverts, matches MAC/source, debounces, pulses `pressed`, fires events. `BleButtonData` is copied on every publish (`_publish` deep-copies).
  - `entity.py`: base entity, `entity_unique_id(mac, source, key)`, `MODE_ENTITIES` (which entities each mode creates; setup removes any others, incl. the v2 text sensor). **Never change the unique-ID format**; it would orphan every user's entities.
  - `binary_sensor.py`: the button in instant mode (`_attr_name = None`, so it's named after the device; `translation_key="press"`).
  - `event.py`: the button in multi-click mode (`_attr_name = None`, `translation_key="click"`, fed by `coordinator.async_add_click_listener`).
  - `clicks.py`: `ClickDetector`, brand-independent click/long-press logic (see below).
  - `decoder.py`: optional **button profiles** for known payload formats (currently `hs_counter`: the Aqara BLE button, manufacturer ID 0x5348; the user's own button).
  - `sensor.py`: Last pressed (timestamp, `RestoreSensor`) and Signal strength (diagnostic, disabled by default).
  - `device_trigger.py`: lists `press` (instant) or `single/double/triple/long` (multi-click) per the device's entry mode; attaches to `ble_button_press` / `ble_button_click` filtered by `device_id` (+ `click_type`).
  - `diagnostics.py`: all debug counters live here, not in entity attributes.
  - `config_flow.py`: user → discover (8 s live scan) / manual → confirm; options flow edits mode, source, press delay, click window.
  - `strings.json` **and** `translations/en.json`: keep them identical. Custom integrations only load `translations/en.json` at runtime; `strings.json` is for hassfest/tooling.
  - `icons.json`: state-based icons (no `_attr_icon` on entities, it would override these).
  - `brand/`: `icon.png` 256², `icon@2x.png` 512², `logo.png`/`logo@2x.png`. Read by HA 2026.3+ and by the HACS validator. Custom integrations can't go into the home-assistant/brands repo any more.
- `tests/`: pytest-homeassistant-custom-component suite.
- `docs/images/`: README hero GIF and stills; `docs/hero/` has the HTML source and render script to regenerate them.
- `.github/workflows/`: hassfest + HACS validation + tests.

## Design decisions to preserve

- **Generic first, profiles second.** The integration must work with any brand of BLE button; the user explicitly doesn't want it tied to one firmware. All core behaviour (press = changed advert; clicks counted within the window; long press = still transmitting `LONG_PRESS_TIME` after a press) lives in `coordinator.py`/`clicks.py` and needs no payload knowledge. Payload-specific knowledge only goes in `decoder.py` as an optional profile that *improves* accuracy (exact press counter, native long-press flag). `tests/test_clicks.py::test_real_capture_without_profile` proves the generic path handles the user's real button; keep it passing.
- **Long press needs every advert** (incl. identical repeats): `bluetooth.async_register_advertisement_callback` (HA 2026.10+), registered only in multi-click mode via `getattr` so older HA still loads. Without it, generic long press is unavailable and profiled buttons get `LONG_PRESS_FALLBACK_WINDOW`.
- The click window only waits longer than configured when the button is actually repeating and the long-press check hasn't run yet (`ClickDetector._async_window_closed`).
- `tests/test_clicks.py::REAL_CAPTURE` is a real capture of the user's button (single, double, ~4 s hold, triple, single). Use it as the regression fixture for any timing change.
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

## Versioning and releasing

Semantic Versioning, starting from **v3.0.0** (the first properly managed release; the manifest had already reached 2.3.0, so never go below 3.x):

| Change | Bump |
|---|---|
| Breaks existing setups: entity IDs/states/unique IDs, removed options, higher min HA | major |
| New feature: button profile, option, entity, trigger | minor |
| Bug fix only | patch |
| Needs real-hardware testing first | pre-release `vX.Y.Z-beta.N` (manifest `X.Y.Z-beta.N`, `gh release create --prerelease`) |

1. Bump `version` in `custom_components/ble_button/manifest.json` and add a `## X.Y.Z` entry to `CHANGELOG.md` (CI's *Version* job fails without it).
2. PR → merge to `main` once CI is green.
3. `gh release create vX.Y.Z --target main --title "vX.Y.Z: <headline>" --notes-file <notes>`. HACS offers users the GitHub **releases**; the tag must be exactly `v` + manifest version.
4. `.github/workflows/release.yml` then checks tag == manifest version and attaches `ble_button.zip` (manual install).
5. Major bumps need an "Upgrading" note in the README.

`hacs.json` `homeassistant` is the minimum HA version HACS will install on; raise it if code starts using newer core APIs.

## Conventions

- Match the existing style: a path comment on line 1 of each module, `from __future__ import annotations`, HA helpers over hand-rolled code.
- The README is the product page (HACS renders it). Keep the YAML examples in modern syntax (`triggers:` / `trigger:` / `actions:` / `action:`).
- Branch before committing; don't push to `main` or create releases without the user asking.
