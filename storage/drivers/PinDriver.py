from gpiozero import LED
from time import sleep

class PinDriver:
    def __init__(self, pin: int):
        # LED() drives pin HIGH when .on() and LOW when .off()
        # We want active-low: LOW = connected, HIGH = disconnected
        self.pin = LED(pin)

    def connect(self) -> None:
        self.pin.on()

    def disconnect(self) -> None:
        self.pin.off()


# Example usage
#driver = PinDriver(17)
#driver.connect()     # 0V
#sleep(2)
#driver.disconnect()  # HIGH