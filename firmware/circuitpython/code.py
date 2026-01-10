# Project: BM83-ESP32-S3-Nextion
"""
CircuitPython firmware for ESP32-S3 controlling BM83 Bluetooth module and Nextion display.
Bridges Nextion HMI commands to BM83 UART and displays AVRCP metadata.
"""
from __future__ import annotations

import time
from collections import deque

# Try importing CircuitPython-specific modules
HAS_HARDWARE = False
try:
    import board
    import busio
    HAS_HARDWARE = True
except ImportError:
    pass

# Optional BLE HID support
HAS_BLE = False
try:
    import adafruit_ble
    from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
    from adafruit_ble.services.standard.hid import HIDService
    from adafruit_hid.consumer_control import ConsumerControl
    from adafruit_hid.consumer_control_code import ConsumerControlCode
    HAS_BLE = True
except ImportError:
    pass

# =============================================================================
# Constants
# =============================================================================

# Time offset for display sync (ms)
TIME_OFFSET_MS = 12000

# BM83 UART settings
BM83_BAUD = 115200

# Nextion UART settings
NEXTION_BAUD = 9600

# Nextion terminator
TERM = b"\xFF\xFF\xFF"

# BM83 opcodes
OP_MMI_CMD = 0x02
OP_MUSIC_CONTROL = 0x04
OP_CHANGE_DEVICE_NAME = 0x05
OP_CHANGE_PIN_CODE = 0x06
OP_BTM_PARAMETER_SETTING = 0x07
OP_READ_BTM_VERSION = 0x08
OP_GET_PB_BY_AT_CMD = 0x09
OP_VENDOR_AT_COMMAND = 0x0A
OP_AVRCP_SPECIFIC_CMD = 0x0B
OP_AVRCP_GROUP_NAVIGATION = 0x0C
OP_READ_LINK_STATUS = 0x0D
OP_READ_PAIRED_DEV_RECORD = 0x0E
OP_READ_LOCAL_BD_ADDR = 0x0F
OP_READ_LOCAL_DEV_NAME = 0x10
OP_SET_ACCESS_PB_METHOD = 0x11
OP_SEND_SPP_DATA = 0x12
OP_BTM_UTILITY = 0x13
OP_EVENT_ACK = 0x14
OP_ADDITIONAL_PROFILES_LINK_SETUP = 0x15
OP_READ_LINKED_DEV_INFO = 0x16
OP_PROFILES_LINK_BACK = 0x17
OP_DISCONNECT = 0x18
OP_MCU_STATUS_INDICATION = 0x19
OP_USER_CONFIRM_SPP_REQ_REPLY = 0x1A
OP_SET_HF_GAIN_LEVEL = 0x1B
OP_EQ_MODE_SETTING = 0x1C
OP_DSP_NR_CTRL = 0x1D
OP_GPIO_CTRL = 0x1E
OP_MCU_UART_RX_BUFFER_SIZE = 0x1F
OP_VOICE_PROMPT_CMD = 0x20
OP_SET_OVERALL_GAIN = 0x23
OP_READ_BTM_LINK_MODE = 0x24
OP_CONFIGURE_VENDOR_PARAM = 0x25
OP_READ_VENDOR_EEPROM = 0x26
OP_READ_IC_VERSION_INFO = 0x29
OP_MSPK_VENDOR_CMD = 0x2A
OP_READ_BTM_SETTING = 0x2B
OP_READ_FEATURE_LIST = 0x2C
OP_PERSONAL_MSPK_GROUP_CTRL = 0x2D
OP_MSPK_EXCHANGE_LINK_INFO = 0x2E
OP_MSPK_SET_GIAC = 0x2F

