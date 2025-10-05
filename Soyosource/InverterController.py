#!/usr/bin/env python3
import serial
import time
import logging
import platform
import glob
from typing import List

# -----------------------------
# CONFIGURATION
# -----------------------------
BAUD = 4800
TIMEOUT = 0.5
MAX_POWER = 950
SEND_INTERVAL = 0.5        # send packet every 0.5 s
POWER_INC_INTERVAL = 1.0   # increase power every 1 s

# -----------------------------
# LOGGER SETUP
# -----------------------------
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')


def scan_serial_ports() -> List[str]:
    """Scan available serial ports depending on OS."""
    system = platform.system()
    ports = []
    if system == "Windows":
        for i in range(1, 21):
            ports.append(f"COM{i}")
    elif system == "Linux":
        ports.extend(glob.glob("/dev/ttyUSB*"))
        ports.extend(glob.glob("/dev/ttyACM*"))
    else:
        raise RuntimeError(f"Unsupported OS: {system}")
    return ports


def detect_com_port() -> str:
    """Detect available serial ports and return the first valid one."""
    ports = scan_serial_ports()
    if not ports:
        raise RuntimeError("No serial ports found. Please connect the inverter.")

    logging.info(f"Available serial ports: {ports}")

    for port in ports:
        try:
            ser = serial.Serial(port, BAUD, timeout=TIMEOUT)
            ser.close()
            logging.info(f"Using serial port: {port}")
            return port
        except Exception:
            logging.warning(f"Port {port} is not usable")
            continue

    raise RuntimeError("No usable serial ports found.")


class InverterController:
    HEADER: List[int] = [36, 86, 0, 33]
    BYTE6: int = 128

    def __init__(self, port: str, baud: int = 4800, timeout: float = 0.5, max_power: int = 900):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.max_power = max_power
        self.ser = None

    def connect(self) -> None:
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            logging.info(f"Serial port {self.port} opened at {self.baud} bps")
        except Exception as e:
            logging.error(f"Failed to open serial port {self.port}: {e}")
            raise

    def disconnect(self) -> None:
        if self.ser and self.ser.is_open:
            self.ser.close()
            logging.info("Serial port closed")

    def build_packet(self, power_watts: int) -> List[int]:
        power = max(0, min(power_watts, self.max_power))
        b4 = (power >> 8) & 0xFF
        b5 = power & 0xFF
        chk = (264 - b4 - b5) & 0xFF
        return self.HEADER + [b4, b5, self.BYTE6, chk]

    def send_power(self, power_watts: int) -> None:
        if not self.ser or not self.ser.is_open:
            logging.error("Serial port not open. Cannot send power command.")
            return
        packet = self.build_packet(power_watts)
        try:
            self.ser.write(bytearray(packet))
            self.ser.flush()
            logging.info(f"Sent {power_watts} W: {packet}")
        except Exception as e:
            logging.error(f"Failed to send packet: {e}")


def main():
    try:
        port = detect_com_port()
        inverter = InverterController(port, BAUD, TIMEOUT, MAX_POWER)
        inverter.connect()
    except Exception as e:
        logging.error(f"Setup error: {e}")
        return

    power = 130
    last_send_time = time.time()
    last_inc_time = time.time()

    try:
        while power <= MAX_POWER:
            current_time = time.time()

            # Send power every 0.5s
            if current_time - last_send_time >= SEND_INTERVAL:
                inverter.send_power(power)
                last_send_time = current_time

            # Increase power every 1s
            if current_time - last_inc_time >= POWER_INC_INTERVAL:
                #power += 1
                last_inc_time = current_time

            time.sleep(0.01)  # small sleep to prevent CPU hogging

        logging.info(f"Reached MAX_POWER {MAX_POWER} W. Stopping.")
    except KeyboardInterrupt:
        logging.info("Interrupted by user — stopping.")
    finally:
        inverter.disconnect()


if __name__ == "__main__":
    main()
