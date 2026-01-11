# GitHub Copilot Instructions for BM83-ESP32-S3-Nextion

## Project Overview
This repository contains CircuitPython firmware for an **ESP32-S3** board that host-controls a **Microchip BM83 Bluetooth audio module** over UART, integrates a **Nextion HMI display** over UART, and optionally provides **BLE HID ConsumerControl** for volume/mute.

The main entrypoint is:
- `firmware/circuitpython/code.py`

Supporting modules live under:
- `firmware/circuitpython/`

## Technology Stack
- **Language**: Python (CircuitPython style; runs on-device)
- **Platform**: CircuitPython 10.x
- **Hardware/Protocols**:
  - BM83 UART framing + parsing (binary protocol, checksum)
  - Nextion UART token parsing + command sending (`0xFF 0xFF 0xFF` terminator)
  - Optional BLE HID ConsumerControl (volume/mute)
  - Optional I²S DAC integration (e.g., UDA1334A), depending on firmware usage

## Code Structure (authoritative)
**Current implementation**: All code is in a single monolithic file:
- `firmware/circuitpython/code.py`: Contains all functionality including:
  - Main runtime / event loop / orchestration
  - `Bm83` class: BM83 UART framing, parsing, AVRCP helpers, EQ syncing
  - `Nextion` class: Nextion protocol, token parsing, command queue, polling (`sendme`)
  - `BleHid` class: optional BLE HID ConsumerControl helper
  - Utility functions: `_sanitize_text()`, `_fmt_ms()`, `hexdump()`, etc.

**Future modular structure** (referenced by tests but not yet implemented):
- `bm83.py`: BM83 protocol handling
- `nextion.py`: Nextion protocol handling
- `ble_hid.py`: BLE HID functionality
- `utils.py`: shared utility functions

Tests:
- `tests/`: unit tests run in CI (host Python)
- `tests/test_code.py`: tests for monolithic `code.py` (currently working)
- `tests/test_modules.py`: tests for future modular structure (currently failing due to missing modules)

CI:
- `.github/workflows/python-package.yml`: runs **flake8** and **pytest**

## Core Commands (match CI)
### Install (local dev)
```bash
python -m pip install --upgrade pip
python -m pip install flake8 pytest
```

### Linting (CI-compatible)
```bash
# Fail on syntax errors / undefined names
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Style-only pass (warnings)
flake8 . --count --exit-zero --max-complexity=10 --max-line-length=127 --statistics
```

### Testing
```bash
pytest
pytest -v
```

## Coding Standards
- Keep code compatible with CircuitPython constraints:
  - prefer simple control flow and low allocation in hot loops
  - avoid heavy imports or patterns that assume CPython-only modules
- **PEP 8**, max line length **127**
- Prefer small, testable functions (protocol parsing is a great unit-test target)
- Add docstrings for public helpers and for protocol parsing/encoding functions
- Use descriptive names; keep protocol constants centralized and documented

## Key Patterns & Conventions
### Global state
- If you must use global variables in `code.py` (common in CircuitPython), follow this rule:
  - **Only declare `global x` inside a function if that function assigns to `x`.**
  - Reading a global does **not** need a `global` statement.

### UART protocols
- **BM83**
  - treat framing/parsing as a strict binary protocol
  - validate lengths and checksums before acting on frames
  - keep parsing resilient: ignore/skip bad frames rather than crashing
- **Nextion**
  - commands are ASCII and must be terminated with `\xFF\xFF\xFF`
  - sanitize any user/device-provided text before sending to the display
  - parsing should be non-blocking and tolerant of partial tokens

### Runtime/event loop
- Maintain a **non-blocking** main loop:
  - do not add long sleeps or blocking reads
  - handle timeouts and partial UART reads gracefully
  - keep state machines explicit (especially play/pause timing and metadata updates)

## Common Operations (preferred entry points)
- Sending BM83 commands: use the `Bm83.send()` method in `code.py` (don't duplicate framing logic)
- Updating Nextion UI: use the `Nextion` class methods in `code.py` (don't hand-roll terminators everywhere)
- Formatting/sanitizing UI text: use `_sanitize_text()` and `_fmt_ms()` functions in `code.py`
- BLE HID volume/mute: use `BleHid` class methods in `code.py` rather than inlining HID reports

## Common Pitfalls to Avoid
1. Don’t declare `global` for read-only globals (flake8 will complain; also harms clarity).
2. Don’t accept BM83 frames without checksum/length validation.
3. Don’t block the event loop on UART reads; always handle timeouts/partial reads.
4. Don’t send unsanitized strings to Nextion (quotes/CRLF/length can break commands).
5. Don't duplicate protocol constants/encoders—keep them centralized within `code.py`.

## Boundaries / Files to Treat as Read-Only (unless explicitly requested)
- `Documents/` (vendor datasheets, reference PDFs)
- `.github/workflows/` (CI config)
- `LICENSE`
- `SECURITY.md`

## Acceptance Criteria for Changes
- `flake8` passes (strict pass + style pass as in CI)
- `pytest` passes
- Changes preserve protocol correctness and non-blocking behavior
- If behavior changes, update `README.md` and/or inline docs where needed
- New protocol parsing/encoding behavior should include unit tests where feasible

## Examples

### Good: reading a global (no `global` declaration)
```python
def is_powered_on() -> bool:
    """Return the last-known BM83 power state."""
    return _power_on
```

### Good: assigning a global (requires `global`)
```python
def set_power_state(on: bool) -> None:
    """Update the cached BM83 power state."""
    global _power_on
    _power_on = on
```