# BM83 events
EVT_CMD_ACK = 0x00
EVT_BTM_STATUS = 0x01
EVT_CALL_STATUS = 0x02
EVT_CALLER_ID = 0x03
EVT_SMS_IND = 0x04
EVT_MISSED_CALL_IND = 0x05
EVT_PHONEBOOK_INFO = 0x06
EVT_BTM_UTILITY_REQ = 0x07
EVT_VENDOR_AT_CMD_RSP = 0x08
EVT_SPP_DATA = 0x0A
EVT_REPORT_LINK_STATUS = 0x0B
EVT_REPORT_PAIRED_RECORD = 0x0C
EVT_REPORT_HFP_VOLUME = 0x0D
EVT_REPORT_A2DP_VOLUME = 0x0E
EVT_REPORT_INPUT_SIGNAL_LEVEL = 0x0F
EVT_REPORT_IAPAUDIO_STATUS = 0x10
EVT_REPORT_IAPEA_STATUS = 0x11
EVT_AVRCP_SPEC_RSP = 0x12
EVT_AVRCP_IND = 0x13
EVT_READ_LINKED_DEV_INFO_RSP = 0x14
EVT_READ_BTM_VERSION_RSP = 0x15
EVT_CALL_LIST_REPORT = 0x16
EVT_AVRCP_VOLUME_CTRL = 0x17
EVT_REPORT_TYPE_CODEC = 0x18
EVT_REPORT_TYPE_BTM_SETTING = 0x1A
EVT_REPORT_MCU_UART_VERSION = 0x1B
EVT_REPORT_BTM_INITIAL_DONE = 0x1C
EVT_REPORT_MAP_DATA = 0x1D
EVT_SECURITY_REQ = 0x1E
EVT_REPORT_DEVICE_NAME = 0x1F
EVT_REPORT_AV_STATUS = 0x20
EVT_USER_CONFIRM_SSP_REQ = 0x22
EVT_REPORT_AVRCP_VOL_CTRL_STATUS = 0x23
EVT_REPORT_INPUT_SOURCE = 0x24
EVT_REPORT_LINK_BACK_STATUS = 0x25
EVT_REPORT_IC_VERSION_INFO = 0x2A
EVT_REPORT_CUSTOMER_GATT_ATTRIBUTE_DATA = 0x2B
EVT_MSPK_VENDOR_EVENT = 0x2C
EVT_REPORT_FEATURE_LIST = 0x2D
EVT_EQ_MODE_IND = 0x34

# MMI actions
MMI_POWER_ON_BUTTON_PRESS = 0x51
MMI_POWER_ON_BUTTON_RELEASE = 0x52
MMI_POWER_OFF_BUTTON_PRESS = 0x53
MMI_POWER_OFF_BUTTON_RELEASE = 0x54
MMI_ACCEPT_CALL = 0x04
MMI_END_CALL = 0x05
MMI_VOICE_DIAL = 0x06
MMI_LAST_NUM_REDIAL = 0x07
MMI_TOGGLE_MIC_MUTE = 0x09
MMI_PAIR_MODE = 0x5D

# Music control actions
MC_PLAY_PAUSE = 0x00
MC_STOP = 0x01
MC_NEXT = 0x02
MC_PREVIOUS = 0x03
MC_FAST_FORWARD_PRESS = 0x04
MC_FAST_FORWARD_RELEASE = 0x05
MC_REWIND_PRESS = 0x06
MC_REWIND_RELEASE = 0x07

# AVRCP commands
AVRCP_PLAY = 0x00
AVRCP_PAUSE = 0x01
AVRCP_NEXT = 0x02
AVRCP_PREV = 0x03
AVRCP_FF = 0x04
AVRCP_REW = 0x05

# EQ modes (0-10)
EQ_OFF = 0
EQ_SOFT = 1
EQ_BASS = 2
EQ_TREBLE = 3
EQ_CLASSICAL = 4
EQ_ROCK = 5
EQ_JAZZ = 6
EQ_POP = 7
EQ_DANCE = 8
EQ_RNB = 9
EQ_USER = 10

# EQ labels
EQ_LABELS = [
    "OFF",
    "SOFT",
    "BASS",
    "TREBLE",
    "CLASSICAL",
    "ROCK",
    "JAZZ",
    "POP",
    "DANCE",
    "R&B",
    "USER"
]

