#!/usr/bin/env python3
"""
BM83 module controller

This module provides an interface for communicating with BM83 Bluetooth audio modules.
It handles UART communication, command framing, and event parsing.

Configuration:
- UART baudrate: 115200
- Data bits: 8
- Parity: None
- Stop bits: 1

Author: Your Name
Date: 2024
"""

import time
import board
import busio
import digitalio
from collections import namedtuple

# BM83 UART Configuration
UART_BAUDRATE = 115200
UART_TIMEOUT = 1.0

# BM83 Command/Event Constants
CMD_HEADER = 0xAA
EVT_HEADER = 0xAA

# Command Opcodes
CMD_MAKE_CALL = 0x00
CMD_MAKE_EXTENSION_CALL = 0x01
CMD_MMI_ACTION = 0x02
CMD_EVENT_ACK = 0x04
CMD_MUSIC_CONTROL = 0x05
CMD_CHANGE_DEVICE_NAME = 0x06
CMD_CHANGE_PIN_CODE = 0x07
CMD_BTM_PARAMETER_SETTING = 0x08
CMD_READ_BTM_VERSION = 0x09
CMD_GET_PB_BY_AT_CMD = 0x0A
CMD_VENDOR_AT_COMMAND = 0x0B
CMD_AVRCP_SPEC_CMD = 0x0C
CMD_AVRCP_GROUP_NAVIGATION = 0x0D
CMD_READ_LINK_STATUS = 0x0E
CMD_READ_PAIRED_DEVICE_RECORD = 0x0F
CMD_READ_LOCAL_BD_ADDRESS = 0x10
CMD_READ_LOCAL_DEVICE_NAME = 0x11
CMD_SET_ACCESS_PB_METHOD = 0x12
CMD_SEND_SPP_DATA = 0x13
CMD_BTM_UTILITY_FUNCTION = 0x14
CMD_EVENT_MASK_SETTING = 0x15
CMD_SEND_BTM_POWER_OFF = 0x16
CMD_STANDBY_MODE_CONTROL = 0x17
CMD_MCU_STATUS_INDICATION = 0x18
CMD_VOICE_PROMPT_CMD = 0x19
CMD_SET_OVERALL_GAIN = 0x1A
CMD_READ_BTM_LINK_MODE = 0x1B
CMD_CONFIGURE_VENDOR_PARAM = 0x1C
CMD_READ_VENDOR_EEPROM = 0x1D
CMD_CODEC_CAPABILITY = 0x1E
CMD_PBAPC_READ_PB = 0x1F
CMD_READ_BTM_BATTERY_CHARGE_STATUS = 0x29
CMD_MCU_UPDATE_BATTERY_LEVEL = 0x2A
CMD_READ_BTM_SETTING = 0x2B
CMD_REPORT_BTM_INITIAL_STATUS = 0x2E
CMD_SET_BTM_TX_POWER = 0x30
CMD_READ_BTM_TX_POWER = 0x31
CMD_LE_ANCS_SERVICE = 0x40
CMD_LE_SIGNALING = 0x41
CMD_GATT_GENERIC = 0x42
CMD_DFU = 0x47
CMD_RESET_EEPROM_SETTING = 0x1E8
CMD_SET_AUDIO_BUFFER = 0x1EA
CMD_SET_UART_BAUD_RATE = 0x1EC
CMD_READ_TWS_LOCAL_DEVICE_INFO = 0x2C

