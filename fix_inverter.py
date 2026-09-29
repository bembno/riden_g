with open('drivers/InverterController.py') as f:
    c = f.read()

# Add failure tracking to __init__
c = c.replace(
    '''    def __init__(self, port=None, baud=BAUD, timeout=TIMEOUT, max_power=MAX_POWER):
        self.Port, self.Baud, self.Timeout = port, baud, timeout
        self.MaxPower = max_power
        self.SerialConn: Optional[serial.Serial] = None
        self.CurrentPower = 0
        self.Running = False
        self.Thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()''',
    '''    def __init__(self, port=None, baud=BAUD, timeout=TIMEOUT, max_power=MAX_POWER):
        self.Port, self.Baud, self.Timeout = port, baud, timeout
        self.MaxPower = max_power
        self.SerialConn: Optional[serial.Serial] = None
        self.CurrentPower = 0
        self.Running = False
        self.Thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._max_failures = 5''')

# Update SendPower
c = c.replace(
    '''    def SendPower(self, power: int):
        if not self.SerialConn or not self.SerialConn.is_open:
            logging.error("Serial port not open.")
            return
        try:
            packet = self.BuildPacket(power)
            self.SerialConn.write(packet)
            self.SerialConn.flush()
            with self._lock:
                self.CurrentPower = power
            logging.info(f"Sent {power} W")
        except Exception as e:
            logging.error(f"Send failed: {e}")''',
    '''    def SendPower(self, power: int) -> bool:
        if not self.SerialConn or not self.SerialConn.is_open:
            self._consecutive_failures += 1
            logging.error("Serial port not open.")
            return False
        try:
            packet = self.BuildPacket(power)
            self.SerialConn.write(packet)
            self.SerialConn.flush()
            with self._lock:
                self.CurrentPower = power
                self._consecutive_failures = 0
            return True
        except Exception as e:
            self._consecutive_failures += 1
            logging.error(f"Send failed: {e}")
            return False

    def is_healthy(self) -> bool:
        return (self._consecutive_failures < self._max_failures and
                self.SerialConn is not None and self.SerialConn.is_open)''')

with open('drivers/InverterController.py', 'w') as f:
    f.write(c)
print('inverter fixed')