from gpiozero import LED


class PinDriver:
    def __init__(self, pin: int):
        # gpiozero LED: .on() drives the pin HIGH, .off() drives it LOW.
        # The relay wiring is active-HIGH in this setup:
        # HIGH = relay energized = charger power ON,
        # LOW  = relay released  = charger power OFF.
        # (Confirmed by hardware: Riden powers up on connect().)
        self.pin = LED(pin)

    def connect(self) -> None:
        """Energize relay -> power the Riden charger."""
        self.pin.on()

    def disconnect(self) -> None:
        """Release relay -> cut power to the Riden charger."""
        self.pin.off()


# Example usage
# driver = PinDriver(17)
# driver.connect()     # HIGH -> charger powered
# driver.disconnect()  # LOW  -> charger unpowered
