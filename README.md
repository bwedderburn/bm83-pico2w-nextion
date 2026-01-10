# BM83-ESP32-S3-Nextion

Bluetooth audio, HID, and a Nextion display driven by an ESP32-S3 running CircuitPython.

## Overview

This project integrates a Microchip BM83 Bluetooth module with an ESP32-S3 and a Nextion HMI display.

The main entrypoint is `firmware/circuitpython/code.py`.

### Module layout

- `bm83.py`: Driver and protocol handling for the Microchip BM83 Bluetooth audio module.
- `nextion.py`: High-level interface for communicating with and updating the Nextion HMI display.
- `ble_hid.py`: Bluetooth LE HID helpers (reports, pairing/connection glue) used for HID functionality.
- `utils.py`: Shared utility functions (parsing, framing, small helpers) used across modules.

## Firmware

See `firmware/` for CircuitPython sources and related assets.
