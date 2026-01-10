"""
Nextion HMI display protocol implementation.
Handles token parsing and command sending.
"""
from __future__ import annotations

from collections import deque

# Nextion terminator
TERM = b"\xFF\xFF\xFF"

# EQ map (token -> mode)
EQ_MAP = {
    b"EQ_OFF": 0,
    b"EQ_SOFT": 1,
    b"EQ_BASS": 2,
    b"EQ_TREBLE": 3,
    b"EQ_CLASSICAL": 4,
    b"EQ_ROCK": 5,
    b"EQ_JAZZ": 6,
    b"EQ_POP": 7,
    b"EQ_DANCE": 8,
    b"EQ_RNB": 9,
    b"EQ_USER": 10,
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


def ascii_upper_uscore(data: bytes) -> bool:
    """Check if bytes contain only uppercase ASCII, digits, underscore, and space."""
    if not data:
        return False
    for b in data:
        if not ((65 <= b <= 90) or (48 <= b <= 57) or b == 95 or b == 32):  # A-Z, 0-9, _, space
            return False
    return True


class Nextion:
    """Nextion display protocol handler."""

    def __init__(self, uart=None):
        """Initialize Nextion with optional UART."""
        self.uart = uart
        self.rx_buffer = bytearray()
        self.tx_queue = deque((), 50)  # max 50 commands queued

    def send_cmd(self, cmd: str) -> None:
        """Queue a command to send to Nextion display."""
        self.tx_queue.append(cmd)

    def flush_queue(self) -> None:
        """Send queued commands to Nextion (call in main loop)."""
        if self.uart is None:
            return

        while self.tx_queue:
            cmd = self.tx_queue.popleft()
            frame = cmd.encode("ascii") + TERM
            self.uart.write(frame)
            print(f"NX TX: {cmd}")

    def process_bytes(self, data: bytes, token_handler) -> None:
        """Process incoming Nextion bytes, extract valid tokens."""
        if not data:
            return

        self.rx_buffer.extend(data)

        # Look for terminator
        while True:
            try:
                idx = self.rx_buffer.index(0xFF)
            except ValueError:
                break

            # Check if we have all three terminator bytes
            if idx + 2 >= len(self.rx_buffer):
                break

            if self.rx_buffer[idx:idx+3] == TERM:
                # Extract everything before terminator
                raw_token = self.rx_buffer[:idx]

                # Remove processed bytes including terminator
                self.rx_buffer[:idx+3] = []

                # Filter out non-token bytes from the beginning
                # Find the start of a valid token (A-Z, 0-9, _)
                token_start = 0
                for i, b in enumerate(raw_token):
                    if (65 <= b <= 90) or (48 <= b <= 57) or b == 95:  # A-Z, 0-9, _
                        token_start = i
                        break

                token_candidate = raw_token[token_start:]

                # Validate and handle if it's a valid token
                if ascii_upper_uscore(token_candidate):
                    token_handler(bytes(token_candidate))
            else:
                # False alarm, skip this 0xFF
                self.rx_buffer.pop(0)