# EQ sequence for cycling
EQ_SEQ = [EQ_OFF, EQ_SOFT, EQ_BASS, EQ_TREBLE, EQ_CLASSICAL, EQ_ROCK, EQ_JAZZ, EQ_POP, EQ_DANCE, EQ_RNB, EQ_USER]

# EQ map (token -> mode)
EQ_MAP = {
    b"EQ_OFF": EQ_OFF,
    b"EQ_SOFT": EQ_SOFT,
    b"EQ_BASS": EQ_BASS,
    b"EQ_TREBLE": EQ_TREBLE,
    b"EQ_CLASSICAL": EQ_CLASSICAL,
    b"EQ_ROCK": EQ_ROCK,
    b"EQ_JAZZ": EQ_JAZZ,
    b"EQ_POP": EQ_POP,
    b"EQ_DANCE": EQ_DANCE,
    b"EQ_RNB": EQ_RNB,
    b"EQ_USER": EQ_USER,
}

# Button tokens
TOK_BT = [
    b"BT_POWER",
    b"BT_PAIR",
    b"BT_PLAY",
    b"BT_NEXT",
    b"BT_PREV",
    b"BT_VOLUP",
    b"BT_VOLDN",
]

TOK_EQ = list(EQ_MAP.keys())
TOKENS = TOK_BT + TOK_EQ

# =============================================================================
# Global State
# =============================================================================

_power_on = False
_is_playing = False
_is_connected = False
_current_pos_ms = 0
_total_duration_ms = 0
_pos_start_monotonic = 0
_track_title = ""
_track_artist = ""
_track_album = ""
_eq_mode = EQ_OFF
_eq_index = 0
_last_eq_time = 0
_last_next_token_time = 0

# Nextion TX queue (use deque for efficient FIFO)
_nx_queue = deque((), 50)  # max 50 commands queued

# Nextion RX buffer
_nx_buf = bytearray()

# BM83 RX buffer
_bm_buf = bytearray()

# =============================================================================
# Utility Functions
# =============================================================================


def hexdump(data: bytes, width: int = 16) -> str:
    """Format bytes as hex string with optional line width."""
    if not data:
        return "<empty>"
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i:i+width]
        hex_str = " ".join(f"{b:02X}" for b in chunk)
        lines.append(hex_str)
    return "\n".join(lines) if len(lines) > 1 else lines[0]


def _sanitize_text(text: str, max_len: int = 100) -> str:
    """Remove problematic characters from text for Nextion display."""
    # Remove CR, LF, quotes, and limit length
    text = text.replace("\r", " ").replace("\n", " ")
    text = text.replace('"', "'").replace("\\", "/")
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def _fmt_ms(ms: int) -> str:
    """Format milliseconds as MM:SS."""
    if ms < 0:
        ms = 0
    total_sec = ms // 1000
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes:02d}:{seconds:02d}"


def _ascii_upper_uscore(data: bytes) -> bool:
    """Check if bytes contain only uppercase ASCII, digits, underscore, and space."""
    if not data:
        return False
    for b in data:
        if not ((65 <= b <= 90) or (48 <= b <= 57) or b == 95 or b == 32):  # A-Z, 0-9, _, space
            return False
    return True


# =============================================================================
# BM83 Protocol Layer
# =============================================================================


