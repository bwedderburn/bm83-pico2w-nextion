# code.py — BM83 + Pico 2 W + Nextion (stable baseline)
# Pinout & design notes
#
#  - BM83 UART on UART0  (TX=GP12, RX=GP13, 115200 baud)
#  - Nextion on UART1    (TX=GP8,  RX=GP9,  9600 baud)
#  - Optional TX_IND pin (GP22) if defined on this Pico variant.
#
#  - Nextion sends *ASCII tokens* like BT_PLAY, BT_VOLUP, EQ_BASS
#    terminated with 0xFF 0xFF 0xFF.
#  - Pico parses frames separated by that terminator and filters
#    out any boot-noise / weird non-ASCII bytes.
#  - Tokens are mapped to BM83 host commands (MMI, AVRCP, EQ).
#
#  This version is deliberately verbose and chatty for debugging.
#  You can trim prints once everything feels solid.

from __future__ import annotations

import time

# ---------------------------------------------------------------------------
#  Hardware imports (CircuitPython vs. host / sandbox)
# ---------------------------------------------------------------------------

try:
    import board
    import busio
    import digitalio

    HAS_HARDWARE = True
except ImportError:
    # We are likely running in a non-CircuitPython environment (e.g. PC, sandbox).
    # Provide light dummy shims so the module can import and the pure-Python
    # helpers / tests can still run.
    board = None  # type: ignore
    busio = None  # type: ignore
    digitalio = None  # type: ignore

    HAS_HARDWARE = False

    class _DummyUART:
        def __init__(self, *_, **__):
            self._buf = b""

        def write(self, data: bytes) -> None:
            # In host mode, just print what would have been sent.
            print("[DUMMY UART write]", data)

        def read(self, n: int = 1) -> bytes:
            # No incoming data in dummy mode.
            return b""


# ---------------------------------------------------------------------------
#  Small hex dump helper
# ---------------------------------------------------------------------------


def hexdump(data: bytes, width: int = 16) -> str:
    """Return a short hex representation of a bytes object."""
    if not data:
        return "<empty>"
    s = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        s.append(" ".join(f"{b:02X}" for b in chunk))
    return " | ".join(s)


# ---------------------------------------------------------------------------
#  UART setup / globals
# ---------------------------------------------------------------------------

# Defaults (usable in both hardware and dummy mode)
BM83_BAUD = 115200
NX_BAUD = 9600

if HAS_HARDWARE:
    # BM83 on UART0
    BM83_TX = board.GP12
    BM83_RX = board.GP13

    # Nextion on UART1
    NX_TX = board.GP8
    NX_RX = board.GP9

    # Optional TX indicator pin (if present on Pico)
    TX_IND_PIN = getattr(board, "GP22", None)

    # Create UART objects
    nextion = busio.UART(
        NX_TX,
        NX_RX,
        baudrate=NX_BAUD,
        timeout=0.01,
        receiver_buffer_size=128,
    )

    bm83 = busio.UART(
        BM83_TX,
        BM83_RX,
        baudrate=BM83_BAUD,
        timeout=0.02,
        receiver_buffer_size=256,
    )

    # Optional TX activity GPIO
    _tx_ind = None
    _prev_tx_ind = None
    if "TX_IND_PIN" in globals() and TX_IND_PIN is not None:
        try:
            _tx_ind = digitalio.DigitalInOut(TX_IND_PIN)
            _tx_ind.switch_to_input()
            _prev_tx_ind = _tx_ind.value
        except Exception as e:  # pragma: no cover
            print("[WARN] Could not init TX_IND pin:", e)
            _tx_ind = None

    print(f"[BM83] Host UART @ {BM83_BAUD}  TX={BM83_TX} RX={BM83_RX}")
    print(f"[NX ] UART @ {NX_BAUD}  TX={NX_TX} RX={NX_RX}")
    print("Ready: VOL↑/VOL↓ = volume, PAIR enters pairing, EQ_* selects preset")

