# /code.py
# ===========================================================
# ESP32-S3 DevKitC-1 + BM83 + Nextion NX3224F028 + BLE HID Volume
# CircuitPython 10.x
#
# THIS REVISION: EQ FIX ONLY
# - Skip USER mode in EQ cycling
# - Sync "next EQ" to BM83's *reported* EQ mode (no backwards / wonky cycling)
# - Force EQ to OFF after BM83 power-on so it doesn't jump to BASS on boot
#
# Everything else (metadata, timing, BLE HID) left as-is.
# ===========================================================

import gc
from collections import deque
import time
import board
import busio

DEBUG = True


def dprint(*a):
    if DEBUG:
        print(*a)


NX_BAUD = 9600
BM83_BAUD = 115200

NX_TX, NX_RX = board.IO15, board.IO16
BM83_TX, BM83_RX = board.IO17, board.IO18

BLE_ENABLED = True
BLE_NAME = "AmpBench Remote"

TERM = b"\xFF\xFF\xFF"
TOKENS = {
    b"BT_POWER",
    b"BT_POWEROFF",
    b"BT_PAIR",
    b"BT_PLAY",
    b"BT_PREV",
    b"BT_NEXT",
    b"BT_VOLUP",
    b"BT_VOLDN",
}

EQ_OBJ_PAGE0 = "tEQ0"
EQ_OBJ_PAGE1 = "tEQ1"
NX_RUNTIME = {
    "title": "tTitle",
    "artist": "tArtist",
    "album": "tAlbum",
    "genre": "tGenre",
    "time_cur": "tTIME_CUR",
    "time": "tTime",
    "track_num": "tTrack_num",
    "total_tracks": "tTotalTracks",
}


def _sanitize_text(txt, max_len=48):
    if txt is None:
        return "—"
    out = []
    for ch in str(txt):
        o = ord(ch)
        out.append(ch if 32 <= o <= 126 else " ")
    s = "".join(out).replace('"', "'").strip()
    if not s:
        s = "—"
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _fmt_ms(ms):
    if ms is None:
        return "—"
    try:
        ms = int(ms)
    except Exception:
        return _sanitize_text(ms, max_len=16)
    if ms < 0:
        ms = 0
    total = ms // 1000
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


# ---------------- Nextion ----------------
class Nextion:
    def __init__(self, uart):
        self.uart = uart
        self._rx = bytearray()

        self.current_page = None
        self._last_sendme_at = 0.0
        self._sendme_period_s = 0.5

        self._txq = deque()
        self._last_tx_at = 0.0
        self._tx_interval_s = 0.035

        self._last_token = None
        self._last_token_at = 0.0

    def boot_sync(self, delay_s=0.8):
        time.sleep(delay_s)
        self._rx = bytearray()
        self._txq.clear()
        self.current_page = None
        self._last_sendme_at = 0.0
        self._last_tx_at = 0.0
        self.enqueue("bkcmd=3")
        self.enqueue("sendme")

    def enqueue(self, cmd):
        self._txq.append(cmd)

    def sendme_tick(self):
        now = time.monotonic()
        if (now - self._last_sendme_at) >= self._sendme_period_s:
            self._last_sendme_at = now
            self.enqueue("sendme")

    def tick(self):
        self.sendme_tick()

        now = time.monotonic()
        if not self._txq:
            return
        if (now - self._last_tx_at) < self._tx_interval_s:
            return

        cmd = self._txq.popleft()
        try:
            self.uart.write(cmd.encode("ascii", "replace") + TERM)
            self._last_tx_at = now
        except Exception as e:
            dprint("[NX] write err:", e)

    def _read_more(self):
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(256, n)) if n else None
        except Exception as e:
            dprint("[NX] read err:", e)
            return
        if chunk:
            self._rx.extend(chunk)

    def _pop_frame(self):
        i = self._rx.find(TERM)
        if i < 0:
            return None
        frame = bytes(self._rx[:i])
        self._rx = self._rx[i + 3 :]
        return frame

    @staticmethod
    def _is_token_frame(frame):
        f = frame.strip()
        if not f:
            return False
        for b in f:
            if 48 <= b <= 57:
                continue
            if 65 <= b <= 90:
                continue
            if b == 95:
                continue
            return False
        return f in TOKENS

    def read(self, max_tokens=6, debounce_s=0.10):
        tokens = []
        page_changed = False

        self._read_more()
        while True:
            frame = self._pop_frame()
            if frame is None:
                break

            if len(frame) >= 2 and frame[0] == 0x66:
                pageid = frame[1]
                if self.current_page != pageid:
                    self.current_page = pageid
                    page_changed = True
                continue

            if self._is_token_frame(frame):
                now = time.monotonic()
                if self._last_token == frame and (now - self._last_token_at) < debounce_s:
                    continue
                self._last_token = frame
                self._last_token_at = now
                tokens.append(frame)
                if len(tokens) >= max_tokens:
                    break

        return tokens, page_changed

    def set_text_active_page(self, obj, txt):
        safe = _sanitize_text(txt)
        self.enqueue('%s.txt="%s"' % (obj, safe))


