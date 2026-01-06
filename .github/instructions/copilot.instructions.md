# GitHub Copilot Instructions for BM83-ESP32-S3-Nextion

## Project Overview
This repository contains firmware and hardware files for a Raspberry Pi Pico 2 W bridge that host-controls a Microchip BM83 Bluetooth audio module over UART. The system parses Nextion HMI tokens and optionally routes audio via an Adafruit UDA1334A I²S DAC with BM83 line-in detect (P3.2) and mute synchronization.

## Technology Stack
- **Language**: Python (100%)
- **Platform**: CircuitPython on Raspberry Pi Pico 2 W
- **Hardware Components**:
  - Microchip BM83 Bluetooth module
  - Nextion HMI display
  - Adafruit UDA1334A I²S DAC
  - Raspberry Pi Pico 2 W

## Code Structure
- `firmware/circuitpython/code.py`: Main firmware implementation
- `.github/workflows/python-package.yml`: CI/CD pipeline with flake8 linting and pytest

## Coding Standards
- **Linting**: Strict flake8 compliance required
  - Error codes checked: E9, F63, F7, F82
  - Max line length: 127 characters
  - Max complexity: 10
- **Python Style**:
  - Use type hints (from `__future__ import annotations`)
  - Follow PEP 8 conventions
  - Use descriptive variable names
  - Include docstrings for functions

## Key Patterns & Conventions
- **Global variables** prefixed with underscore (e.g., `_power_on`, `_is_playing`)
- **Only declare variables as `global` if they are assigned within the function** (not just read)
- **UART communication**: Use `busio.UART` from CircuitPython
- **BM83 protocol**: Frame structure with checksum validation (0xAA header)
- **Nextion commands**: ASCII strings terminated with `\xFF\xFF\xFF`
- **Event handling**: Non-blocking read with timeouts
- **EQ modes**: 0-10 (OFF, SOFT, BASS, TREBLE, CLASSICAL, ROCK, JAZZ, POP, DANCE, RNB, USER)

## Common Operations
- **BM83 Commands**: Use `bm83_send()` with proper opcode and payload
- **Nextion Updates**: Use `nx_send_cmd()` with string commands
- **AVRCP Metadata**: Parse with `_parse_avrcp_metadata_block()`
- **Play/Pause State**: Manage timing with `_current_pos_ms` and `_pos_start_monotonic`

## Testing
- Tests located in `tests/` directory
- CI runs pytest automatically
- All code must pass flake8 validation before merge

## Hardware-Specific Notes
- **GPIO Pins**:
  - BM83 UART: GP12 (TX), GP13 (RX) @ 115200 baud
  - Nextion UART: GP8 (TX), GP9 (RX) @ 9600 baud
- **BM83 Power Control**: MMI press/release sequences (0x51/0x52 for ON, 0x53/0x54 for OFF)
- **Line-in Detection**: P3.2 on BM83 module
- **Audio Routing**: Optional I²S DAC with mute synchronization

## Common Pitfalls to Avoid
1. **Don't declare variables as `global` if only reading them** (causes F824 flake8 errors)
2. **Always include checksum validation** for BM83 frames
3. **Handle UART timeouts gracefully** (non-blocking reads)
4. **Sanitize Nextion text** (remove CR/LF/quotes, limit length)
5. **Track play/pause state carefully** for accurate time display

## When Suggesting Changes
- Ensure flake8 compliance (especially F824 for unused globals)
- Maintain non-blocking event loop structure
- Preserve existing timing and state management logic
- Test UART communication changes thoroughly
- Document hardware-specific behaviors