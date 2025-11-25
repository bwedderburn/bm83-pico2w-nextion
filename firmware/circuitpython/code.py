# code.py — Pico 2 W + CircuitPython
# BM83 Host UART (UART0) on GP12/GP13; Nextion (UART1) on GP8/GP9.

import time
import board
import busio

try:
    import digitalio
except Exception:
    digitalio = None

BM83_TX_PIN, BM83_RX_PIN, BM83_BAUD = board.GP12, board.GP13, 115200
NX_TX_PIN,  NX_RX_PIN,  NX_BAUD    = board.GP8,  board.GP9,   9600
TX_IND_PIN = getattr(board, "GP22", None)

ENABLE_ABS_VOL = False
ABS_VOL_STEP   = 8
_abs_vol       = 64

TOKENS = [b"BT_POWER", b"BT_PAIR", b"BT_PLAY", b"BT_NEXT", b"BT_PREV", b"BT_VOLUP", b"BT_VOLDN"]

def hexdump(buf): return " ".join(f"{b:02X}" for b in (buf or b""))

bm83 = None
_power_on = None

def _chk(hi, lo, p):
    s = (hi + lo + sum(p)) & 0xFF
    return ((~s + 1) & 0xFF)

def bm83_frame(opcode, params=b"\x00"):
    plen = 1 + len(params)
    hi, lo = (plen >> 8) & 0xFF, plen & 0xFF
    payload = bytes([opcode]) + bytes(params)
    return bytes([0xAA, hi, lo]) + payload + bytes([_chk(hi, lo, payload)])

def bm83_read_event(uart, timeout=0.25):
    # Remove or update this line:
    # If needed:
    _power_on = True  # or whatever value it should have
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        b = uart.read(1)
        if not b:
            continue
        if b[0] == 0x00:  # optional wake
            continue
        if b[0] != 0xAA:
            continue
        hdr = uart.read(3)
        if not hdr or len(hdr) < 3:
            continue
        plen = (hdr[0] << 8) | hdr[1]
        ev   = hdr[2]
        params = uart.read(plen - 1) if plen > 1 else b""
        if params is None:
            params = b""
        chk = uart.read(1)
        if not chk or len(chk) < 1:
            continue
        if ((hdr[0] + hdr[1] + ev + sum(params) + chk[0]) & 0xFF) == 0:
            if ev == 0x01 and len(params) >= 1:
                if params[0] == 0x02: _power_on = True
                elif params[0] == 0x00: _power_on = False
            return ev, bytes(params)
    return None

def bm83_send(u, op, params=b"\x00", expect_ack=True, label=""):
    u.write(bm83_frame(op, params))
    ok = not expect_ack
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.35:
        evt = bm83_read_event(u, timeout=0.05)
        if not evt:
            continue
        ev, pl = evt
        if ev == 0x00 and len(pl) >= 2 and pl[0] == op:
            ok = (pl[1] == 0x00)
            print(f"[ACK {label}] op=0x{pl[0]:02X} status=0x{pl[1]:02X}")
        else:
            print(f"[EVT {label}] 0x{ev:02X}  {hexdump(pl)}")
    return ok

OP_EVENT_MASK        = 0x03
OP_MUSIC_CONTROL     = 0x04
OP_SET_OVERALL_GAIN  = 0x23
OP_BTM_UTILITY_FUNC  = 0x13
OP_READ_BD_ADDR      = 0x0F
OP_MMI_ACTION        = 0x02

MC_PLAY_PAUSE = 0x07
MC_NEXT       = 0x09
MC_PREV       = 0x0A

MMI_POWER_ON_PRESS    = 0x51
MMI_POWER_ON_RELEASE  = 0x52
MMI_POWER_OFF_PRESS   = 0x53
MMI_POWER_OFF_RELEASE = 0x54
MMI_ENTER_PAIRING     = 0x5D

def bm83_unmask_all(u):           bm83_send(u, OP_EVENT_MASK, b"\x00\x00\x00\x00", label="EvtMask")
def bm83_connectable(u, on=True): bm83_send(u, OP_BTM_UTILITY_FUNC, bytes([0x03, 0x01 if on else 0x00]), label="Connectable")
def bm83_play(u):                 bm83_send(u, OP_MUSIC_CONTROL, bytes([0x00, MC_PLAY_PAUSE]), label="Play/Pause")
def bm83_next(u):                 bm83_send(u, OP_MUSIC_CONTROL, bytes([0x00, MC_NEXT]),       label="Next")
def bm83_prev(u):                 bm83_send(u, OP_MUSIC_CONTROL, bytes([0x00, MC_PREV]),       label="Prev")

def bm83_set_abs_vol(u, level):
    lvl = max(0, min(127, int(level)))
    bm83_send(u, OP_SET_OVERALL_GAIN, bytes([0x00, 0x01, 0x04, lvl, 0x00, 0x00]), label=f"AbsVol={lvl}")

