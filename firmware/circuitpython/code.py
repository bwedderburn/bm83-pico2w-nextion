import time
import board
import busio
import digitalio
from adafruit_debouncer import Debouncer

# UART setup for BM83 (Bluetooth module)
uart_bm83 = busio.UART(board.TX, board.RX, baudrate=115200, timeout=0.1)

# UART setup for Nextion display
uart_nextion = busio.UART(board.TX1, board.RX1, baudrate=115200, timeout=0.1)

# GPIO setup for buttons
button_play_pin = digitalio.DigitalInOut(board.D5)
button_play_pin.direction = digitalio.Direction.INPUT
button_play_pin.pull = digitalio.Pull.UP
button_play = Debouncer(button_play_pin)

button_next_pin = digitalio.DigitalInOut(board.D6)
button_next_pin.direction = digitalio.Direction.INPUT
button_next_pin.pull = digitalio.Pull.UP
button_next = Debouncer(button_next_pin)

button_prev_pin = digitalio.DigitalInOut(board.D7)
button_prev_pin.direction = digitalio.Direction.INPUT
button_prev_pin.pull = digitalio.Pull.UP
button_prev = Debouncer(button_prev_pin)

button_vol_up_pin = digitalio.DigitalInOut(board.D8)
button_vol_up_pin.direction = digitalio.Direction.INPUT
button_vol_up_pin.pull = digitalio.Pull.UP
button_vol_up = Debouncer(button_vol_up_pin)

button_vol_down_pin = digitalio.DigitalInOut(board.D9)
button_vol_down_pin.direction = digitalio.Direction.INPUT
button_vol_down_pin.pull = digitalio.Pull.UP
button_vol_down = Debouncer(button_vol_down_pin)

# BM83 command opcodes
CMD_MMI_ACTION = 0x02
CMD_DEVICE_STATE = 0x03
CMD_MUSIC_CONTROL = 0x04
CMD_VOLUME_UP = 0x05
CMD_VOLUME_DOWN = 0x06

# MMI Action parameters
MMI_POWER_ON = 0x51
MMI_POWER_OFF = 0x52
MMI_ENTER_PAIRING = 0x5C
MMI_ACCEPT_CALL = 0x04
MMI_REJECT_CALL = 0x05
MMI_END_CALL = 0x06

# Music Control parameters
MUSIC_PLAY = 0x00
MUSIC_PAUSE = 0x01
MUSIC_NEXT = 0x02
MUSIC_PREVIOUS = 0x03

# State variables
current_state = {
    "connected": False,
    "playing": False,
    "volume": 50,
    "track_info": {"title": "", "artist": "", "album": ""}
}

def send_nextion_command(cmd: str):
    """Send a command to the Nextion display."""
    uart_nextion.write(cmd.encode() + b'\xff\xff\xff')

def update_nextion_display():
    """Update the Nextion display with current state."""
    # Update connection status
    if current_state["connected"]:
        send_nextion_command('t0.txt="Connected"')
        send_nextion_command('t0.pco=GREEN')
    else:
        send_nextion_command('t0.txt="Disconnected"')
        send_nextion_command('t0.pco=RED')
    
    # Update play/pause status
    if current_state["playing"]:
        send_nextion_command('t1.txt="Playing"')
    else:
        send_nextion_command('t1.txt="Paused"')
    
    # Update volume
    send_nextion_command(f't2.txt="Volume: {current_state["volume"]}"')
    
    # Update track info
    track = current_state["track_info"]
    send_nextion_command(f't3.txt="{track["title"]}"')
    send_nextion_command(f't4.txt="{track["artist"]}"')
    send_nextion_command(f't5.txt="{track["album"]}"')

def parse_nextion_response():
    """Parse responses from the Nextion display."""
    if uart_nextion.in_waiting:
        data = uart_nextion.read(uart_nextion.in_waiting)
        if data:
            print(f"Nextion: {data.hex()}")
            # Handle button presses from Nextion
            if len(data) >= 3 and data[0] == 0x65:
                page_id = data[1]
                component_id = data[2]
                event_type = data[3] if len(data) > 3 else 0
                
                if event_type == 0x01:  # Touch press event
                    handle_nextion_button(page_id, component_id)

def handle_nextion_button(page_id: int, component_id: int):
    """Handle button presses from the Nextion display."""
    if page_id == 0:  # Main page
        if component_id == 1:  # Play/Pause button
            send_bm83_music_control(MUSIC_PLAY if not current_state["playing"] else MUSIC_PAUSE)
        elif component_id == 2:  # Next button
            send_bm83_music_control(MUSIC_NEXT)
        elif component_id == 3:  # Previous button
            send_bm83_music_control(MUSIC_PREVIOUS)
        elif component_id == 4:  # Volume up button
            send_bm83_volume_up()
        elif component_id == 5:  # Volume down button
            send_bm83_volume_down()

def send_bm83_command(opcode: int, payload: bytes = b""):
    """Send a command to the BM83 module."""
    frame = bm83_frame(opcode, payload)
    uart_bm83.write(frame)
    print(f"Sent to BM83: {frame.hex()}")

def send_bm83_mmi_action(action: int):
    """Send an MMI action command to the BM83."""
    payload = bytes([0x00, action])
    send_bm83_command(CMD_MMI_ACTION, payload)

