# code.py — BM83 + Pico 2 W + Nextion (baseline)

from __future__ import annotations

import time

try:
    import board
    import busio
    import digitalio

    HAS_HARDWARE = True
except ImportError:
    board = None  # type: ignore
    busio = None  # type: ignore
    digitalio = None  # type: ignore
    HAS_HARDWARE = False

    class _DummyUART:
        def __init__(self, *_, **__):
            self._buf = b""

        def write(self, data: bytes) -> None:
            print("[DUMMY UART write]", data)

        def read(self, n: int = 1) -> bytes:
            return b""


def hexdump(data: bytes, width: int = 16) -> str:
    if not data:
        return "<empty>"
    parts: list[str] = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        parts.append(" ".join(f"{b:02X}" for b in chunk))
    return " | ".join(parts)


BM83_BAUD = 115200
NX_BAUD = 9600

if HAS_HARDWARE:
    BM83_TX = board.GP12
    BM83_RX = board.GP13
    NX_TX = board.GP8
    NX_RX = board.GP9
    TX_IND_PIN = getattr(board, "GP22", None)

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

    _tx_ind = None
    _prev_tx_ind = None
    if TX_IND_PIN is not None:
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
    BM83_TX = BM83_RX = NX_TX = NX_RX = None
    TX_IND_PIN = None
    nextion = _DummyUART()
    bm83 = _DummyUART()
    _tx_ind = None
    _prev_tx_ind = None
    print("[WARN] Running in dummy mode (no hardware).")


_power_on = False

OP_READ_BD_ADDR = 0x0F
OP_EVENT_MASK = 0x03
OP_BTM_UTILITY_FUNC = 0x13
OP_MMI_ACTION = 0x02
OP_MUSIC_CONTROL = 0x1C
OP_SET_OVERALL_GAIN = 0x23

EVT_PKT_ACK = 0x00
EVT_CONNECTION_STATUS = 0x01

MMI_POWER_ON = 0x01
MMI_POWER_OFF = 0x02
MMI_PAIRING = 0x04
MMI_PLAY_PAUSE = 0x0C
MMI_NEXT = 0x0D
MMI_PREV = 0x0E
MMI_VOL_UP = 0x05
MMI_VOL_DN = 0x06

_CAND_MMI_VOL = [
    (0x05, 0x06),
    (0x45, 0x46),
    (0x55, 0x56),
]

AUTO_MMI_PROBE = False

A2DP_LEVEL_MIN = 0
A2DP_LEVEL_MAX = 15
_a2dp_level = 8

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


def bm83_frame(opcode: int, payload: bytes = b"") -> bytes:
    plen = 1 + len(payload)
    hi = (plen >> 8) & 0xFF
    lo = plen & 0xFF
    body = bytes([opcode]) + payload
    s = sum(body) & 0xFF
    chk = (-s) & 0xFF
    return bytes([0xAA, hi, lo]) + body + bytes([chk])


def bm83_read_event(uart, timeout: float = 0.01):
    if not HAS_HARDWARE:
        return None

    end_time = time.monotonic() + timeout
    while time.monotonic() < end_time:
        b = uart.read(1)
        if not b:
            continue
        if b[0] != 0xAA:
            continue

        hdr = uart.read(2)
        if not hdr or len(hdr) < 2:
            return None
        hi, lo = hdr
        length = (hi << 8) | lo

        body = uart.read(length + 1)
        if not body or len(body) < length + 1:
            return None

        payload = body[:-1]
        chk = body[-1]

        s = sum(payload) & 0xFF
        if ((s + chk) & 0xFF) != 0:
            print("[BM83] Bad checksum in event:", hexdump(b + hdr + body))
            return None

        if len(payload) < 2:
            return None

        evt_opcode = payload[0]

        if evt_opcode == EVT_PKT_ACK:
            if len(payload) < 3:
                return "ACK", 0, 0xFF, b""
            orig_op = payload[1]
            status = payload[2]
            params = payload[3:]
            return "ACK", orig_op, status, params

        status = payload[1]
        params = payload[2:]

        global _power_on
        if evt_opcode == EVT_CONNECTION_STATUS and params:
            state = params[0]
            if state in (0x01, 0x02):
                _power_on = True
            elif state == 0x00:
                _power_on = False

        return "EVT", evt_opcode, status, params

    return None


def bm83_send(
    uart,
    opcode: int,
    payload: bytes = b"",
    *,
    expect_ack: bool = True,
    label: str = "",
) -> bool:
    frame = bm83_frame(opcode, payload)
    uart.write(frame)

    if not HAS_HARDWARE:
        return True
    if not expect_ack:
        return True

    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.3:
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
            print(
                f"[EVT {label}] type={etype} op=0x{eop:02X} status=0x{status:02X} "
                f"data={hexdump(raw)}"
            )
    return False


def bm83_read_bd_addr(uart) -> None:
    bm83_send(uart, OP_READ_BD_ADDR, b"", label="Probe", expect_ack=True)


def bm83_unmask_all(uart) -> None:
    mask = bytes([0xFF] * 8)
    bm83_send(uart, OP_EVENT_MASK, mask, label="EvtMask")


def bm83_connectable(uart, enable: bool = True) -> None:
    mode = 0x01 if enable else 0x00
    payload = bytes([0x0E, mode])
    bm83_send(uart, OP_BTM_UTILITY_FUNC, payload, label="Connectable")


def bm83_set_a2dp_level(uart, level: int) -> bool:
    global _a2dp_level

    level = max(A2DP_LEVEL_MIN, min(A2DP_LEVEL_MAX, int(level)))
    _a2dp_level = level

    data_base_index = 0x00
    mask = 0b00000001
    type_ = 0x03
    gain_a2dp = level
    gain_hf = 0x00
    gain_line_in = 0x00

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
    up_id, dn_id = _CAND_MMI_VOL[0]
    sub = up_id if up else dn_id
    payload = bytes([sub, 0x00])
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="VolRel")


