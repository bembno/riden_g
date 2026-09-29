#!/usr/bin/env python3
import serial, time, logging, platform, glob, threading
from typing import List, Optional

# -----------------------------
# CONFIGURATION
# -----------------------------
BAUD = 4800
TIMEOUT = 0.5
MAX_POWER = 950
SEND_INTERVAL = 0.5

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# -----------------------------
# HELPER FUNCTION
# -----------------------------
def DetectComPort(baud: int = BAUD, timeout: float = TIMEOUT) -> str:
    """Return first usable serial port."""
    system = platform.system()
    ports = (
        [f"COM{i}" for i in range(1, 21)] if system == "Windows"
        else glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    )
    if not ports:
        raise RuntimeError("No serial ports found.")
    for port in ports:
        try:
            with serial.Serial(port, baud, timeout=timeout):
                logging.info("Using serial port: {}".format(port))
                return port
        except Exception:
            continue
    raise RuntimeError("No usable serial ports found.")

# -----------------------------
# MAIN CLASS
# -----------------------------
class InverterController:
    HEADER = [36, 86, 0, 33]
    BYTE6 = 128

    def __init__(self, port=None, baud=BAUD, timeout=TIMEOUT, max_power=MAX_POWER):
        self.Port, self.Baud, self.Timeout = port, baud, timeout
        self.MaxPower = max_power
        self.SerialConn: Optional[serial.Serial] = None
        self.CurrentPower = 0
        self.Running = False
        self.Thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Health tracking
        self._consecutive_failures = 0
        self._max_failures_before_unhealthy = 5
        self._last_successful_send = 0
        self._last_health_check = 0

    # ---- Connection ----
    def Connect(self):
        if not self.Port:
            self.Port = DetectComPort(self.Baud, self.Timeout)
        self.SerialConn = serial.Serial(self.Port, self.Baud, timeout=self.Timeout)
        logging.info("Connected to {} @ {} bps".format(self.Port, self.Baud))
        self._consecutive_failures = 0
        self._last_successful_send = time.time()

    def Disconnect(self):
        if self.SerialConn and self.SerialConn.is_open:
            self.SerialConn.close()
            logging.info("Serial port closed")

    # ---- Communication ----
    def BuildPacket(self, power: int) -> bytes:
        power = max(0, min(power, self.MaxPower))
        b4, b5 = (power >> 8) & 0xFF, power & 0xFF
        chk = (264 - b4 - b5) & 0xFF
        return bytes(self.HEADER + [b4, b5, self.BYTE6, chk])

    def SendPower(self, power: int):
        if not self.SerialConn or not self.SerialConn.is_open:
            logging.error("Serial port not open.")
            self._record_failure()
            return
        try:
            packet = self.BuildPacket(power)
            self.SerialConn.write(packet)
            self.SerialConn.flush()
            with self._lock:
                self.CurrentPower = power
            logging.info("Sent {} W".format(power))
            self._record_success()
        except Exception as e:
            logging.error("Send failed: {}".format(e))
            self._record_failure()

    def _record_success(self):
        with self._lock:
            self._consecutive_failures = 0
            self._last_successful_send = time.time()

    def _record_failure(self):
        with self._lock:
            self._consecutive_failures += 1

    # ---- Power Control ----
    def ModifyPower(self, new_power: int):
        new_power = max(0, min(new_power, self.MaxPower))
        self.SendPower(round(new_power))

    def GetCurrentPower(self) -> int:
        """Return the latest sent power value."""
        with self._lock:
            return self.CurrentPower

    # ---- Health Monitoring ----
    def is_healthy(self) -> bool:
        """Return True if inverter is connected and healthy."""
        with self._lock:
            if self.SerialConn is None or not self.SerialConn.is_open:
                return False
            if self._consecutive_failures >= self._max_failures_before_unhealthy:
                return False
            return True

    def get_failure_count(self) -> int:
        """Return number of consecutive failures."""
        with self._lock:
            return self._consecutive_failures

    def get_last_success_time(self) -> float:
        """Return timestamp of last successful send."""
        with self._lock:
            return self._last_successful_send

    def reset_failure_count(self):
        """Reset failure counter after successful recovery."""
        with self._lock:
            self._consecutive_failures = 0

    # ---- Control Loop ----
    def StartControlLoop(self, start_power=0, send_interval=SEND_INTERVAL):
        """Start sending power periodically in a thread."""
        if self.Running:
            logging.warning("Control loop already running.")
            return

        self.Running = True
        self.CurrentPower = start_power

        def Loop():
            logging.info("Control loop started")
            try:
                while self.Running:
                    self.SendPower(self.CurrentPower)
                    time.sleep(send_interval)
            except KeyboardInterrupt:
                pass
            finally:
                self.StopControlLoop()

        self.Thread = threading.Thread(target=Loop, daemon=True)
        self.Thread.start()

    def StopControlLoop(self):
        if self.Running:
            self.Running = False
            logging.info("Control loop stopped")

    def ThreadLooping(self, start_power=0, send_interval=SEND_INTERVAL):
        """Public helper to start threaded control loop."""
        self.StartControlLoop(start_power, send_interval)

    def Stop(self):
        self.StopControlLoop()
        self.Disconnect()

# -----------------------------
# ENTRY POINT
# -----------------------------
if __name__ == "__main__":
    ctrl = InverterController()
    ctrl.Connect()
    ctrl.ThreadLooping(start_power=0)

    time.sleep(5)
    ctrl.ModifyPower(120)
    logging.info("Current power (reported): {} W".format(ctrl.GetCurrentPower()))

    time.sleep(5)
    ctrl.Stop()