def send_bm83_music_control(control: int):
    """Send a music control command to the BM83."""
    payload = bytes([0x00, control])
    send_bm83_command(CMD_MUSIC_CONTROL, payload)

def send_bm83_volume_up():
    """Send a volume up command to the BM83."""
    send_bm83_command(CMD_VOLUME_UP, bytes([0x00, 0x01]))

def send_bm83_volume_down():
    """Send a volume down command to the BM83."""
    send_bm83_command(CMD_VOLUME_DOWN, bytes([0x00, 0x01]))

def send_bm83_device_state_query():
    """Query the device state from the BM83."""
    send_bm83_command(CMD_DEVICE_STATE, bytes([0x00]))

def parse_bm83_response():
    """Parse responses from the BM83 module."""
    if uart_bm83.in_waiting:
        data = uart_bm83.read(uart_bm83.in_waiting)
        if data:
            print(f"BM83: {data.hex()}")
            # Parse BM83 frames
            i = 0
            while i < len(data):
                if data[i] == 0xAA and i + 3 <= len(data):
                    len_hi = data[i + 1]
                    len_lo = data[i + 2]
                    frame_len = (len_hi << 8) | len_lo
                    total_len = 3 + frame_len + 1  # Header + body + checksum
                    
                    if i + total_len <= len(data):
                        frame = data[i:i + total_len]
                        if verify_bm83_checksum(frame):
                            handle_bm83_event(frame)
                        i += total_len
                    else:
                        break
                else:
                    i += 1

def verify_bm83_checksum(frame: bytes) -> bool:
    """Verify the checksum of a BM83 frame."""
    if len(frame) < 5:
        return False
    
    len_hi = frame[1]
    len_lo = frame[2]
    frame_len = (len_hi << 8) | len_lo
    
    if len(frame) != 3 + frame_len + 1:
        return False
    
    body = frame[3:-1]
    received_checksum = frame[-1]
    
    s = sum(body) & 0xFF
    calculated_checksum = ((~s + 1) & 0xFF)
    
    return received_checksum == calculated_checksum

def handle_bm83_event(frame: bytes):
    """Handle events from the BM83 module."""
    opcode = frame[3]
    params = frame[4:-1]
    
    if opcode == 0x00:  # ACK
        print("ACK received")
    elif opcode == 0x01:  # Device state
        if len(params) >= 2:
            state = params[1]
            current_state["connected"] = (state & 0x01) != 0
            update_nextion_display()
    elif opcode == 0x1A:  # Music control status
        if len(params) >= 2:
            status = params[1]
            current_state["playing"] = (status == 0x00)
            update_nextion_display()
    elif opcode == 0x1B:  # Volume level
        if len(params) >= 2:
            current_state["volume"] = params[1]
            update_nextion_display()
    elif opcode == 0x26:  # BTM track changed
        parse_track_info(params)
        update_nextion_display()

def parse_track_info(params: bytes):
    """Parse track information from BM83 event."""
    try:
        # Track info format varies by implementation
        # This is a simplified parser
        text = params.decode('utf-8', errors='ignore')
        parts = text.split('\x00')
        
        if len(parts) >= 1:
            current_state["track_info"]["title"] = parts[0]
        if len(parts) >= 2:
            current_state["track_info"]["artist"] = parts[1]
        if len(parts) >= 3:
            current_state["track_info"]["album"] = parts[2]
    except:
        pass

def bm83_frame(opcode: int, payload: bytes = b"") -> bytes:
    """Build a BM83 UART frame.

    Checksum is the 2's complement of (opcode + params).
    """
    plen = 1 + len(payload)
    hi = (plen >> 8) & 0xFF
    lo = plen & 0xFF
    body = bytes([opcode]) + payload
    s = sum(body) & 0xFF
    chk = ((~s + 1) & 0xFF)
    return bytes([0xAA, hi, lo]) + body + bytes([chk])

def handle_physical_buttons():
    """Handle physical button presses."""
    button_play.update()
    button_next.update()
    button_prev.update()
    button_vol_up.update()
    button_vol_down.update()
    
    if button_play.fell:
        send_bm83_music_control(MUSIC_PLAY if not current_state["playing"] else MUSIC_PAUSE)
    
    if button_next.fell:
        send_bm83_music_control(MUSIC_NEXT)
    
    if button_prev.fell:
        send_bm83_music_control(MUSIC_PREVIOUS)
    
    if button_vol_up.fell:
        send_bm83_volume_up()
    
    if button_vol_down.fell:
        send_bm83_volume_down()

# Main loop
print("Starting BM83 + ESP32-S3 + Nextion controller...")

# Initialize BM83
time.sleep(1)
send_bm83_mmi_action(MMI_POWER_ON)
time.sleep(0.5)
send_bm83_device_state_query()

# Initialize Nextion display
time.sleep(0.5)
update_nextion_display()

last_state_query = time.monotonic()
STATE_QUERY_INTERVAL = 5.0  # Query state every 5 seconds

while True:
    # Handle physical buttons
    handle_physical_buttons()
    
    # Parse BM83 responses
    parse_bm83_response()
    
    # Parse Nextion responses
    parse_nextion_response()
    
    # Periodic state query
    if time.monotonic() - last_state_query > STATE_QUERY_INTERVAL:
        send_bm83_device_state_query()
        last_state_query = time.monotonic()
    
    time.sleep(0.01)  # Small delay to prevent busy loop
