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

## Hardware
- `hardware/kicad/` reserved for KiCad 9.0 project (BM83+Pico+Nextion carrier).
