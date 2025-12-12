# BM83 + Pico 2 W + Nextion

- **Pico 2 W** runs CircuitPython and bridges **Nextion UART** → **BM83 Host UART**.
- Supports tokens: `BT_POWER`, `BT_PAIR`, `BT_PLAY`, `BT_NEXT`, `BT_PREV`, `BT_VOLUP`, `BT_VOLDN`.
- BM83 UART @115200; Nextion @9600 (adjust in `code.py` if needed).

## Wiring (defaults)
- BM83 Host UART: **GP12 (TX) → BM83 RX**, **GP13 (RX) ← BM83 TX**, GND↔GND
- Nextion: **GP8 (TX) → NX RX**, **GP9 (RX) ← NX TX**, GND↔GND
- Optional: **BM83 UART_TX_IND → Pico GP22** (input) for activity debug

## Getting started
1. Flash **CircuitPython** to the Pico 2 W (UF2).
2. Copy `firmware/circuitpython/code.py` to the `CIRCUITPY` drive (rename to `code.py` if needed).
3. Open a serial terminal to the Pico and watch logs.

## Display offset and live time
- The firmware applies a TIME_OFFSET_MS (default 12000 ms) to the on-screen live position (tTIME_CUR) to compensate for display lag.
- You can change TIME_OFFSET_MS in `code.py` near the top of the file.

## Linting / CI
- CI uses flake8. To run locally:
  - flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
  - flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics

## License
This project is provided under the MIT License. See LICENSE for details.