def bm83_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build a BM83 command frame with checksum."""
    length = len(payload) + 1  # opcode counts toward length
    len_hi = (length >> 8) & 0xFF
    len_lo = length & 0xFF

    # Checksum: two's complement of sum of (opcode + payload bytes)
    checksum_sum = opcode
    for b in payload:
        checksum_sum += b
    checksum = (~checksum_sum + 1) & 0xFF

    frame = bytes([0xAA, len_hi, len_lo, opcode]) + payload + bytes([checksum])
    return frame


def bm83_send(opcode: int, payload: bytes = b"") -> None:
    """Send a command to BM83."""
    if not HAS_HARDWARE:
        return
    frame = bm83_frame(opcode, payload)
    uart_bm.write(frame)
    print(f"BM83 TX: {hexdump(frame)}")


def bm83_checksum_valid(data: bytes) -> bool:
    """Verify BM83 frame checksum (excludes 0xAA, len_hi, len_lo)."""
    if len(data) < 2:
        return False
    # Sum all bytes except checksum, then add checksum should equal 0 (mod 256)
    total = sum(data) & 0xFF
    return total == 0


def parse_bm83_frame(buf: bytearray) -> tuple[int, bytes] | None:
    """
    Parse a BM83 frame from buffer.
    Returns (event_code, payload) or None if incomplete/invalid.
    Removes parsed frame from buffer.
    """
    while len(buf) > 0 and buf[0] != 0xAA:
        buf.pop(0)  # Discard junk before frame start

    if len(buf) < 4:
        return None  # Need at least: AA len_hi len_lo event

    len_hi = buf[1]
    len_lo = buf[2]
    length = (len_hi << 8) | len_lo

    frame_len = 4 + length  # AA + len_hi + len_lo + event + params + checksum
    if len(buf) < frame_len:
        return None  # Incomplete frame

    # Extract frame
    frame = buf[:frame_len]

    # Verify checksum (skip AA, len_hi, len_lo)
    checksum_data = frame[3:]
    if not bm83_checksum_valid(checksum_data):
        print(f"BM83 RX: Invalid checksum - {hexdump(frame)}")
        buf[:frame_len] = []  # Discard bad frame
        return None

    event_code = frame[3]
    payload = frame[4:frame_len-1] if length > 1 else b""

    # Remove parsed frame from buffer
    buf[:frame_len] = []

    return (event_code, payload)


def _parse_avrcp_metadata_block(data: bytes) -> dict[str, str]:
    """Parse AVRCP metadata from EVT_AVRCP_IND event."""
    metadata = {}
    pos = 0

    while pos < len(data):
        if pos + 3 > len(data):
            break

        attr_id = data[pos]
        len_hi = data[pos + 1]
        len_lo = data[pos + 2]
        text_len = (len_hi << 8) | len_lo
        pos += 3

        if pos + text_len > len(data):
            break

        text = data[pos:pos+text_len].decode("utf-8", errors="replace")
        pos += text_len

        # Attribute IDs: 1=Title, 2=Artist, 3=Album, 4=Track, 5=Total, 6=Genre, 7=Duration
        if attr_id == 1:
            metadata["title"] = text
        elif attr_id == 2:
            metadata["artist"] = text
        elif attr_id == 3:
            metadata["album"] = text
        elif attr_id == 7:
            # Duration in ms
            try:
                metadata["duration"] = int(text)
            except ValueError:
                pass

    return metadata


# =============================================================================
# Nextion Protocol Layer
# =============================================================================


def nx_send_cmd(cmd: str) -> None:
    """Queue a command to send to Nextion display."""
    _nx_queue.append(cmd)


def nx_flush_queue() -> None:
    """Send queued commands to Nextion (call in main loop)."""
    if not HAS_HARDWARE:
        return

    while _nx_queue:
        cmd = _nx_queue.popleft()
        frame = cmd.encode("ascii") + TERM
        uart_nx.write(frame)
        print(f"NX TX: {cmd}")


def process_nextion_bytes(data: bytes) -> None:
    """Process incoming Nextion bytes, extract valid tokens."""
    if not data:
        return

    _nx_buf.extend(data)

    # Look for terminator
    while True:
        try:
            idx = _nx_buf.index(0xFF)
        except ValueError:
            break

        # Check if we have all three terminator bytes
        if idx + 2 >= len(_nx_buf):
            break

        if _nx_buf[idx:idx+3] == TERM:
            # Extract everything before terminator
            raw_token = _nx_buf[:idx]

            # Remove processed bytes including terminator
            _nx_buf[:idx+3] = []

            # Filter out non-token bytes from the beginning
            # Find the start of a valid token (A-Z, 0-9, _)
            token_start = 0
            for i, b in enumerate(raw_token):
                if (65 <= b <= 90) or (48 <= b <= 57) or b == 95:  # A-Z, 0-9, _
                    token_start = i
                    break

            token_candidate = raw_token[token_start:]

            # Validate and handle if it's a valid token
            if _ascii_upper_uscore(token_candidate):
                handle_token(bytes(token_candidate))
        else:
            # False alarm, skip this 0xFF
            _nx_buf.pop(0)


def handle_token(token: bytes) -> None:
    """Handle a validated token from Nextion."""
    global _last_next_token_time

    print(f"NX RX: {token.decode('ascii')}")

    # Power control
    if token == b"BT_POWER":
        if _power_on:
            bm83_send(OP_MMI_CMD, bytes([MMI_POWER_OFF_BUTTON_PRESS, 0x00]))
            time.sleep(0.1)
            bm83_send(OP_MMI_CMD, bytes([MMI_POWER_OFF_BUTTON_RELEASE, 0x00]))
        else:
            bm83_send(OP_MMI_CMD, bytes([MMI_POWER_ON_BUTTON_PRESS, 0x00]))
            time.sleep(0.1)
            bm83_send(OP_MMI_CMD, bytes([MMI_POWER_ON_BUTTON_RELEASE, 0x00]))
        return

    # Pairing
    if token == b"BT_PAIR":
        bm83_send(OP_MMI_CMD, bytes([MMI_PAIR_MODE, 0x00]))
        return

    # Playback control
    if token == b"BT_PLAY":
        bm83_send(OP_MUSIC_CONTROL, bytes([MC_PLAY_PAUSE]))
        return

    # Next track - with debouncing
    if token == b"BT_NEXT":
        now = time.monotonic()
        if now - _last_next_token_time < 0.3:  # 300ms debounce
            print("  (debounced)")
            return
        _last_next_token_time = now

        next_eq()
        return

    if token == b"BT_PREV":
        bm83_send(OP_MUSIC_CONTROL, bytes([MC_PREVIOUS]))
        return

    # Volume control
    if token == b"BT_VOLUP":
        if HAS_BLE and ble_hid:
            ble_hid.send(ConsumerControlCode.VOLUME_INCREMENT)
        return

    if token == b"BT_VOLDN":
        if HAS_BLE and ble_hid:
            ble_hid.send(ConsumerControlCode.VOLUME_DECREMENT)
        return

    # Direct EQ selection
    if token in EQ_MAP:
        mode = EQ_MAP[token]
        set_eq(mode)
        return


# =============================================================================
# EQ State Machine
# =============================================================================


def set_eq(mode: int) -> None:
    """Set BM83 EQ mode and update display."""
    global _eq_mode, _eq_index, _last_eq_time

    # Throttle rapid EQ changes
    now = time.monotonic()
    if now - _last_eq_time < 0.5:  # 500ms minimum between changes
        print("  EQ change throttled")
        return
    _last_eq_time = now

    if mode < 0 or mode > 10:
        print(f"  Invalid EQ mode: {mode}")
        return

    _eq_mode = mode

    # Update index to match mode
    try:
        _eq_index = EQ_SEQ.index(mode)
    except ValueError:
        _eq_index = 0

    # Send to BM83
    bm83_send(OP_EQ_MODE_SETTING, bytes([mode]))

    # Update display
    label = EQ_LABELS[mode]
    nx_send_cmd(f'tEQ.txt="{label}"')
    print(f"  EQ set to: {label} (mode={mode}, index={_eq_index})")


def next_eq() -> None:
    """Cycle to next EQ preset."""
    global _eq_index

    _eq_index = (_eq_index + 1) % len(EQ_SEQ)
    mode = EQ_SEQ[_eq_index]
    set_eq(mode)


def sync_eq_from_bm83(mode: int) -> None:
    """Initialize EQ state from BM83's reported mode."""
    global _eq_mode, _eq_index

    if mode < 0 or mode > 10:
        return

    _eq_mode = mode

    # Map mode to index in EQ_SEQ
    try:
        _eq_index = EQ_SEQ.index(mode)
    except ValueError:
        _eq_index = 0

    # Update display
    label = EQ_LABELS[mode]
    nx_send_cmd(f'tEQ.txt="{label}"')
    print(f"  EQ synced from BM83: {label} (mode={mode}, index={_eq_index})")


