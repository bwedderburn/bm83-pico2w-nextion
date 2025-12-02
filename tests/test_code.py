# Tests for firmware/circuitpython/code.py
#
# These tests verify the pure-Python helper functions in code.py
# that can run without CircuitPython hardware.

from __future__ import annotations

import importlib.util
from pathlib import Path

# Load code.py using importlib to avoid conflict with built-in 'code' module
FIRMWARE_DIR = Path(__file__).parent.parent / "firmware" / "circuitpython"
spec = importlib.util.spec_from_file_location("bt_code", FIRMWARE_DIR / "code.py")
bt_code = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt_code)


# ---------------------------------------------------------------------------
#  hexdump tests
# ---------------------------------------------------------------------------


def test_hexdump_empty():
    """hexdump of empty bytes returns <empty>."""
    assert bt_code.hexdump(b"") == "<empty>"


def test_hexdump_single_byte():
    """hexdump of a single byte."""
    assert bt_code.hexdump(b"\x00") == "00"
    assert bt_code.hexdump(b"\xFF") == "FF"
    assert bt_code.hexdump(b"\x0A") == "0A"


def test_hexdump_multiple_bytes():
    """hexdump of multiple bytes with default width."""
    result = bt_code.hexdump(b"\x01\x02\x03")
    assert result == "01 02 03"


def test_hexdump_with_width():
    """hexdump respects the width parameter."""
    data = bytes(range(5))  # 0x00 to 0x04
    result = bt_code.hexdump(data, width=2)
    # Should split into: "00 01", "02 03", "04"
    assert "00 01" in result
    assert "02 03" in result
    assert "04" in result


# ---------------------------------------------------------------------------
#  bm83_frame tests
# ---------------------------------------------------------------------------


def test_bm83_frame_basic():
    """Basic BM83 frame construction."""
    # Frame format: 0xAA, len_hi, len_lo, opcode, [payload...], checksum
    frame = bt_code.bm83_frame(0x0F)  # READ_BD_ADDR opcode, no payload
    assert frame[0] == 0xAA  # Start byte
    assert frame[1] == 0x00  # len_hi
    assert frame[2] == 0x01  # len_lo (1 byte for opcode)
    assert frame[3] == 0x0F  # opcode
    # Checksum: (~(0x0F) + 1) & 0xFF = 0xF1
    assert frame[4] == 0xF1


def test_bm83_frame_with_payload():
    """BM83 frame with payload."""
    frame = bt_code.bm83_frame(0x02, b"\x01\x00")  # MMI action
    assert frame[0] == 0xAA
    # Length = 1 (opcode) + 2 (payload) = 3
    assert frame[1] == 0x00
    assert frame[2] == 0x03
    assert frame[3] == 0x02  # opcode
    assert frame[4] == 0x01  # payload byte 1
    assert frame[5] == 0x00  # payload byte 2
    # Checksum: (~(0x02 + 0x01 + 0x00) + 1) & 0xFF = (~3 + 1) & 0xFF = 0xFD
    assert frame[6] == 0xFD


def test_bm83_frame_checksum_wrap():
    """BM83 frame checksum with values that wrap."""
    # Use a payload that sums to 0xFF to test wrap behavior
    frame = bt_code.bm83_frame(0xFF, b"")
    # Checksum: (~0xFF + 1) & 0xFF = (0x00 + 1) & 0xFF = 0x01
    assert frame[4] == 0x01


# ---------------------------------------------------------------------------
#  _ascii_upper_uscore tests
# ---------------------------------------------------------------------------


def test_ascii_upper_uscore_valid_tokens():
    """Valid tokens should return True."""
    assert bt_code._ascii_upper_uscore(b"BT_PLAY")
    assert bt_code._ascii_upper_uscore(b"EQ_CLASSICAL")
    assert bt_code._ascii_upper_uscore(b"A1_B2_C3")
    assert bt_code._ascii_upper_uscore(b"TEST")
    assert bt_code._ascii_upper_uscore(b"TEST 123")  # space allowed


def test_ascii_upper_uscore_invalid():
    """Invalid patterns should return False."""
    assert not bt_code._ascii_upper_uscore(b"bt_play")  # lowercase
    assert not bt_code._ascii_upper_uscore(b"BT-PLAY")  # dash not allowed
    assert not bt_code._ascii_upper_uscore(b"BT.PLAY")  # dot not allowed
    assert not bt_code._ascii_upper_uscore(b"")  # empty


