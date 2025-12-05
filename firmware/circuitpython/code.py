# code.py — BM83 + Pico 2 W + Nextion (BM83 control + AVRCP metadata + EQ via Vol±)

from __future__ import annotations

import time

import board
import busio
import digitalio


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

BM83_TX = board.GP12
BM83_RX = board.GP13
NX_TX = board.GP8
NX_RX = board.GP9

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


_power_on = False

# ---- UART opcodes (from Audio UART Command Set) ----
OP_READ_BD_ADDR = 0x0F
OP_EVENT_MASK = 0x03
OP_BTM_UTILITY_FUNC = 0x13
OP_MMI_ACTION = 0x02
OP_MUSIC_CONTROL = 0x04        # Music_Control (0x04)
OP_EQ_MODE_SETTING = 0x1C      # EQ_Mode_Setting (0x1C)
OP_SET_OVERALL_GAIN = 0x23
OP_AVRCP_SPECIFIC = 0x0B       # AVRCP Specific Command (0x0B)

# Events
EVT_PKT_ACK = 0x00
EVT_CONNECTION_STATUS = 0x01
EVT_EQ_MODE_INDICATION = 0x10  # (ignored; we drive EQ from UI)

# Music control sub-codes (for OP_MUSIC_CONTROL 0x04)
MC_PLAY_PAUSE = 0x07
MC_NEXT       = 0x09
MC_PREV       = 0x0A

# MMI actions for power / pairing (press/release style)
MMI_POWER_ON_PRESS    = 0x51
MMI_POWER_ON_RELEASE  = 0x52
MMI_POWER_OFF_PRESS   = 0x53
MMI_POWER_OFF_RELEASE = 0x54
MMI_ENTER_PAIRING     = 0x5D

# AVRCP / metadata
PDU_GET_ELEMENT_ATTRIBUTES = 0x20  # Get Element Attributes (all info)

# Poll metadata more aggressively now that fluff is removed
META_POLL_INTERVAL = 1.0  # seconds (was ~2.5)

# ---- Track timing / live position state ----
_current_track_ms = 0          # total track length from metadata (ms)
_current_pos_ms = 0            # accumulated position when paused (ms)
_pos_start_monotonic = None    # monotonic() timestamp when last started
_is_playing = False            # our best guess of play/pause state
_last_timecur_update = 0.0     # last time we pushed tTIME_CUR
_last_meta_key = None          # (title, artist, album, raw_time) for track-change detection

# ---- EQ mapping & state ----
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

EQ_LABELS = {
    0: "OFF",
    1: "SOFT",
    2: "BASS",
    3: "TREBLE",
    4: "CLASSICAL",
    5: "ROCK",
    6: "JAZZ",
    7: "POP",
    8: "DANCE",
    9: "RNB",
    10: "USER",
}

_current_eq_mode = 0  # track what we think the EQ mode is


# ---- Nextion helpers ----

def nx_send_cmd(cmd: str) -> None:
    """Send a raw Nextion command with 0xFF 0xFF 0xFF terminator."""
    data = cmd.encode("ascii", "replace") + b"\xFF\xFF\xFF"
    try:
        nextion.write(data)
    except Exception as e:
        print("[NX] UART write error:", e)


def nx_set_eq_label(mode: int) -> None:
    """Update EQ labels on one or more Nextion pages.

    We keep the same naming as before so EQ feedback wiring remains
    unchanged. You can have any subset of these in the HMI:
      - tEQ0  (e.g. main music page)
      - tEQ1  (legacy; safe if removed)
      - tEQ2  (another page if desired)
    """
    label = EQ_LABELS.get(mode, f"EQ{mode}")
    print(f"[EQ] Mode {mode} ({label})")

    targets = ["tEQ0", "tEQ1", "tEQ2"]
    for name in targets:
        nx_send_cmd(f'{name}.txt="{label}"')


def _nx_safe_text(s: str, max_len: int = 40) -> str:
    """Sanitize text for Nextion (strip CR/LF/quotes, limit length)."""
    s = s.replace("\r", " ").replace("\n", " ")
    s = s.replace('"', "'")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _format_ms_as_min_sec(ms: int) -> str:
    """Format milliseconds as 'Xm Ys'."""
    if ms < 0:
        ms = 0
    total_secs = ms // 1000
    minutes = total_secs // 60
    seconds = total_secs % 60
    return f"{minutes}m {seconds}s"