# =============================================================================
# BM83 Event Handlers
# =============================================================================


def handle_bm83_event(event: int, payload: bytes) -> None:
    """Process a BM83 event."""
    global _power_on, _is_connected, _is_playing
    global _track_title, _track_artist, _track_album
    global _current_pos_ms, _total_duration_ms, _pos_start_monotonic

    if event == EVT_BTM_STATUS:
        if len(payload) >= 1:
            status = payload[0]
            print(f"  BTM Status: 0x{status:02X}")

            # Status values (examples):
            # 0x00 = Power OFF
            # 0x01 = Pairing state
            # 0x02 = Power ON
            # 0x03 = Pairing successful
            # 0x05 = Connecting
            # 0x06 = Connected / idle
            # 0x09 = A2DP streaming

            if status == 0x00:
                _power_on = False
                _is_connected = False
                nx_send_cmd('tSTATUS.txt="OFF"')
            elif status in (0x01, 0x02):
                _power_on = True
                _is_connected = False
                nx_send_cmd('tSTATUS.txt="PAIRING"')
            elif status in (0x06, 0x09):
                _power_on = True
                _is_connected = True
                _is_playing = (status == 0x09)
                nx_send_cmd('tSTATUS.txt="CONNECTED"')

    elif event == EVT_AVRCP_IND:
        # AVRCP metadata or playback status
        if len(payload) >= 1:
            sub_event = payload[0]

            # 0x00 = Media info (metadata)
            if sub_event == 0x00 and len(payload) > 1:
                metadata = _parse_avrcp_metadata_block(payload[1:])

                if "title" in metadata:
                    _track_title = _sanitize_text(metadata["title"])
                    nx_send_cmd(f'tTITLE.txt="{_track_title}"')

                if "artist" in metadata:
                    _track_artist = _sanitize_text(metadata["artist"])
                    nx_send_cmd(f'tARTIST.txt="{_track_artist}"')

                if "album" in metadata:
                    _track_album = _sanitize_text(metadata["album"])
                    nx_send_cmd(f'tALBUM.txt="{_track_album}"')

                if "duration" in metadata:
                    _total_duration_ms = metadata["duration"]
                    nx_send_cmd(f'tTIME_TOT.txt="{_fmt_ms(_total_duration_ms)}"')

                print(f"  Metadata: {metadata}")

            # 0x01 = Play status changed
            elif sub_event == 0x01 and len(payload) >= 10:
                # Bytes: [01] [play_status] [pos_ms:4] [duration_ms:4]
                play_status = payload[1]
                pos_ms = int.from_bytes(payload[2:6], "big")
                duration_ms = int.from_bytes(payload[6:10], "big")

                _is_playing = (play_status == 0x01)
                _current_pos_ms = pos_ms
                _total_duration_ms = duration_ms
                _pos_start_monotonic = time.monotonic()

                nx_send_cmd(f'tTIME_CUR.txt="{_fmt_ms(_current_pos_ms + TIME_OFFSET_MS)}"')
                nx_send_cmd(f'tTIME_TOT.txt="{_fmt_ms(_total_duration_ms)}"')

                status_text = "PLAYING" if _is_playing else "PAUSED"
                nx_send_cmd(f'tSTATUS.txt="{status_text}"')

                print(f"  Play status: {status_text}, pos={_fmt_ms(pos_ms)}, dur={_fmt_ms(duration_ms)}")

    elif event == EVT_EQ_MODE_IND:
        # EQ mode indication from BM83
        if len(payload) >= 1:
            mode = payload[0]
            sync_eq_from_bm83(mode)

    elif event == EVT_CMD_ACK:
        if len(payload) >= 2:
            ack_opcode = payload[0]
            ack_status = payload[1]
            print(f"  ACK: op=0x{ack_opcode:02X} status=0x{ack_status:02X}")

    else:
        print(f"  Unhandled event 0x{event:02X}: {hexdump(payload)}")


