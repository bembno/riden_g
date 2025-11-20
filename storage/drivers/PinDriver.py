from gpiozero import LED
from time import sleep

class PinDriver:
    def __init__(self, pin: int):
        # LED() drives pin HIGH when .on() and LOW when .off()
        # We want active-low: LOW = connected, HIGH = disconnected
        self.pin = LED(pin)

    def connect(self) -> None:
        """Set pin to 0V = connected (active-low)."""
        self.pin.on()

    def disconnect(self) -> None:
        """Set pin to HIGH = disconnected."""
        self.pin.off()


# Example usage
#driver = PinDriver(17)
#driver.connect()     # 0V
#sleep(2)
#driver.disconnect()  # HIGH