# ---------------- BLE HID ----------------
class BleHid:
    def __init__(self, enabled, name):
        self.enabled = enabled
        self.name = name
        self._ble = None
        self._adv = None
        self._cc = None
        self._ready = False
        self._next_adv_at = 0.0

    def setup(self):
        if not self.enabled:
            return
        try:
            from adafruit_ble import BLERadio
            from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
            from adafruit_ble.services.standard.hid import HIDService
            from adafruit_hid.consumer_control import ConsumerControl

            self._ble = BLERadio()
            self._ble.name = self.name
            hid = HIDService()
            self._adv = ProvideServicesAdvertisement(hid)
            self._cc = ConsumerControl(hid.devices)
            self._ready = True
            print("[BLE] Ready:", self.name)
            self._start_adv(force=True)
        except Exception as e:
            print("[BLE] Disabled:", e)
            self._ready = False

    def _start_adv(self, force=False):
        if not self._ready or not self._ble or not self._adv:
            return
        if self._ble.connected:
            return
        try:
            if (not force) and getattr(self._ble, "advertising", False):
                return
        except Exception:
            pass
        now = time.monotonic()
        if (not force) and now < self._next_adv_at:
            return
        try:
            self._ble.start_advertising(self._adv)
            self._next_adv_at = now + 0.2
        except Exception as e:
            msg = str(e)
            if "Nimble" in msg or "memory" in msg.lower():
                self._next_adv_at = now + 10.0
                return
            self._next_adv_at = now + 5.0
            dprint("[BLE] adv err:", e)

    def tick(self):
        self._start_adv(force=False)

    def _send_ccc(self, code):
        if not self._ready or not self._ble or not self._cc:
            return
        if not self._ble.connected:
            return
        try:
            self._cc.send(code)
        except Exception as e:
            print("[BLE] send fail:", e)

    def volume(self, up):
        from adafruit_hid.consumer_control_code import ConsumerControlCode as CCC
        self._send_ccc(CCC.VOLUME_INCREMENT if up else CCC.VOLUME_DECREMENT)

    def mute(self):
        from adafruit_hid.consumer_control_code import ConsumerControlCode as CCC
        self._send_ccc(CCC.MUTE)


