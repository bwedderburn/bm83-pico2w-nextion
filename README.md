# BM83-ESP32-S3-Nextion

ESP32-S3 DevKitC-1 + Microchip BM83 + Nextion NX3224F028.

This project is a host/controller for a **BM83** Bluetooth audio module with a **Nextion** UART HMI, plus optional **BLE HID** (volume/mute).

## CircuitPython firmware

CircuitPython sources live in:

- `firmware/circuitpython/`

The main entrypoint is `firmware/circuitpython/code.py`.

### Supported Nextion tokens

The UI sends these tokens (terminated by `0xFF 0xFF 0xFF`):

- `BT_POWER`, `BT_POWEROFF`, `BT_PAIR`
- `BT_PLAY`, `BT_PREV`, `BT_NEXT`
- `BT_VOLUP`, `BT_VOLDN`

### UART settings (defaults)

- Nextion UART: **9600**
- BM83 Host UART: **115200**

### Wiring (ESP32-S3 defaults)

`code.py` defaults:

- Nextion UART: `board.IO15` (TX) and `board.IO16` (RX)
- BM83 UART: `board.IO17` (TX) and `board.IO18` (RX)

Ensure all devices share **GND**.

## BLE HID (optional)

BLE HID is optional and used for **volume up/down** and **mute**.

If BLE libraries are missing at runtime, the firmware should continue without BLE and print a message.

## Development / CI

CI runs lint + unit tests for the CircuitPython modules using CPython:

- `ruff`
- `pytest`

Local commands:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check .
pytest -q
```

## License

MIT License. See `LICENSE`.
