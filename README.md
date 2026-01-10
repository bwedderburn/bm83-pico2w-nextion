# BM83-ESP32-S3-Nextion

Bluetooth audio, HID, and a Nextion display driven by an ESP32-S3 running CircuitPython.

## Overview

This project integrates a Microchip BM83 Bluetooth module with an ESP32-S3 and a Nextion HMI display.

The main entrypoint is `firmware/circuitpython/code.py`.

CircuitPython support modules also live under `firmware/circuitpython/`.

### Module layout

All modules below are located in `firmware/circuitpython/`:

- `bm83.py`: BM83 UART framing + event parsing + AVRCP helpers (play status, notifications, element attributes) and EQ state syncing.
- `nextion.py`: Nextion UART protocol (token parsing, command queue, `sendme` polling) and helper methods to update page objects.
- `ble_hid.py`: Optional BLE HID **ConsumerControl** helper used for volume up/down and mute.
- `utils.py`: Shared helpers such as `sanitize_text()` and `fmt_ms()` used by the runtime and protocol layers.

## Firmware

See `firmware/` for CircuitPython sources and related assets.