# ---------------- BM83 ----------------
class Bm83:
    OP_MMI_ACTION = 0x02
    OP_EVENT_FILTER = 0x03
    OP_MUSIC_CONTROL = 0x04
    OP_AVC_VENDOR_CMD = 0x0B
    OP_READ_BD_ADDR = 0x0F
    OP_BTM_UTILITY_FUNC = 0x13
    OP_EVENT_ACK = 0x14
    OP_EQ_MODE_SETTING = 0x1C
    OP_AVRCP_VENDOR_DEP_CMD = 0x4A

    EVT_BTM_STATUS = 0x01
    EVT_EQ_MODE_IND = 0x10
    EVT_AVC_VENDOR_RSP = 0x1A
    EVT_AVRCP_VENDOR_DEP_RSP = 0x5D

    MMI_POWER_ON_PRESS = 0x51
    MMI_POWER_ON_RELEASE = 0x52
    MMI_POWER_OFF_PRESS = 0x53
    MMI_POWER_OFF_RELEASE = 0x54
    MMI_ENTER_PAIRING = 0x5D

    MC_PLAY_PAUSE = 0x07
    MC_PREV = 0x0A

    # EQ cycle (USER removed)
    EQ_SEQ = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9)
    EQ_L = {
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
        # Some firmwares report USER as 0x0A; we won't cycle into it, but label it if seen.
        10: "USER",
        11: "USER",
    }

    CONNECTED_STATES = (0x06, 0x0B, 0x82, 0x64, 0x65, 0x66)

    def __init__(self, uart):
        self.uart = uart
        self._rx = bytearray()

        self.power_on = False

        # EQ FIX: track what BM83 says the current EQ mode is
        self.current_eq_mode = 0  # assume OFF until told otherwise

        self.connected = False
        self._last_connected_seen = 0.0
        self._disconnect_hold_s = 2.0

        self._next_playstatus_at = 0.0
        self._playstatus_period_s = 1.0

        self._next_attrs_at = 0.0
        self._attrs_throttle_s = 1.5
        self._last_attrs_req_at = 0.0

        self._gea_frag = bytearray()
        self._gea_expect_len = None

    @staticmethod
    def _checksum(hi, lo, body):
        return (-((hi + lo + sum(body)) & 0xFF)) & 0xFF

    def _frame(self, op, params=b""):
        body = bytes([op]) + params
        ln = len(body)
        hi, lo = (ln >> 8) & 0xFF, ln & 0xFF
        chk = self._checksum(hi, lo, body)
        return bytes([0xAA, hi, lo]) + body + bytes([chk])

    def send(self, op, params=b""):
        pkt = self._frame(op, params)
        dprint("[BM83 TX]", " ".join("%02X" % b for b in pkt))
        try:
            self.uart.write(pkt)
        except Exception as e:
            print("[BM83] write err:", e)

    def ack_event(self, event_op):
        if event_op == 0x00:
            return
        self.send(self.OP_EVENT_ACK, bytes([event_op & 0xFF]))

    def poll(self, max_read=768):
        out = []
        try:
            n = getattr(self.uart, "in_waiting", 0) or 0
            chunk = self.uart.read(min(max_read, n)) if n else None
        except Exception as e:
            dprint("[BM83] read err:", e)
            return out

        if chunk:
            self._rx.extend(chunk)

        while True:
            if len(self._rx) < 4:
                break
            sof = self._rx.find(b"\xAA")
            if sof < 0:
                self._rx.clear()
                break
            if sof > 0:
                self._rx = self._rx[sof:]
            if len(self._rx) < 4:
                break

            hi, lo = self._rx[1], self._rx[2]
            ln = (hi << 8) | lo
            total = 3 + ln + 1
            if len(self._rx) < total:
                break

            body = bytes(self._rx[3 : 3 + ln])
            chk = self._rx[3 + ln]
            if chk != self._checksum(hi, lo, body):
                self._rx = self._rx[1:]
                continue

            op = body[0]
            params = body[1:]
            dprint(
                "[BM83 EVT] op=0x%02X len=%d data=" % (op, len(params)),
                " ".join("%02X" % b for b in params),
            )
            out.append((op, params))
            self._rx = self._rx[total:]

        return out

    def init_link(self):
        self.send(self.OP_READ_BD_ADDR)
        self.send(self.OP_EVENT_FILTER, b"\x00\x00\x00\x00")
        self.send(self.OP_BTM_UTILITY_FUNC, b"\x03\x01")
        print("[BM83] Link initialized")

    # EQ helpers (EQ FIX)
    def set_eq(self, mode):
        self.send(self.OP_EQ_MODE_SETTING, bytes([mode & 0xFF, 0x00]))

    def set_eq_off(self):
        self.set_eq(0)
        self.current_eq_mode = 0

    def next_eq(self):
        """
        EQ FIX: choose next mode based on BM83's current reported mode,
        not a local counter that can drift.
        """
        cur = self.current_eq_mode
        try:
            i = self.EQ_SEQ.index(cur)
        except ValueError:
            i = 0  # if BM83 reports something odd (like USER), fall back gracefully
        nxt = self.EQ_SEQ[(i + 1) % len(self.EQ_SEQ)]
        self.set_eq(nxt)
        # Optimistically update; BM83 will also confirm via EQ_MODE_IND
        self.current_eq_mode = nxt
        return nxt

    def power_on_cmd(self):
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_PRESS]))
        time.sleep(0.2)
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_ON_RELEASE]))
        time.sleep(0.5)
        self.init_link()

        # EQ FIX: Force OFF at boot so it doesn't jump to BASS
        time.sleep(0.15)
        self.set_eq_off()

        self.power_on = True
        print("[POWER] ON (UART)")

    def power_off_cmd(self):
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_PRESS]))
        time.sleep(1.5)
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_POWER_OFF_RELEASE]))
        self.power_on = False
        self.connected = False
        print("[POWER] OFF (UART)")

    def power_toggle(self):
        self.power_off_cmd() if self.power_on else self.power_on_cmd()

    def pair(self):
        self.send(self.OP_MMI_ACTION, bytes([0x00, self.MMI_ENTER_PAIRING]))
        print("[PAIR] Enter pairing")

    def play_pause(self):
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PLAY_PAUSE]))
        print("[PLAY/PAUSE] toggled")

    def prev(self):
        self.send(self.OP_MUSIC_CONTROL, bytes([0x00, self.MC_PREV]))
        print("[PREV] triggered")

    def note_btm_state(self, state):
        now = time.monotonic()
        if state in self.CONNECTED_STATES:
            self._last_connected_seen = now
            if not self.connected:
                self.connected = True
                return "CONNECTED"
            return None
        if self.connected and (now - self._last_connected_seen) > self._disconnect_hold_s:
            self.connected = False
            return "DISCONNECTED"
        return None

    @staticmethod
    def _avc_payload(pdu, params):
        return bytes([pdu, 0x00]) + len(params).to_bytes(2, "big") + params

    def avrcp_get_play_status(self, db=0):
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x30, b""))

    def avrcp_register_notification(self, event_id, interval_s=0, db=0):
        params = bytes([event_id]) + int(interval_s).to_bytes(4, "big")
        self.send(self.OP_AVC_VENDOR_CMD, bytes([db]) + self._avc_payload(0x31, params))

    def avrcp_get_element_attributes(self, db=0):
        attr_ids = (1, 2, 3, 6, 4, 5, 7)
        p = bytes([len(attr_ids)])
        for a in attr_ids:
            p += int(a).to_bytes(4, "big")
        self.send(self.OP_AVRCP_VENDOR_DEP_CMD, bytes([db, 0x20]) + p)

    def schedule_attrs(self, delay_s=0.35):
        now = time.monotonic()
        if (now - self._last_attrs_req_at) < self._attrs_throttle_s:
            return
        t = now + delay_s
        if self._next_attrs_at == 0.0 or t < self._next_attrs_at:
            self._next_attrs_at = t

    def tick_avrcp(self):
        if not self.connected:
            return
        now = time.monotonic()
        if now >= self._next_playstatus_at:
            self.avrcp_get_play_status(0)
            self._next_playstatus_at = now + self._playstatus_period_s
        if self._next_attrs_at and now >= self._next_attrs_at:
            self._last_attrs_req_at = now
            self._next_attrs_at = 0.0
            self.avrcp_get_element_attributes(0)

    @staticmethod
    def parse_avc_vendor_rsp(params):
        if len(params) < 1 + 10:
            return None
        db = params[0]
        p = params[1:]
        pdu = p[6]
        pkt_type = p[7]
        plen = int.from_bytes(p[8:10], "big")
        if len(p) < 10 + plen:
            return None
        return db, pdu, pkt_type, p[10 : 10 + plen]

    def parse_gea_0x5d(self, params):
        if len(params) < 2:
            return None
        pdu_id = params[0]
        payload = params[2:]
        if pdu_id != 0x20 or len(payload) < 5:
            return None

        resp = payload[0]
        is_end = payload[1]
        attr_num = payload[2]
        total_len = int.from_bytes(payload[3:5], "big")
        part = payload[5:]

        if self._gea_expect_len is None:
            self._gea_expect_len = total_len
            self._gea_frag = bytearray()
        self._gea_frag.extend(part)

        if is_end != 0x01:
            return None

        full = bytes(self._gea_frag[: self._gea_expect_len])
        self._gea_frag = bytearray()
        self._gea_expect_len = None

        attrs = {}
        idx = 0
        for _ in range(attr_num):
            if idx + 8 > len(full):
                break
            aid = int.from_bytes(full[idx : idx + 4], "big")
            vlen = int.from_bytes(full[idx + 6 : idx + 8], "big")
            val = full[idx + 8 : idx + 8 + vlen]
            idx += 8 + vlen
            try:
                s = val.decode("utf-8", "replace").strip()
            except Exception:
                s = "".join(chr(b) if 32 <= b <= 126 else " " for b in val).strip()
            attrs[aid] = s
        return resp, attrs


