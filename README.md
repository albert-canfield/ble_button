# BLE Button

A Home Assistant custom integration that turns passive BLE advertisement buttons into Home Assistant binary sensors.

This integration does **not** connect to the BLE device. It listens for Bluetooth Low Energy advertisements and turns a detected advertisement from the configured device into a short binary sensor pulse.

## Features

- Passive BLE advertisement listening
- No pairing required
- No GATT connection required
- Add devices from recent BLE advertisements
- Dynamic Bluetooth adapter/proxy selection
- Works with Home Assistant Bluetooth adapters and BLE proxies
- Text sensor output: `none → press → none`
- Event output: `ble_button_press`
- Payload-independent detection

## Supported devices

Any BLE device that emits advertisements when pressed or activated.

Tested with:

- Aqara BLE Button

## Installation with HACS

1. Open HACS.
2. Go to **Integrations**.
3. Open the three-dot menu.
4. Choose **Custom repositories**.
5. Add this repository URL:

```text
https://github.com/albert-canfield/ble_button
```

6. Category: **Integration**.
7. Install **BLE Button**.
8. Restart Home Assistant.

## Manual installation

Copy:

```text
custom_components/ble_button
```

to:

```text
/config/custom_components/ble_button
```

Then restart Home Assistant.

## Setup

Go to:

```text
Settings → Devices & services → Add integration → BLE Button
```

You can either:

- Add a button from recent BLE advertisements
- Add a button manually by MAC address
- Optionally restrict detection to a specific Bluetooth adapter/proxy

## Entity behaviour

The integration exposes a binary sensor.

```text
off → on → off
```

The sensor turns `on` briefly when the configured BLE advertisement is detected.

## Automation example

```yaml
alias: BLE Button Toggle Light
mode: single

trigger:
  - platform: state
    entity_id: binary_sensor.your_ble_button_press
    to: "on"

action:
  - service: light.toggle
    target:
      entity_id: light.bedroom
```

## Event automation example

The integration also fires:

```text
ble_button_press
```

Example:

```yaml
alias: BLE Button Event Toggle Light
mode: single

trigger:
  - platform: event
    event_type: ble_button_press

action:
  - service: light.toggle
    target:
      entity_id: light.bedroom
```

## Notes

- This integration is advertisement-only.
- It does not pair with the BLE device.
- It does not connect over GATT.
- BLE advertisement payload contents are ignored.
- Detection is based on the configured BLE MAC address and optional Bluetooth source.

## License

MIT