def nx_update_current_time(ms: int) -> None:
    """Update live playback position text field tTIME_CUR."""
    txt = _format_ms_as_min_sec(ms)
    nx_send_cmd(f'tTIME_CUR.txt="{txt}"')


def nx_update_metadata(meta: dict) -> None:
    """Push AVRCP metadata dict to Nextion text fields.

    Expects component names:
      - tTitle
      - tArtist
      - tAlbum
      - tGenre
      - tTime     (total track time)
      - tTIME_CUR (live position, updated elsewhere)

    We only reset the live timer when we detect a *track change* based on a
    key of (title, artist, album, raw_time). This avoids the current time
    jumping back to 0 on every periodic metadata poll.
    """
    global _current_track_ms, _current_pos_ms, _pos_start_monotonic
    global _is_playing, _last_meta_key

    try:
        title = _nx_safe_text(meta.get(1, ""))
        artist = _nx_safe_text(meta.get(2, ""))
        album = _nx_safe_text(meta.get(3, ""))
        genre = _nx_safe_text(meta.get(6, ""))

        raw_time = meta.get(7, "")  # usually milliseconds string
        track_key = (title, artist, album, str(raw_time))

        ms_value = None
        ptime = ""
        if raw_time:
            try:
                ms_value = int(str(raw_time).strip())
                ptime = _format_ms_as_min_sec(ms_value)
            except Exception:
                # If it isn't an integer, just show it as text
                ptime = _nx_safe_text(str(raw_time))

        if title:
            nx_send_cmd(f'tTitle.txt="{title}"')
        if artist:
            nx_send_cmd(f'tArtist.txt="{artist}"')
        if album:
            nx_send_cmd(f'tAlbum.txt="{album}"')
        if genre:
            nx_send_cmd(f'tGenre.txt="{genre}"')
        if ptime:
            nx_send_cmd(f'tTime.txt="{ptime}"')
            if isinstance(ms_value, int):
                _current_track_ms = ms_value

        # Only when the track key changes do we reset the live timer to 0.
        if _last_meta_key != track_key:
            _last_meta_key = track_key
            _current_pos_ms = 0
            _pos_start_monotonic = time.monotonic() if _is_playing else None
            nx_update_current_time(0)

    except Exception as e:
        print("[NX] Metadata update error:", e)


# ---- BM83 framing / event handling ----

