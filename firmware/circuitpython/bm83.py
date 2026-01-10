"""
BM83 Bluetooth module protocol implementation.
Handles frame construction, parsing, checksums, and AVRCP metadata.
"""
from __future__ import annotations

try:
    from utils import hexdump
except ImportError:
    # Fallback for when imported as standalone module in tests
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


class Bm83:
    """BM83 protocol handler."""

    def __init__(self, uart=None):
        """Initialize BM83 with optional UART."""
        self.uart = uart
        self.rx_buffer = bytearray()

    def frame(self, opcode: int, payload: bytes = b"") -> bytes:
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

    def send(self, opcode: int, payload: bytes = b"") -> None:
        """Send a command to BM83."""
        if self.uart is None:
            return
        frame = self.frame(opcode, payload)
        self.uart.write(frame)
        print(f"BM83 TX: {hexdump(frame)}")

    @staticmethod
    def _checksum_valid(data: bytes) -> bool:
        """Verify BM83 frame checksum (excludes 0xAA, len_hi, len_lo)."""
        if len(data) < 2:
            return False
        # Sum all bytes except checksum, then add checksum should equal 0 (mod 256)
        total = sum(data) & 0xFF
        return total == 0

    def parse_frame(self) -> tuple[int, bytes] | None:
        """
        Parse a BM83 frame from buffer.
        Returns (event_code, payload) or None if incomplete/invalid.
        Removes parsed frame from buffer.
        """
        buf = self.rx_buffer

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
        if not self._checksum_valid(checksum_data):
            print(f"BM83 RX: Invalid checksum - {hexdump(frame)}")
            buf[:frame_len] = []  # Discard bad frame
            return None

        event_code = frame[3]
        payload = frame[4:frame_len-1] if length > 1 else b""

        # Remove parsed frame from buffer
        buf[:frame_len] = []

        return (event_code, payload)

    @staticmethod
    def parse_avrcp_metadata(data: bytes) -> dict[str, str | int]:
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