# Event Opcodes
EVT_COMMAND_ACK = 0x00
EVT_BTM_STATUS = 0x01
EVT_CALL_STATUS = 0x02
EVT_CALLER_ID = 0x03
EVT_SMS_RECEIVED_IND = 0x04
EVT_MISSED_CALL_IND = 0x05
EVT_PHONE_MAX_BATTERY_LEVEL = 0x06
EVT_PHONE_BATTERY_LEVEL = 0x07
EVT_PHONE_ROAMING_STATUS = 0x08
EVT_PHONE_MAX_SIGNAL_STRENGTH = 0x09
EVT_PHONE_SIGNAL_STRENGTH = 0x0A
EVT_PHONE_SERVICE_STATUS = 0x0B
EVT_BTM_BATTERY_LEVEL = 0x0C
EVT_BTM_CHARGING_STATUS = 0x0D
EVT_RESET_TO_DEFAULT = 0x0E
EVT_REPORT_HF_GAIN_LEVEL = 0x0F
EVT_EQ_MODE_INDICATION = 0x10
EVT_PBAP_MISSED_CALL_HISTORY = 0x11
EVT_PBAP_RECEIVED_CALL_HISTORY = 0x12
EVT_PBAP_DIALED_CALL_HISTORY = 0x13
EVT_PBAP_COMBINE_CALL_HISTORY = 0x14
EVT_PHONE_BOOK_INFO = 0x15
EVT_PHONE_BOOK_CONTACT = 0x16
EVT_READ_LINKED_DEVICE_INFO = 0x17
EVT_READ_BTM_VERSION = 0x18
EVT_CALL_LIST_REPORT = 0x19
EVT_AVRCP_SPEC_RSP = 0x1A
EVT_BTM_UTILITY_REQ = 0x1B
EVT_VENDOR_AT_CMD_RSP = 0x1C
EVT_READ_LINK_STATUS = 0x1D
EVT_READ_PAIRED_DEVICE_RECORD = 0x1E
EVT_READ_LOCAL_BD_ADDRESS = 0x1F
EVT_READ_LOCAL_DEVICE_NAME = 0x20
EVT_REPORT_SPP_DATA = 0x21
EVT_REPORT_LINK_BACK_STATUS = 0x22
EVT_RINGTONE_FINISH_INDICATE = 0x23
EVT_USER_CONFIRM_SSP_REQ = 0x24
EVT_REPORT_AVRCP_VOL_CTRL = 0x26
EVT_REPORT_INPUT_SIGNAL_LEVEL = 0x27
EVT_REPORT_iAP_INFO = 0x28
EVT_REPORT_AVRCP_ABS_VOL_CTRL = 0x29
EVT_REPORT_VOICE_PROMPT_STATUS = 0x2A
EVT_REPORT_MAP_DATA = 0x2B
EVT_SECURITY_BONDING_RES = 0x2C
EVT_REPORT_TYPE_CODEC = 0x2D
EVT_REPORT_TYPE_BTM_SETTING = 0x2E
EVT_REPORT_MCU_UPDATE_REPLY = 0x2F
EVT_REPORT_BTM_INITIAL_STATUS = 0x30
EVT_REPORT_LE_EVENT = 0x31
EVT_REPORT_nSPK_VENDOR_EVENT = 0x32
EVT_REPORT_nSPK_LINK_STATUS = 0x33
EVT_REPORT_nSPK_AUDIO_SETTING = 0x34
EVT_REPORT_AVRCP_MEDIA_STATUS = 0x35
EVT_REPORT_nSPK_CHANNEL_SETTING = 0x36
EVT_LE_ANCS_SERVICE_EVENT = 0x40
EVT_LE_GATT_EVENT = 0x41
EVT_REPORT_CUSTOMER_GATT_ATTRIBUTE_DATA = 0x42
EVT_REPORT_BUTTON_ACTION_RESPONSE = 0x43
EVT_REPORT_TWS_RX_VENDOR_CMD = 0x44
EVT_REPORT_TWS_LOCAL_DEVICE_STATUS = 0x45
EVT_REPORT_TWS_VAD_DATA = 0x46
EVT_DFU_EVENT = 0x47
EVT_REPORT_TWS_EAR_BUD_POSITION = 0x48