def bm83_power_on(u):
    print("[POWER] ON")
    ok1 = bm83_send(u, OP_MMI_ACTION, bytes([0x00, MMI_POWER_ON_PRESS]),   label="PwrOn-press")
    time.sleep(0.20)
    ok2 = bm83_send(u, OP_MMI_ACTION, bytes([0x00, MMI_POWER_ON_RELEASE]), label="PwrOn-release")
    return ok1 and ok2

def bm83_power_off(u):
    print("[POWER] OFF")
    ok1 = bm83_send(u, OP_MMI_ACTION, bytes([0x00, MMI_POWER_OFF_PRESS]),   label="PwrOff-press")
    time.sleep(1.50)
    ok2 = bm83_send(u, OP_MMI_ACTION, bytes([0x00, MMI_POWER_OFF_RELEASE]), label="PwrOff-release")
    return ok1 and ok2

def bm83_power_toggle(u):
    global _power_on
    if _power_on is True:
        if not bm83_power_off(u): bm83_power_on(u); return
    if _power_on is False:
        if not bm83_power_on(u): bm83_power_off(u); return
    if not bm83_power_on(u): bm83_power_off(u)

nextion = busio.UART(NX_TX_PIN, NX_RX_PIN, baudrate=NX_BAUD, timeout=0.05, receiver_buffer_size=1024)
bm83    = busio.UART(BM83_TX_PIN, BM83_RX_PIN, baudrate=BM83_BAUD, timeout=0.05, receiver_buffer_size=4096)

tx_ind = None
if TX_IND_PIN is not None and digitalio is not None:
    try:
        tx_ind = digitalio.DigitalInOut(TX_IND_PIN)
        tx_ind.switch_to_input(pull=digitalio.Pull.UP)
    except Exception as e:
        print("TX_IND not configured:", e)

bm83_send(bm83, OP_READ_BD_ADDR, b"\x00", label="Probe")
bm83_unmask_all(bm83)
bm83_connectable(bm83, True)
print(f"[BM83] Host UART online @ {BM83_BAUD} | Pins TX={BM83_TX_PIN} RX={BM83_RX_PIN}")
print(f"Nextion UART @ {NX_BAUD} | Pins TX={NX_TX_PIN} RX={NX_RX_PIN}")
print("Listening for:", [t.decode() for t in TOKENS])
print("Ready.")

TERM = b"\xFF\xFF\xFF"
buf  = bytearray()
start = 0
MAXBUF = 512
_last_evt_drain = 0.0
_last_txind = None

def handle_token(tok: bytes):
    global _abs_vol
    if tok == b"BT_POWER":
        bm83_power_toggle(bm83); return
    if tok == b"BT_PAIR":
        bm83_send(bm83, OP_MMI_ACTION, bytes([0x00, MMI_ENTER_PAIRING]), label="Pairing"); return
    if tok == b"BT_PLAY":
        bm83_play(bm83); return
    if tok == b"BT_NEXT":
        bm83_next(bm83); return
    if tok == b"BT_PREV":
        bm83_prev(bm83); return
    if tok in (b"BT_VOLUP", b"BT_VOLDN"):
        if ENABLE_ABS_VOL:
            _abs_vol = max(0, min(127, _abs_vol + (ABS_VOL_STEP if tok == b"BT_VOLUP" else -ABS_VOL_STEP)))
            bm83_set_abs_vol(bm83, _abs_vol)
        else:
            print("Note: AbsVol disabled; ignoring VOL tokens.")
        return

while True:
    now = time.monotonic()
    if now - _last_evt_drain > 0.05:
        evt = bm83_read_event(bm83, timeout=0.001)
        while evt:
            ev, pl = evt
            print(f"[EVT] 0x{ev:02X}  {hexdump(pl)}")
            evt = bm83_read_event(bm83, timeout=0.001)
        _last_evt_drain = now

    if tx_ind is not None:
        state = tx_ind.value
        if _last_txind is None or state != _last_txind:
            print("[TX_IND]", int(state))
            _last_txind = state

    data = nextion.read(64)
    if data:
        buf.extend(data)
        while True:
            i = buf.find(TERM, start)
            if i == -1:
                if start > 0 and (start > len(buf)//2 or len(buf) > MAXBUF):
                    buf = buf[start:]; start = 0
                break
            frame = bytes(buf[start:i])
            start = i + 3
            msg = frame.strip()
            if not msg:
                continue
            acted = False
            if msg in TOKENS:
                handle_token(msg); acted = True
                try: print("Action:", msg.decode("ascii"))
                except: print("Action: (binary)")
            else:
                for t in TOKENS:
                    if t in msg:
                        handle_token(t); acted = True
                        print("Action:", t.decode("ascii"))
                        break
            if not acted:
                try: print("Unknown Nextion msg:", msg.decode("ascii"))
                except: print("Unknown Nextion msg (binary)")
        if len(buf) > 4 * MAXBUF:
            buf = buf[-MAXBUF:]; start = 0

    time.sleep(0.005)