def volume_bump(uart, up: bool = True) -> None:
    if up:
        new_level = min(_a2dp_level + 1, A2DP_LEVEL_MAX)
    else:
        new_level = max(_a2dp_level - 1, A2DP_LEVEL_MIN)

    if new_level == _a2dp_level:
        return

    bm83_set_a2dp_level(uart, new_level)


def bm83_eq_set(uart, mode: int) -> None:
    mode = max(0, min(10, mode))
    payload = bytes([0x07, mode])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="EQ")
    print(f"[EQ] Set EQ mode to {mode}")


def bm83_play(uart) -> None:
    payload = bytes([0x01, 0x00])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Play/Pause")


def bm83_next(uart) -> None:
    payload = bytes([0x02, 0x00])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Next")


def bm83_prev(uart) -> None:
    payload = bytes([0x03, 0x00])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Prev")


def bm83_pair(uart) -> None:
    payload = bytes([0x5D, 0x00])
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="Pair")


def bm83_power_toggle(uart) -> None:
    global _power_on
    sub = MMI_POWER_OFF if _power_on else MMI_POWER_ON
    payload = bytes([sub, 0x00])
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="Power")
    _power_on = not _power_on
    print(f"[POWER] Requested {'ON' if _power_on else 'OFF'}")


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
    if not msg:
        return False
    for b in msg:
        if b == 0x20:
            continue
        if 0x30 <= b <= 0x39:
            continue
        if 0x41 <= b <= 0x5A:
            continue
        if b == 0x5F:
            continue
        return False
    return True


def handle_token(msg: bytes) -> None:
    m = msg.strip()
    if not m:
        return

    print("Action:", m.decode("ascii"))

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


TERM = b"\xFF\xFF\xFF"
NOISE_BYTES = {0x1A, 0x02}

_nx_buf = bytearray()


def process_nextion_bytes(chunk: bytes) -> None:
    global _nx_buf

    if not chunk:
        return

    cleaned = bytes(b for b in chunk if b not in NOISE_BYTES)
    if not cleaned:
        return

    _nx_buf.extend(cleaned)

    while True:
        idx = _nx_buf.find(TERM)
        if idx < 0:
            break

        frame = bytes(_nx_buf[:idx])
        _nx_buf = _nx_buf[idx + len(TERM) :]

        if not frame:
            continue

        msg = frame.strip()
        if not msg:
            continue

        if not _ascii_upper_uscore(msg):
            continue

        if msg in TOKENS:
            handle_token(msg)
            continue

        for t in TOKENS:
            if t in msg:
                handle_token(t)
                break


def run_mmi_probe_cycle(uart) -> None:
    print("[MMI] Starting volume probe cycle…")
    for i, (up_id, dn_id) in enumerate(_CAND_MMI_VOL):
        print(f"[MMI] Candidate {i}: Vol+ 0x{up_id:02X}, Vol- 0x{dn_id:02X}")
        uart.write(bm83_frame(OP_MMI_ACTION, bytes([up_id, 0x00])))
        time.sleep(0.2)
        uart.write(bm83_frame(OP_MMI_ACTION, bytes([dn_id, 0x00])))
        time.sleep(0.2)
    print("[MMI] Probe cycle complete.")


if HAS_HARDWARE:
    print("[BM83] Boot settle…")
    for _ in range(10):
        time.sleep(0.05)

    bm83_read_bd_addr(bm83)
    bm83_unmask_all(bm83)
    bm83_connectable(bm83, True)

    if AUTO_MMI_PROBE:
        run_mmi_probe_cycle(bm83)

    _last_evt_print = 0.0

    while True:
        now = time.monotonic()

        evt = bm83_read_event(bm83, timeout=0.01)
        if evt:
            etype, op, status, data = evt
            interesting = {0x00, 0x10, 0x1A, 0x1B, 0x20, 0x2D}
            if op in interesting or (now - _last_evt_print) > 1.0:
                print(
                    f"[BM83 EVT] type={etype} op=0x{op:02X} status=0x{status:02X} "
                    f"data={hexdump(data)}"
                )
                _last_evt_print = now

        if _tx_ind is not None:
            v = _tx_ind.value
            if v != _prev_tx_ind:
                _prev_tx_ind = v
                print("[TX_IND]", int(v))

        try:
            chunk = nextion.read(64)
        except Exception as e:  # pragma: no cover
            print("[NX] UART read error:", e)
            chunk = None

        if chunk:
            process_nextion_bytes(chunk)

        time.sleep(0.003)
else:
    print("[INFO] Hardware modules not found; main loop disabled.")


if False:
    assert _ascii_upper_uscore(b"BT_PLAY")
    assert _ascii_upper_uscore(b"EQ_CLASSICAL")
    assert _ascii_upper_uscore(b"A1_B2_C3")
    assert not _ascii_upper_uscore(b"bt_play")
    assert not _ascii_upper_uscore(b"BT-PLAY")

    _nx_buf = bytearray()

    def _test_handle_token(msg: bytes) -> None:
        print("[TEST HANDLE]", msg)

    original_handle_token = handle_token
    handle_token = _test_handle_token

    process_nextion_bytes(b"BT_PLAY" + TERM)

    _nx_buf = bytearray()
    process_nextion_bytes(bytes([0x1A]) + b"BT_PLAY" + TERM + bytes([0x02]))

    handle_token = original_handle_token

    print("[TEST] All manual tests passed.")