def test_ascii_upper_uscore_numbers():
    """Numbers are allowed."""
    assert bt_code._ascii_upper_uscore(b"123")
    assert bt_code._ascii_upper_uscore(b"A1B2C3")


# ---------------------------------------------------------------------------
#  process_nextion_bytes tests
# ---------------------------------------------------------------------------


def test_process_nextion_bytes_clean_token():
    """Test processing a clean token frame."""
    # Reset the buffer
    bt_code._nx_buf.clear()

    # Track which tokens were handled
    handled = []
    original_handle_token = bt_code.handle_token

    def mock_handle_token(msg):
        handled.append(msg)

    bt_code.handle_token = mock_handle_token
    try:
        bt_code.process_nextion_bytes(b"BT_PLAY" + bt_code.TERM)
        assert b"BT_PLAY" in handled
    finally:
        bt_code.handle_token = original_handle_token
        bt_code._nx_buf.clear()


def test_process_nextion_bytes_with_noise():
    """Test that noise bytes are filtered out."""
    bt_code._nx_buf.clear()

    handled = []
    original_handle_token = bt_code.handle_token

    def mock_handle_token(msg):
        handled.append(msg)

    bt_code.handle_token = mock_handle_token
    try:
        # Include noise bytes (0x1A, 0x02) around the token
        bt_code.process_nextion_bytes(bytes([0x1A]) + b"BT_PLAY" + bt_code.TERM + bytes([0x02]))
        assert b"BT_PLAY" in handled
    finally:
        bt_code.handle_token = original_handle_token
        bt_code._nx_buf.clear()


def test_process_nextion_bytes_empty():
    """Empty input should not cause issues."""
    bt_code._nx_buf.clear()
    bt_code.process_nextion_bytes(b"")
    bt_code.process_nextion_bytes(None)  # type: ignore


def test_process_nextion_bytes_partial_frame():
    """Partial frames are buffered until terminator arrives."""
    bt_code._nx_buf.clear()

    handled = []
    original_handle_token = bt_code.handle_token

    def mock_handle_token(msg):
        handled.append(msg)

    bt_code.handle_token = mock_handle_token
    try:
        # Send partial token
        bt_code.process_nextion_bytes(b"BT_")
        assert len(handled) == 0  # not yet handled

        # Complete the frame
        bt_code.process_nextion_bytes(b"PLAY" + bt_code.TERM)
        assert b"BT_PLAY" in handled
    finally:
        bt_code.handle_token = original_handle_token
        bt_code._nx_buf.clear()


def test_process_nextion_bytes_multiple_frames():
    """Multiple frames in one chunk are all processed."""
    bt_code._nx_buf.clear()

    handled = []
    original_handle_token = bt_code.handle_token

    def mock_handle_token(msg):
        handled.append(msg)

    bt_code.handle_token = mock_handle_token
    try:
        bt_code.process_nextion_bytes(
            b"BT_PLAY" + bt_code.TERM + b"BT_NEXT" + bt_code.TERM
        )
        assert b"BT_PLAY" in handled
        assert b"BT_NEXT" in handled
    finally:
        bt_code.handle_token = original_handle_token
        bt_code._nx_buf.clear()


# ---------------------------------------------------------------------------
#  EQ_MAP tests
# ---------------------------------------------------------------------------


def test_eq_map_has_all_presets():
    """EQ_MAP should contain all 11 standard presets."""
    assert len(bt_code.EQ_MAP) == 11
    assert bt_code.EQ_MAP[b"EQ_OFF"] == 0
    assert bt_code.EQ_MAP[b"EQ_USER"] == 10


# ---------------------------------------------------------------------------
#  Constants tests
# ---------------------------------------------------------------------------


def test_tokens_list():
    """TOKENS should contain all BT and EQ tokens."""
    assert b"BT_POWER" in bt_code.TOKENS
    assert b"BT_PLAY" in bt_code.TOKENS
    assert b"BT_VOLUP" in bt_code.TOKENS
    assert b"EQ_BASS" in bt_code.TOKENS
    assert len(bt_code.TOKENS) == len(bt_code.TOK_BT) + len(bt_code.TOK_EQ)


def test_has_hardware_false():
    """When running in test environment, HAS_HARDWARE should be False."""
    assert bt_code.HAS_HARDWARE is False