# =============================================================================
# Main Loop
# =============================================================================


def update_display_time() -> None:
    """Update current playback time on display."""
    if not _is_playing:
        return

    elapsed = time.monotonic() - _pos_start_monotonic
    estimated_pos = _current_pos_ms + int(elapsed * 1000) + TIME_OFFSET_MS

    if estimated_pos > _total_duration_ms and _total_duration_ms > 0:
        estimated_pos = _total_duration_ms

    nx_send_cmd(f'tTIME_CUR.txt="{_fmt_ms(estimated_pos)}"')


def main_loop() -> None:
    """Main event loop - read UART, process events, update display."""
    last_display_update = time.monotonic()

    while True:
        # Read from BM83
        if uart_bm.in_waiting:
            chunk = uart_bm.read(uart_bm.in_waiting)
            if chunk:
                _bm_buf.extend(chunk)

                # Try parsing frames
                while True:
                    result = parse_bm83_frame(_bm_buf)
                    if result is None:
                        break
                    event, payload = result
                    print(f"BM83 RX: Event 0x{event:02X}")
                    handle_bm83_event(event, payload)

        # Read from Nextion
        if uart_nx.in_waiting:
            chunk = uart_nx.read(uart_nx.in_waiting)
            if chunk:
                process_nextion_bytes(chunk)

        # Flush Nextion TX queue
        nx_flush_queue()

        # Update display time periodically (every 1 second)
        now = time.monotonic()
        if now - last_display_update >= 1.0:
            update_display_time()
            last_display_update = now

        time.sleep(0.01)  # 10ms loop delay