def bm83_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build a BM83 UART frame.

    Checksum is the 2's complement of (len_hi + len_lo + opcode + params).
    """
    plen = 1 + len(payload)
    hi = (plen >> 8) & 0xFF
    lo = plen & 0xFF
    body = bytes([opcode]) + payload
    s = (hi + lo + sum(body)) & 0xFF
    chk = (-s) & 0xFF
    return bytes([0xAA, hi, lo]) + body + bytes([chk])


def bm83_read_event(uart, timeout: float = 0.01):
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

        # BM83 checksum covers len_hi + len_lo + opcode + params
        s = (hi + lo + sum(payload)) & 0xFF
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
    """Enable standard event reporting (4-byte 0x00 mask)."""
    mask = bytes([0x00, 0x00, 0x00, 0x00])
    bm83_send(uart, OP_EVENT_MASK, mask, label="EvtMask")


def bm83_connectable(uart, enable: bool = True) -> None:
    """Put BM83 into connectable / non-connectable mode."""
    payload = bytes([0x03, 0x01 if enable else 0x00])
    bm83_send(uart, OP_BTM_UTILITY_FUNC, payload, label="Connectable")


# ---- AVRCP metadata helpers ----

def bm83_request_metadata(uart) -> None:
    """Request AVRCP 'all information of the media' for current track."""
    payload = b"\x00\x20\x00\x00\x0D" + (b"\x00" * 13)
    bm83_send(uart, OP_AVRCP_SPECIFIC, payload,
              expect_ack=True, label="AVRCP_GetMeta")


def _parse_avrcp_metadata_block(data: bytes) -> dict:
    """Parse AVRCP GetElementAttributes response into {attr_id: text}."""
    meta: dict[int, str] = {}
    n = len(data)
    i = 0
    while i + 8 <= n:
        if not (data[i] == 0x00 and data[i + 1] == 0x00 and data[i + 2] == 0x00):
            i += 1
            continue
        attr_id = data[i + 3]
        if not (1 <= attr_id <= 7):
            i += 1
            continue
        if i + 8 > n:
            break
        # charset = (data[i + 4] << 8) | data[i + 5]
        length = (data[i + 6] << 8) | data[i + 7]
        start = i + 8
        end = start + length
        if end > n:
            break
        raw = data[start:end]
        try:
            text = raw.decode("utf-8", "replace")
        except Exception:
            text = repr(raw)
        meta[attr_id] = text
        i = end
    if meta:
        for aid, txt in meta.items():
            name = {
                1: "Title",
                2: "Artist",
                3: "Album",
                4: "Track#",
                5: "TotalTracks",
                6: "Genre",
                7: "Time(ms)",
            }.get(aid, f"Attr{aid}")
            print(f"[META] {name}: {txt}")
    return meta


# ---- EQ commands ----

def bm83_eq_set(uart, mode: int) -> None:
    """Set EQ mode via EQ_Mode_Setting (0x1C) and update indicator."""
    global _current_eq_mode
    mode = max(0, min(10, mode))
    _current_eq_mode = mode

    payload = bytes([mode, 0x00])
    bm83_send(uart, OP_EQ_MODE_SETTING, payload, expect_ack=False, label="EQ")
    nx_set_eq_label(mode)


# ---- Music control (play / next / prev) via Music_Control (0x04) ----

def bm83_play(uart) -> None:
    payload = bytes([0x00, MC_PLAY_PAUSE])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Play/Pause")


def bm83_next(uart) -> None:
    global _current_pos_ms, _pos_start_monotonic
    payload = bytes([0x00, MC_NEXT])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Next")
    # Reset position to 0 for new track
    _current_pos_ms = 0
    _pos_start_monotonic = time.monotonic() if _is_playing else None
    # Refresh metadata
    bm83_request_metadata(uart)


def bm83_prev(uart) -> None:
    global _current_pos_ms, _pos_start_monotonic
    payload = bytes([0x00, MC_PREV])
    bm83_send(uart, OP_MUSIC_CONTROL, payload, expect_ack=False, label="Prev")
    _current_pos_ms = 0
    _pos_start_monotonic = time.monotonic() if _is_playing else None
    bm83_request_metadata(uart)


def bm83_pair(uart) -> None:
    payload = bytes([0x00, MMI_ENTER_PAIRING])
    bm83_send(uart, OP_MMI_ACTION, payload, expect_ack=False, label="Pair")


def bm83_power_on(uart) -> bool:
    """Power ON via MMI press/release sequence (0x51/0x52)."""
    global _power_on
    print("[POWER] ON")
    ok1 = bm83_send(
        uart, OP_MMI_ACTION, bytes([0x00, MMI_POWER_ON_PRESS]),
        label="PwrOn-press"
    )
    time.sleep(0.2)
    ok2 = bm83_send(
        uart, OP_MMI_ACTION, bytes([0x00, MMI_POWER_ON_RELEASE]),
        label="PwrOn-release"
    )
    if ok1 and ok2:
        _power_on = True
    return ok1 and ok2


def bm83_power_off(uart) -> bool:
    """Power OFF via MMI press/release sequence (0x53/0x54)."""
    global _power_on
    print("[POWER] OFF")
    ok1 = bm83_send(
        uart, OP_MMI_ACTION, bytes([0x00, MMI_POWER_OFF_PRESS]),
        label="PwrOff-press"
    )
    time.sleep(1.5)
    ok2 = bm83_send(
        uart, OP_MMI_ACTION, bytes([0x00, MMI_POWER_OFF_RELEASE]),
        label="PwrOff-release"
    )
    if ok1 and ok2:
        _power_on = False
    return ok1 and ok2


def bm83_power_toggle(uart) -> None:
    """Robust power toggle."""
    global _power_on
    if _power_on is True:
        if not bm83_power_off(uart):
            bm83_power_on(uart)
            return
    if _power_on is False:
        if not bm83_power_on(uart):
            bm83_power_off(uart)
            return
    if not bm83_power_on(uart):
        bm83_power_off(uart)
    print(f"[POWER] Requested {'ON' if _power_on else 'OFF'}")


# ---- Nextion token handling ----

TOK_BT = [
    b"BT_POWER",
    b"BT_PAIR",
    b"BT_PLAY",
    b"BT_NEXT",
    b"BT_PREV",
    b"BT_VOLUP",   # repurposed: cycle EQ preset
    b"BT_VOLDN",   # repurposed: EQ_OFF
    b"BT_META",    # request AVRCP metadata manually (optional)
]

TOK_EQ = list(EQ_MAP.keys())

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
    global _is_playing, _current_pos_ms, _pos_start_monotonic, _current_eq_mode

    m = msg.strip()
    if not m:
        return

    print("Action:", m.decode("ascii"))

    if m == b"BT_POWER":
        bm83_power_toggle(bm83)
    elif m == b"BT_PAIR":
        bm83_pair(bm83)
    elif m == b"BT_PLAY":
        # Toggle play/pause in our local timing model
        now = time.monotonic()
        if _is_playing and _pos_start_monotonic is not None:
            # accumulate elapsed time into base position
            _current_pos_ms += int((now - _pos_start_monotonic) * 1000)
            _pos_start_monotonic = None
            _is_playing = False
        else:
            _pos_start_monotonic = now
            _is_playing = True
        bm83_play(bm83)
    elif m == b"BT_NEXT":
        _current_pos_ms = 0
        _pos_start_monotonic = time.monotonic() if _is_playing else None
        bm83_next(bm83)
    elif m == b"BT_PREV":
        _current_pos_ms = 0
        _pos_start_monotonic = time.monotonic() if _is_playing else None
        bm83_prev(bm83)

    # ---- Vol+ / Vol- repurposed for EQ control ----
    elif m == b"BT_VOLUP":
        # Cycle through EQ modes 0..10
        max_mode = max(EQ_LABELS.keys())
        next_mode = (_current_eq_mode + 1) % (max_mode + 1)
        bm83_eq_set(bm83, next_mode)
    elif m == b"BT_VOLDN":
        # Hard EQ Off
        bm83_eq_set(bm83, 0)

    elif m == b"BT_META":
        bm83_request_metadata(bm83)

    # ---- EQ selection via explicit EQ_* tokens (unchanged) ----
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
        _nx_buf = _nx_buf[idx + len(TERM):]

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


def _update_live_time(now: float) -> None:
    """Update tTIME_CUR every ~0.25 s based on our timing model.

    We integrate from time.monotonic(), so loop and polling jitter are
    inherently included; tightening the update interval just makes the
    on-screen time feel more "live".
    """
    global _last_timecur_update, _current_pos_ms, _pos_start_monotonic

    if now - _last_timecur_update < 0.25:
        return
    _last_timecur_update = now

    pos_ms = _current_pos_ms
    if _is_playing and _pos_start_monotonic is not None:
        pos_ms += int((now - _pos_start_monotonic) * 1000)

    if _current_track_ms > 0 and pos_ms > _current_track_ms:
        pos_ms = _current_track_ms

    nx_update_current_time(pos_ms)


# ---- Main ----

print("[BM83] Boot settle…")
for _ in range(10):
    time.sleep(0.05)

bm83_read_bd_addr(bm83)
bm83_unmask_all(bm83)
bm83_connectable(bm83, True)

# Default EQ preset: OFF until user changes it
bm83_eq_set(bm83, 0)

_last_evt_print = 0.0
_last_meta_poll = time.monotonic()

while True:
    now = time.monotonic()

    evt = bm83_read_event(bm83, timeout=0.01)
    if evt:
        etype, op, status, data = evt

        # AVRCP metadata block: op=0x5D carries element attributes
        if op == 0x5D:
            meta = _parse_avrcp_metadata_block(data)
            if meta:
                nx_update_metadata(meta)

        # AVRCP playback-related notifications (0x1A) – good times to refresh
        if op == 0x1A:
            bm83_request_metadata(bm83)

        interesting = {0x00, 0x10, 0x1A, 0x1B, 0x20, 0x2D}
        if op in interesting or (now - _last_evt_print) > 1.0:
            print(
                f"[BM83 EVT] type={etype} op=0x{op:02X} status=0x{status:02X} "
                f"data={hexdump(data)}"
            )
            _last_evt_print = now

    # Periodic metadata polling while powered on (faster now)
    if _power_on and (now - _last_meta_poll) >= META_POLL_INTERVAL:
        bm83_request_metadata(bm83)
        _last_meta_poll = now

    # Live time (tTIME_CUR) updates
    _update_live_time(now)

    try:
        chunk = nextion.read(64)
    except Exception as e:  # pragma: no cover
        print("[NX] UART read error:", e)
        chunk = None

    if chunk:
        process_nextion_bytes(chunk)

    time.sleep(0.003)


# Self-tests (never run in normal operation)
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