# MMI Actions
MMI_ADD_REMOVE_SCO_LINK = 0x01
MMI_FORCE_END_CALL = 0x02
MMI_ACCEPT_CALL = 0x04
MMI_REJECT_CALL = 0x05
MMI_1_CALL_TRANSFER = 0x06
MMI_2_CALL_HOLD_ACCEPT_HELD = 0x07
MMI_3_CALL_HOLD_ACCEPT_HELD = 0x08
MMI_VOICE_DIAL = 0x09
MMI_LAST_NUMBER_REDIAL = 0x0A
MMI_ACTIVE_CALL_HOLD_ACCEPT_HELD = 0x0B
MMI_VOICE_TRANSFER = 0x0C
MMI_QUERY_CALL_LIST_INFO = 0x0D
MMI_THREE_WAY_CALL = 0x0E
MMI_RELEASE_CALL = 0x0F
MMI_ACCEPT_WAITING_HOLD_CALL_RLS_ACTIVE_CALL = 0x10
MMI_TOGGLE_MIC_MUTE = 0x40
MMI_DISABLE_MIC = 0x41
MMI_ENABLE_MIC = 0x42
MMI_DISCONNECT_HF = 0x50
MMI_INCREASE_MIC_GAIN = 0x60
MMI_DECREASE_MIC_GAIN = 0x61
MMI_SWITCH_PRIMARY_SECONDARY_HF = 0x62
MMI_INCREASE_SPEAKER_GAIN = 0x63
MMI_DECREASE_SPEAKER_GAIN = 0x64
MMI_NEXT_AUDIO_EFFECT_MODE = 0x70
MMI_PREVIOUS_AUDIO_EFFECT_MODE = 0x71
MMI_IND_BATTERY_STATUS = 0x80
MMI_IND_USER_ACTIVE = 0x81
MMI_TOGGLE_BTM_POWER = 0x90
MMI_POWER_ON_BTM = 0x91
MMI_POWER_OFF_BTM = 0x92
MMI_ACCEPT_DFU = 0xA0
MMI_REJECT_DFU = 0xA1
MMI_DISCOVERABLE = 0xB0
MMI_TOGGLE_DISCOVERABLE = 0xB1
MMI_NON_DISCOVERABLE = 0xB2
MMI_ENTER_PAIRING_MODE = 0xC0
MMI_POWER_ON_BUTTON_PRESS = 0xC1
MMI_POWER_ON_BUTTON_RELEASE = 0xC2
MMI_SWITCH_AUDIO_OUTPUT = 0xD0
MMI_DISCONNECT_A2DP = 0xD1
MMI_NEXT_SONG = 0xE0
MMI_PREVIOUS_SONG = 0xE1
MMI_PLAY_PAUSE = 0xE2
MMI_FAST_FORWARD_PRESS = 0xE3
MMI_FAST_FORWARD_RELEASE = 0xE4
MMI_FAST_BACKWARD_PRESS = 0xE5
MMI_FAST_BACKWARD_RELEASE = 0xE6
MMI_PLAY = 0xE7
MMI_PAUSE = 0xE8
MMI_REWIND = 0xE9
MMI_FAST_FORWARD_2 = 0xEA
MMI_STOP = 0xEB
MMI_RETRIEVE_PHONEBOOK = 0xF0
MMI_RETRIEVE_MCH = 0xF1
MMI_RETRIEVE_ICH = 0xF2
MMI_RETRIEVE_OCH = 0xF3
MMI_RETRIEVE_CCH = 0xF4
MMI_CANCEL_ACCESS_PHONEBOOK = 0xF5

# BTM Status
BTM_POWER_OFF = 0x00
BTM_POWER_ON = 0x01
BTM_PAIRING_STATE = 0x02
BTM_STANDBY_STATE = 0x03
BTM_DISCOVERABLE = 0x05
BTM_HFP_CONNECTED = 0x06
BTM_A2DP_CONNECTED = 0x07
BTM_HFP_DISCONNECTED = 0x08
BTM_A2DP_DISCONNECTED = 0x09
BTM_SCO_CONNECTED = 0x0A
BTM_SCO_DISCONNECTED = 0x0B
BTM_AVRCP_CONNECTED = 0x0C
BTM_AVRCP_DISCONNECTED = 0x0D
BTM_SPP_CONNECTED = 0x0E
BTM_SPP_DISCONNECTED = 0x0F

# Named tuple for command/event structure
Frame = namedtuple('Frame', ['start', 'length', 'opcode', 'params', 'checksum'])