# =============================================================================
# Initialization
# =============================================================================


if HAS_HARDWARE:
    print("Initializing hardware...")

    # Initialize BM83 UART
    uart_bm = busio.UART(board.GP12, board.GP13, baudrate=BM83_BAUD, timeout=0.001)

    # Initialize Nextion UART
    uart_nx = busio.UART(board.GP8, board.GP9, baudrate=NEXTION_BAUD, timeout=0.001)

    # Initialize BLE HID (optional)
    ble_hid = None
    if HAS_BLE:
        try:
            ble = adafruit_ble.BLERadio()
            hid = HIDService()
            advertisement = ProvideServicesAdvertisement(hid)
            advertisement.complete_name = "BM83-Controller"
            ble.start_advertising(advertisement)
            print("BLE HID advertising...")

            # Wait for connection (non-blocking check)
            if ble.connected:
                ble_hid = ConsumerControl(hid.devices)
                print("BLE HID connected")
        except Exception as e:
            print(f"BLE init failed: {e}")

    print("Hardware initialized. Starting main loop...")

    # Initialize display
    nx_send_cmd('tSTATUS.txt="INIT"')
    nx_send_cmd('tTITLE.txt="BM83 Ready"')
    nx_send_cmd('tARTIST.txt=""')
    nx_send_cmd('tALBUM.txt=""')
    nx_send_cmd('tEQ.txt="OFF"')
    nx_send_cmd('tTIME_CUR.txt="00:00"')
    nx_send_cmd('tTIME_TOT.txt="00:00"')

    # Request initial EQ mode from BM83
    time.sleep(0.5)
    # BM83 should send EVT_EQ_MODE_IND on init

    main_loop()
else:
    print("Running in test mode (no hardware)")
