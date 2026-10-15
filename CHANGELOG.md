# Changelog

All notable changes to BLE Button. Versions follow [Semantic Versioning](https://semver.org):
**major** for changes that break existing setups (entity IDs, states, removed
options, higher minimum Home Assistant), **minor** for new features, **patch**
for fixes.

## 3.0.0

### ⚠️ Breaking changes

- The press entity is now a **binary sensor** named after the button
  (`binary_sensor.<name>`) instead of the text sensor `sensor.<name>_press`.
  States are `on` / `off`, shown in the UI as **Pressed** / **Not pressed**.
  The old sensor entity is removed automatically. Update automations that used
  `to: "press"` to `to: "on"`, or use the new *Button pressed* device trigger.
- Debug counters are no longer entity attributes; use **Download diagnostics**
  on the device page.

### Added

- **Button mode per button: Instant or Multi-click.** Multi-click reports
  single / double / triple / long press through an event entity
  (`event.<name>`), device triggers and a `ble_button_click` event.
  Detection is brand-independent: presses are counted within a configurable
  window (default 2 s), and a button still transmitting 2 s after a press is a
  long press (HA 2026.10+).
- Button profiles for known payload formats (first: Aqara BLE button, `0x5348`),
  which recover missed presses and use the button's own long-press flag.
- *Button pressed* device trigger in the automation editor.
- **Last pressed** timestamp sensor (restored after restart).
- **Signal strength** diagnostic sensor (disabled by default).
- Diagnostics download with all listener counters.
- `device_id` in the `ble_button_press` event data.
- UI translations for every setup step and option.
- Integration icon and logo (Home Assistant 2026.3+).
- CI: hassfest, HACS validation and tests.

### Fixed

- Reloading the integration, changing options, adding a button (and likely
  restarting Home Assistant) no longer fires a fake press from the cached
  advertisement.
- The options dialog no longer discards the "press visible time".
- Discovery now lists non-connectable (advertisement-only) buttons and devices
  heard only through passive proxies.
- No deprecation warnings on Home Assistant 2026.10 (removed the deprecated
  shared-scanner listener, which only ever saw a subset of the adverts).

### Changed

- Existing buttons stay in instant mode; switching modes swaps the binary
  sensor and the event entity automatically.
- Logging is quiet by default; per-press details are logged at debug level.
- Unrelated nearby BLE traffic no longer causes entity updates (fewer
  recorder writes).

## 2.3.0

- Debug build: text sensor `none → press → none` with listener counters as
  attributes.

## 1.0.0

- Initial public release.