class BM83:
    """BM83 Bluetooth module controller"""
    
    def __init__(self, uart_tx, uart_rx, reset_pin=None):
        """
        Initialize BM83 controller
        
        Args:
            uart_tx: TX pin for UART
            uart_rx: RX pin for UART
            reset_pin: Optional reset pin
        """
        self.uart = busio.UART(uart_tx, uart_rx, baudrate=UART_BAUDRATE, timeout=UART_TIMEOUT)
        
        if reset_pin:
            self.reset = digitalio.DigitalInOut(reset_pin)
            self.reset.direction = digitalio.Direction.OUTPUT
            self.reset.value = True
        else:
            self.reset = None
    
    def hardware_reset(self):
        """Perform hardware reset of BM83 module"""
        if self.reset:
            self.reset.value = False
            time.sleep(0.1)
            self.reset.value = True
            time.sleep(0.5)
    
    def send_command(self, opcode, params=None):
        """
        Send command to BM83 module
        
        Args:
            opcode: Command opcode
            params: Optional parameter bytes
        """
        if params is None:
            params = []
        
        frame = bm83_frame(opcode, params)
        self.uart.write(frame)
    
    def read_event(self):
        """
        Read event from BM83 module
        
        Returns:
            Frame object or None if no complete frame available
        """
        # Check if data is available
        if self.uart.in_waiting < 4:  # Minimum frame size
            return None
        
        # Read header
        header = self.uart.read(1)
        if not header or header[0] != EVT_HEADER:
            return None
        
        # Read length
        length_byte = self.uart.read(1)
        if not length_byte:
            return None
        length = length_byte[0]
        
        # Read opcode
        opcode_byte = self.uart.read(1)
        if not opcode_byte:
            return None
        opcode = opcode_byte[0]
        
        # Read parameters
        param_length = length - 2  # length includes opcode and checksum
        if param_length > 0:
            params = self.uart.read(param_length)
            if not params or len(params) != param_length:
                return None
        else:
            params = []
        
        # Read checksum
        checksum_byte = self.uart.read(1)
        if not checksum_byte:
            return None
        checksum = checksum_byte[0]
        
        return Frame(header[0], length, opcode, list(params), checksum)
    
    def mmi_action(self, action):
        """
        Send MMI action command
        
        Args:
            action: MMI action code
        """
        self.send_command(CMD_MMI_ACTION, [action])
    
    def make_call(self, phone_number):
        """
        Make a call to specified phone number
        
        Args:
            phone_number: Phone number string
        """
        params = [len(phone_number)] + [ord(c) for c in phone_number]
        self.send_command(CMD_MAKE_CALL, params)
    
    def music_control(self, action):
        """
        Send music control command
        
        Args:
            action: Music control action (0x00-0x0E)
        """
        self.send_command(CMD_MUSIC_CONTROL, [action])
    
    def read_btm_version(self):
        """Request BTM firmware version"""
        self.send_command(CMD_READ_BTM_VERSION)
    
    def read_link_status(self):
        """Request current link status"""
        self.send_command(CMD_READ_LINK_STATUS)
    
    def read_local_bd_address(self):
        """Request local Bluetooth device address"""
        self.send_command(CMD_READ_LOCAL_BD_ADDRESS)
    
    def read_local_device_name(self):
        """Request local device name"""
        self.send_command(CMD_READ_LOCAL_DEVICE_NAME)


def bm83_frame(opcode, body):
    """
    Create a BM83 command frame with proper checksum
    
    Frame structure:
    - Start byte (0xAA)
    - Length (length of opcode + parameters + checksum)
    - Opcode
    - Parameters
    - Checksum
    
    Args:
        opcode: Command opcode byte
        body: List of parameter bytes
    
    Returns:
        Complete frame as bytes
    """
    hi = CMD_HEADER
    lo = len(body) + 2  # length = parameters + opcode + checksum
    s = sum(body) & 0xFF
    chk = ((~s + 1) & 0xFF)
    return bytes([hi, lo, opcode] + body + [chk])


def parse_event(frame):
    """
    Parse BM83 event frame
    
    Args:
        frame: Frame namedtuple
    
    Returns:
        Dictionary with parsed event data
    """
    event_data = {
        'opcode': frame.opcode,
        'params': frame.params
    }
    
    # Add specific parsing for different event types
    if frame.opcode == EVT_COMMAND_ACK:
        if len(frame.params) >= 2:
            event_data['ack_command'] = frame.params[0]
            event_data['ack_status'] = frame.params[1]
    
    elif frame.opcode == EVT_BTM_STATUS:
        if len(frame.params) >= 1:
            event_data['btm_status'] = frame.params[0]
    
    elif frame.opcode == EVT_CALL_STATUS:
        if len(frame.params) >= 2:
            event_data['database_index'] = frame.params[0]
            event_data['call_status'] = frame.params[1]
    
    return event_data


# Main test code
if __name__ == "__main__":
    # Initialize BM83 with UART pins
    # Adjust pins according to your board configuration
    bm83 = BM83(board.TX, board.RX)
    
    print("BM83 Controller initialized")
    print("Requesting BTM version...")
    bm83.read_btm_version()
    
    # Main event loop
    while True:
        event = bm83.read_event()
        if event:
            parsed = parse_event(event)
            print(f"Event received: {parsed}")
        
        time.sleep(0.1)