# ---------------- Main ----------------
def main():
    gc.collect()

    nx_uart = busio.UART(NX_TX, NX_RX, baudrate=NX_BAUD, timeout=0.0, receiver_buffer_size=1024)
    bm_uart = busio.UART(BM83_TX, BM83_RX, baudrate=BM83_BAUD, timeout=0.0, receiver_buffer_size=8192)

    nx = Nextion(nx_uart)
    bm = Bm83(bm_uart)

    ble = BleHid(BLE_ENABLED, BLE_NAME)
    ble.setup()

    print("=== ESP32-S3 BM83 + Nextion + BLE HID (VOLUME ONLY) ===")

    nx.boot_sync(0.9)

    desired_eq = "OFF"
    desired_meta = {k: "—" for k in NX_RUNTIME.keys()}

    # Play-status based track-change detection
    last_pos_ms = None
    last_total_ms = None

    # iOS mute assist
    last_voldn_at = 0.0
    mute_window_s = 0.35

    def flush_page(pageid):
        if pageid == 0:
            nx.set_text_active_page(EQ_OBJ_PAGE0, desired_eq)
        elif pageid == 1:
            nx.set_text_active_page(EQ_OBJ_PAGE1, desired_eq)
            for k, obj in NX_RUNTIME.items():
                nx.set_text_active_page(obj, desired_meta.get(k, "—"))

    def maybe_track_changed(pos_ms, total_ms):
        nonlocal last_pos_ms, last_total_ms

        if pos_ms is None or total_ms is None:
            last_pos_ms = pos_ms
            last_total_ms = total_ms
            return False

        changed = False

        # total length change is a strong signal (common on track change)
        if last_total_ms is not None and total_ms > 0 and last_total_ms > 0 and total_ms != last_total_ms:
            changed = True

        # position reset (big drop and new pos near the start)
        if last_pos_ms is not None:
            if (pos_ms + 2500) < last_pos_ms and pos_ms < 3000:
                changed = True

        last_pos_ms = pos_ms
        last_total_ms = total_ms
        return changed

    last_gc = time.monotonic()

    while True:
        now = time.monotonic()

        if now - last_gc > 8.0:
            gc.collect()
            last_gc = now

        nx.tick()
        tokens, page_changed = nx.read()

        if page_changed and nx.current_page is not None:
            dprint("[NX] page=", nx.current_page)
            flush_page(nx.current_page)

        ble.tick()

        bm.tick_avrcp()
        for op, params in bm.poll():
            bm.ack_event(op)

            if op == bm.EVT_BTM_STATUS and params:
                state = params[0]
                print("[BTM_Status] state=0x%02X" % state)
                change = bm.note_btm_state(state)
                if change == "CONNECTED":
                    print("[BTM] Connected -> register notifications + request metadata")
                    bm.avrcp_register_notification(0x01, interval_s=1)  # play status
                    bm.avrcp_register_notification(0x02, interval_s=0)  # track changed
                    bm.avrcp_register_notification(0x05, interval_s=1)  # pos changed
                    bm._next_playstatus_at = 0.0
                    bm.schedule_attrs(0.8)

            elif op == bm.EVT_EQ_MODE_IND and params:
                mode = params[0]

                # EQ FIX: keep our EQ state synced to BM83
                bm.current_eq_mode = mode if mode is not None else bm.current_eq_mode

                desired_eq = bm.EQ_L.get(mode, "OFF")
                dprint("[EQ_IND] mode=%d label=%s" % (mode, desired_eq))
                if nx.current_page is not None:
                    flush_page(nx.current_page)

            elif op == bm.EVT_AVC_VENDOR_RSP:
                parsed = bm.parse_avc_vendor_rsp(params)
                if not parsed:
                    continue
                _db, pdu, pkt_type, avp = parsed
                if pkt_type != 0x00:
                    continue

                if pdu == 0x30 and len(avp) >= 9:
                    total_ms = int.from_bytes(avp[0:4], "big")
                    pos_ms = int.from_bytes(avp[4:8], "big")

                    desired_meta["time_cur"] = _fmt_ms(pos_ms)
                    if total_ms > 0:
                        desired_meta["time"] = _fmt_ms(total_ms)

                    if maybe_track_changed(pos_ms, total_ms):
                        dprint("[TRACK] inferred change -> request metadata")
                        bm.schedule_attrs(0.25)

                    if nx.current_page == 1:
                        flush_page(1)

                elif pdu == 0x31 and len(avp) >= 1:
                    # Keep this (some stacks do send TrackChanged reliably)
                    event_id = avp[0]
                    if event_id == 0x02:
                        dprint("[AVRCP] TrackChanged -> request metadata")
                        bm.schedule_attrs(0.25)
                        # Re-register so future notifications keep coming
                        bm.avrcp_register_notification(0x02, interval_s=0)
                    elif event_id == 0x05 and len(avp) >= 5:
                        pos = int.from_bytes(avp[1:5], "big")
                        desired_meta["time_cur"] = _fmt_ms(pos)
                        if nx.current_page == 1:
                            flush_page(1)

            elif op == bm.EVT_AVRCP_VENDOR_DEP_RSP:
                gea = bm.parse_gea_0x5d(params)
                if gea:
                    _resp, attrs = gea
                    print("[META] GetElementAttributes received:", sorted(attrs.keys()))

                    if 1 in attrs:
                        desired_meta["title"] = _sanitize_text(attrs[1])
                    if 2 in attrs:
                        desired_meta["artist"] = _sanitize_text(attrs[2])
                    if 3 in attrs:
                        desired_meta["album"] = _sanitize_text(attrs[3])
                    if 6 in attrs:
                        desired_meta["genre"] = _sanitize_text(attrs[6])
                    if 4 in attrs:
                        desired_meta["track_num"] = _sanitize_text(attrs[4], max_len=8)
                    if 5 in attrs:
                        desired_meta["total_tracks"] = _sanitize_text(attrs[5], max_len=8)
                    if 7 in attrs:
                        desired_meta["time"] = _fmt_ms(attrs[7])

                    if nx.current_page == 1:
                        flush_page(1)

        for tok in tokens:
            dprint("[NX] Token:", tok)

            if tok == b"BT_POWER":
                bm.power_toggle()
            elif tok == b"BT_PAIR":
                bm.pair()
            elif tok == b"BT_PLAY":
                bm.play_pause()
            elif tok == b"BT_PREV":
                bm.prev()
            elif tok == b"BT_NEXT":
                mode = bm.next_eq()
                desired_eq = bm.EQ_L.get(mode, "OFF")
                print("[EQ] set to", desired_eq)
                if nx.current_page is not None:
                    flush_page(nx.current_page)
            elif tok == b"BT_VOLUP":
                ble.volume(True)
            elif tok == b"BT_VOLDN":
                if (now - last_voldn_at) <= mute_window_s:
                    ble.mute()
                    last_voldn_at = 0.0
                else:
                    ble.volume(False)
                    last_voldn_at = now

        time.sleep(0.005)

if __name__ == "__main__":
    main()
