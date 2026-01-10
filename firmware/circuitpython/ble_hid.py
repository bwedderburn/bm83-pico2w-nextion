"""
BLE HID volume control implementation.
"""
from __future__ import annotations

# Try importing BLE libraries
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


class BleHid:
    """BLE HID controller for volume control."""

    def __init__(self, device_name: str = "BM83-Controller"):
        """Initialize BLE HID with device name."""
        self.device_name = device_name
        self.ble = None
        self.hid = None
        self.consumer_control = None

        if not HAS_BLE:
            print("BLE libraries not available")
            return

        try:
            self.ble = adafruit_ble.BLERadio()
            self.hid = HIDService()
            advertisement = ProvideServicesAdvertisement(self.hid)
            advertisement.complete_name = device_name
            self.ble.start_advertising(advertisement)
            print(f"BLE HID advertising as '{device_name}'...")

            # Wait for connection (non-blocking check)
            if self.ble.connected:
                self.consumer_control = ConsumerControl(self.hid.devices)
                print("BLE HID connected")
        except Exception as e:
            print(f"BLE init failed: {e}")
            self.ble = None

    def is_connected(self) -> bool:
        """Check if BLE is connected."""
        return self.ble is not None and self.ble.connected

    def send_volume_up(self) -> None:
        """Send volume up command."""
        if self.consumer_control:
            self.consumer_control.send(ConsumerControlCode.VOLUME_INCREMENT)

    def send_volume_down(self) -> None:
        """Send volume down command."""
        if self.consumer_control:
            self.consumer_control.send(ConsumerControlCode.VOLUME_DECREMENT)