else:
    # Dummy / host mode: provide stand-ins so the rest of the module works.
    BM83_TX = BM83_RX = NX_TX = NX_RX = None
    TX_IND_PIN = None
    nextion = _DummyUART()
    bm83 = _DummyUART()
    _tx_ind = None
    _prev_tx_ind = None
    print("[WARN] busio/board/digitalio not available; running in dummy mode (no hardware).")


# ---------------------------------------------------------------------------
#  BM83 protocol helper
# ---------------------------------------------------------------------------

# BM83 packet format:
#   0xAA, len_hi, len_lo, opcode, [payload...], checksum
# where: len = 1 + payload_len (because opcode counts as 1)


def bm83_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build a BM83 host command frame."""
    plen = 1 + len(payload)
    hi = (plen >> 8) & 0xFF
    lo = plen & 0xFF
    body = bytes([opcode]) + payload
    chk = (~(sum(body) & 0xFF) + 1) & 0xFF
    return bytes([0xAA, hi, lo]) + body + bytes([chk])


# Global track of power state (best effort via events)
_power_on = False


# Some opcodes we care about (not exhaustive)
OP_READ_BD_ADDR = 0x0F
OP_EVENT_MASK = 0x03
OP_BTM_UTILITY_FUNC = 0x13
OP_MMI_ACTION = 0x02
OP_MUSIC_CONTROL = 0x1C
OP_SET_OVERALL_GAIN = 0x23


# MMI sub-IDs (these are firmware-dependent; these values match
# common BM83 images but there can be variations).
MMI_POWER_ON = 0x01
MMI_POWER_OFF = 0x02
MMI_PAIRING = 0x04  # or 0x5D depending on image
MMI_PLAY_PAUSE = 0x0C
MMI_NEXT = 0x0D
MMI_PREV = 0x0E
MMI_VOL_UP = 0x05
MMI_VOL_DN = 0x06


# A small set of candidate MMI IDs for volume up/down; we can try
# them in turn until we find the one that behaves as expected.
_CAND_MMI_VOL = [
    (0x05, 0x06),  # common default: Vol+ / Vol-
    (0x45, 0x46),  # alternate mapping
    (0x55, 0x56),  # another variant
]

# If True, we will automatically probe possible MMI codes for
# volume at startup (by stepping volume up/down once per mapping).
AUTO_MMI_PROBE = False


# A2DP master level (BM83-side trim / limiter)
A2DP_LEVEL_MIN = 0
A2DP_LEVEL_MAX = 15
_a2dp_level = 8  # starting A2DP master level; tune by ear


# EQ mode mapping (host uses 0-10 for the standard 11 presets)
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


def bm83_send(
    uart,
    opcode: int,
    payload: bytes = b"",
    *,
    expect_ack: bool = True,
    label: str = "",
) -> bool:
    """Send a BM83 command and optionally wait for the ACK event.

    Returns True if an ACK with matching opcode is seen (status 0), False otherwise.
    If expect_ack=False, we just fire-and-forget.
    """

    frame = bm83_frame(opcode, payload)
    uart.write(frame)

    if not expect_ack:
        return True

    # Minimal ACK/event listener. BM83 events start with 0xAA too.
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3:  # 300 ms window
        evt = bm83_read_event(uart, timeout=0.05)
        if not evt:
            continue
        etype, eop, status, raw = evt
        if etype == "ACK" and eop == opcode:
            if status == 0:
                if label:
                    print(f"[ACK {label}] op=0x{opcode:02X} status=0x00")
                return True
            else:
                print(f"[ACK {label}] op=0x{opcode:02X} status=0x{status:02X}")
                return False
        else:
            # Some other event; show short debug
            print(
                f"[EVT {label}] type={etype} op=0x{eop:02X} status=0x{status:02X} "
                f"data={hexdump(raw)}"
            )
    return False


def bm83_read_event(uart, timeout: float = 0.01):
    """Read and parse one BM83 event frame, if available.

    Returns (etype, opcode, status, payload) or None.
    etype is one of "ACK" or "EVT".
    """

    # In dummy mode, there are no events.
    if not HAS_HARDWARE:
        return None

    end_time = time.monotonic() + timeout

    while time.monotonic() < end_time:
        b = uart.read(1)
        if not b:
            continue
        if b[0] != 0xAA:
            # Ignore stray bytes
            continue

        # Read length hi/lo
        hdr = uart.read(2)
        if not hdr or len(hdr) < 2:
            return None
        hi, lo = hdr
        length = (hi << 8) | lo
        # length includes the opcode/status/whatever, but we must
        # read that many bytes plus a checksum.
        body = uart.read(length + 1)
        if not body or len(body) < length + 1:
            return None

        payload = body[:-1]
        chk = body[-1]

        # Verify checksum
        s = sum(payload) & 0xFF
        if ((s + chk) & 0xFF) != 0:
            print("[BM83] Bad checksum in event:", hexdump(b + hdr + body))
            return None

        # Event frames typically: opcode, status, [params...]
        if len(payload) < 2:
            return None

        evt_opcode = payload[0]
        status = payload[1]
        params = payload[2:]

        etype = "ACK" if evt_opcode == 0x00 else "EVT"

        # Track power state heuristically via events
        global _power_on
        if etype == "EVT" and evt_opcode == 0x01:
            # connection state-ish
            if len(params) >= 1:
                state = params[0]
                if state in (0x02, 0x01):  # on/connected
                    _power_on = True
                elif state == 0x00:  # off/disconnected
                    _power_on = False

        return etype, evt_opcode, status, params

    return None


# Convenience wrappers


def bm83_read_bd_addr(uart) -> None:
    bm83_send(uart, OP_READ_BD_ADDR, b"", label="Probe", expect_ack=True)


def bm83_unmask_all(uart) -> None:
    # Event mask payload varies by FW; here we just unmask everything with 0xFF.
    mask = bytes([0xFF] * 8)
    bm83_send(uart, OP_EVENT_MASK, mask, label="EvtMask")


def bm83_connectable(uart, enable: bool = True) -> None:
    # BTM utility func 0x0E: Set connectable
    mode = 0x01 if enable else 0x00
    payload = bytes([0x0E, mode])
    bm83_send(uart, OP_BTM_UTILITY_FUNC, payload, label="Connectable")


# ---------------------------------------------------------------------------
#  Volume control (BM83-side A2DP master level)
# ---------------------------------------------------------------------------


def bm83_set_a2dp_level(uart, level: int) -> bool:
    """Set A2DP output level (0-15) using Set_Overall_Gain.

    This only touches the A2DP path (Mask bit0). HF/Line-In stay untouched
    so calls and other paths can be handled separately in config.
    """
    global _a2dp_level

    level = max(A2DP_LEVEL_MIN, min(A2DP_LEVEL_MAX, int(level)))
    _a2dp_level = level

    data_base_index = 0x00       # only one linked device
    mask = 0b00000001            # bit0 = A2DP gain
    type_ = 0x03                 # absolute level mode (0–15)
    gain_a2dp = level
    gain_hf = 0x00               # ignored because mask bit1 = 0
    gain_line_in = 0x00          # ignored because mask bit2 = 0

    payload = bytes([
        data_base_index,
        mask,
        type_,
        gain_a2dp,
        gain_hf,
        gain_line_in,
    ])

    ok = bm83_send(uart, OP_SET_OVERALL_GAIN, payload, label="A2DP_Gain")
    if ok:
        print(f"[VOL] A2DP level set to {level}")
    else:
        print(f"[VOL] Failed to set A2DP level to {level}")
    return ok


def bm83_vol_relative(uart, up: bool = True) -> None:
    """Send one relative volume step via MMI (Vol+/Vol-).

    Kept for completeness / possible future use. Not used by the
    Nextion-driven A2DP master volume, which relies on absolute gain.
    """
    up_id, dn_id = _CAND_MMI_VOL[0]
    sub = up_id if up else dn_id
    payload = bytes([sub, 0x00])  # 0x00 = "short press" for many firmwares
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="VolRel")


def volume_bump(uart, up: bool = True) -> None:
    """High-level volume change: adjust A2DP level in the 0–15 range.

    Phone volume is still active (AVRCP 1.6 absolute volume), but this
    behaves as a BM83-side master/trim so you can keep the amp in a
    safe range regardless of handset level.
    """
    if up:
        new_level = min(_a2dp_level + 1, A2DP_LEVEL_MAX)
    else:
        new_level = max(_a2dp_level - 1, A2DP_LEVEL_MIN)

    if new_level == _a2dp_level:
        return  # already at limit

    bm83_set_a2dp_level(uart, new_level)


# ---------------------------------------------------------------------------
#  EQ control helper
# ---------------------------------------------------------------------------


def bm83_eq_set(uart, mode: int) -> None:
    """Set EQ preset by mode index (0-10)."""
    mode = max(0, min(10, mode))
    # Many firmwares use MUSIC_CONTROL 0x1C, sub-ID 0x07 or 0x08 for EQ.
    # Here we assume 0x07, param = EQ index.
    payload = bytes([0x07, mode])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="EQ")
    print(f"[EQ] Set EQ mode to {mode}")


# ---------------------------------------------------------------------------
#  Simple transport helpers
# ---------------------------------------------------------------------------


def bm83_play(uart) -> None:
    # Many firmwares use MUSIC_CONTROL sub-ID 0x01 for play/pause toggle.
    payload = bytes([0x01, 0x00])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Play/Pause")


def bm83_next(uart) -> None:
    payload = bytes([0x02, 0x00])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Next")


def bm83_prev(uart) -> None:
    payload = bytes([0x03, 0x00])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Prev")


def bm83_pair(uart) -> None:
    # MMI pairing; commonly 0x04 or 0x5D. We can start with 0x5D,
    # which is widely documented as "Enter pairing mode".
    payload = bytes([0x5D, 0x00])
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="Pair")


def bm83_power_toggle(uart) -> None:
    """Heuristic power toggle via MMI based on _power_on flag."""
    global _power_on
    sub = MMI_POWER_OFF if _power_on else MMI_POWER_ON
    payload = bytes([sub, 0x00])
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="Power")
    # We assume it will succeed; the next EVT will refine _power_on.
    _power_on = not _power_on
    print(f"[POWER] Requested {'ON' if _power_on else 'OFF'}")


# ---------------------------------------------------------------------------
#  Nextion token handling
# ---------------------------------------------------------------------------

# Canonical tokens from Nextion (ASCII, uppercase, underscore)
TOK_BT = [
    b"BT_POWER",
    b"BT_PAIR",
    b"BT_PLAY",
    b"BT_NEXT",
    b"BT_PREV",
    b"BT_VOLUP",
    b"BT_VOLDN",
]

TOK_EQ = [
    b"EQ_OFF",
    b"EQ_SOFT",
    b"EQ_BASS",
    b"EQ_TREBLE",
    b"EQ_CLASSICAL",
    b"EQ_ROCK",
    b"EQ_JAZZ",
    b"EQ_POP",
    b"EQ_DANCE",
    b"EQ_RNB",
    b"EQ_USER",
]

TOKENS = TOK_BT + TOK_EQ


def _ascii_upper_uscore(msg: bytes) -> bool:
    """True if msg is composed of [A-Z0-9_ ] after stripping."""
    if not msg:
        return False
    for b in msg:
        if b in (0x20,):  # space
            continue
        if 0x30 <= b <= 0x39:  # 0-9
            continue
        if 0x41 <= b <= 0x5A:  # A-Z
            continue
        if b == 0x5F:  # underscore
            continue
        return False
    return True


def handle_token(msg: bytes) -> None:
    """Map a Nextion token to BM83 actions."""
    m = msg.strip()
    if not m:
        return

    print("Action:", m.decode("ascii", errors="ignore"))

    if m == b"BT_POWER":
        bm83_power_toggle(bm83)
    elif m == b"BT_PAIR":
        bm83_pair(bm83)
    elif m == b"BT_PLAY":
        bm83_play(bm83)
    elif m == b"BT_NEXT":
        bm83_next(bm83)
    elif m == b"BT_PREV":
        bm83_prev(bm83)
    elif m == b"BT_VOLUP":
        volume_bump(bm83, up=True)
    elif m == b"BT_VOLDN":
        volume_bump(bm83, up=False)
    elif m in TOK_EQ:
        mode = EQ_MAP.get(m, 0)
        bm83_eq_set(bm83, mode)
    else:
        print("[WARN] Unhandled token:", m)


# ---------------------------------------------------------------------------
#  Nextion frame parsing
# ---------------------------------------------------------------------------

# Nextion typically uses 0xFF 0xFF 0xFF as a frame terminator.
TERM = b"\xFF\xFF\xFF"


# Some Discovery/Basic models emit weird boot noise bytes (0x1A, 0x02,
# etc.) on reset. We filter them out so they never become tokens.
NOISE_BYTES = {0x1A, 0x02}


# Rolling buffer for Nextion data
_nx_buf = bytearray()


def process_nextion_bytes(chunk: bytes) -> None:
    """Feed raw bytes from Nextion; parse frames and dispatch tokens.

    This function appends to a rolling buffer, splits by 0xFF 0xFF 0xFF,
    filters boot noise, then calls handle_token() for recognized tokens.
    """
    if not chunk:
        return

    # Strip obvious noise first
    cleaned = bytes(b for b in chunk if b not in NOISE_BYTES)
    if not cleaned:
        return

    _nx_buf.extend(cleaned)

    # Process frames while we still have a terminator
    while True:
        idx = _nx_buf.find(TERM)
        if idx < 0:
            # No complete frame yet
            break

        frame = bytes(_nx_buf[:idx])
        del _nx_buf[: idx + len(TERM)]

        if not frame:
            continue

        msg = frame.strip()
        if not msg:
            continue

        # Only allow ASCII [A-Z0-9_ ] patterns to avoid junk
        if not _ascii_upper_uscore(msg):
            # Uncomment if you want to see all rejected frames:
            # print("[NX] (ignored)", hexdump(msg))
            # print("Unknown Nextion msg:", msg)
            continue

        # At this point we have a clean ASCII token candidate.
        # If it's exactly one of our known tokens, dispatch.
        if msg in TOKENS:
            handle_token(msg)
            continue

        # If not exact match, try substring fallback: e.g. if we got
        # something like "00BT_PLAY" for some reason.
        for t in TOKENS:
            if t in msg:
                handle_token(t)
                break
        else:
            # No known token inside; safe to ignore or log.
            # print("[NX] (unrecognized)", hexdump(msg))
            pass


# ---------------------------------------------------------------------------
#  Optional MMI volume probe (disabled unless AUTO_MMI_PROBE=True)
# ---------------------------------------------------------------------------


def run_mmi_probe_cycle(uart) -> None:
    """Optionally probe different MMI volume mappings.

    This is intentionally conservative: it only nudges volume a little
    in each mapping, and prints which sub-IDs were tried.
    """
    print("[MMI] Starting volume probe cycle…")
    for i, (up_id, dn_id) in enumerate(_CAND_MMI_VOL):
        print(f"[MMI] Candidate {i}: Vol+ 0x{up_id:02X}, Vol- 0x{dn_id:02X}")
        # One small up/down nudge each
        uart.write(bm83_frame(OP_MMI_ACTION, bytes([up_id, 0x00])))
        time.sleep(0.2)
        uart.write(bm83_frame(OP_MMI_ACTION, bytes([dn_id, 0x00])))
        time.sleep(0.2)
    print("[MMI] Probe cycle complete.")


# ---------------------------------------------------------------------------
#  Initial BM83 bring-up and main loop
# ---------------------------------------------------------------------------

if HAS_HARDWARE:
    # Short delay to let BM83 boot
    print("[BM83] Boot settle…")
    for _ in range(10):
        time.sleep(0.05)

    # Probe BD_ADDR (mainly to confirm comms)
    bm83_read_bd_addr(bm83)

    # Unmask all events so we see useful status
    bm83_unmask_all(bm83)

    # Tell BM83 to be connectable
    bm83_connectable(bm83, True)

    # Optionally run MMI volume mapping probe
    if AUTO_MMI_PROBE:
        run_mmi_probe_cycle(bm83)

    _last_evt_print = 0.0

    while True:
        now = time.monotonic()

        # 1) Drain any BM83 events (non-blocking-ish)
        evt = bm83_read_event(bm83, timeout=0.01)
        if evt:
            etype, op, status, data = evt
            # Print only interesting events or occasionally others
            interesting = {0x00, 0x10, 0x1A, 0x1B, 0x20, 0x2D}
            if op in interesting or (now - _last_evt_print) > 1.0:
                print(
                    f"[BM83 EVT] type={etype} op=0x{op:02X} status=0x{status:02X} "
                    f"data={hexdump(data)}"
                )
                _last_evt_print = now

        # 2) Optional TX indicator monitoring
        if _tx_ind is not None:
            v = _tx_ind.value
            if v != _prev_tx_ind:
                _prev_tx_ind = v
                print("[TX_IND]", int(v))

        # 3) Read any Nextion data and process frames
        try:
            chunk = nextion.read(64)
        except Exception as e:  # pragma: no cover
            print("[NX] UART read error:", e)
            chunk = None

        if chunk:
            # Uncomment if you want to see raw Nextion bytes:
            # print("Raw bytes from Nextion:", chunk)
            process_nextion_bytes(chunk)

        # Avoid tight spin
        time.sleep(0.003)

else:
    # In non-hardware environments we do **not** start the infinite loop.
    print("[INFO] Hardware modules not found; BM83/Nextion main loop is disabled.")


# ---------------------------------------------------------------------------
#  Manual test cases (for host-side sanity checks)
# ---------------------------------------------------------------------------

if False:  # Set to True only when running in a suitable test environment
    # Basic tests for _ascii_upper_uscore
    assert _ascii_upper_uscore(b"BT_PLAY")
    assert _ascii_upper_uscore(b"EQ_CLASSICAL")
    assert _ascii_upper_uscore(b"A1_B2_C3")
    assert not _ascii_upper_uscore(b"bt_play")  # lowercase should fail
    assert not _ascii_upper_uscore(b"BT-PLAY")  # dash should fail

    # Simple process_nextion_bytes test using a fake handler
    _nx_buf = bytearray()

    def _test_handle_token(msg: bytes) -> None:
        print("[TEST HANDLE]", msg)

    # Monkey-patch handle_token for this test
    original_handle_token = handle_token
    handle_token = _test_handle_token

    # Feed a clean token frame
    process_nextion_bytes(b"BT_PLAY" + TERM)

    # Feed with noise bytes around the token; should still detect BT_PLAY
    _nx_buf = bytearray()
    process_nextion_bytes(bytes([0x1A]) + b"BT_PLAY" + TERM + bytes([0x02]))

    # Restore real handler
    handle_token = original_handle_token

    print("[TEST] All manual tests passed.")
