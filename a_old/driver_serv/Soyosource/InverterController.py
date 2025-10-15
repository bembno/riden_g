#!/usr/bin/env python3
import serial
import time
import logging
import platform
import glob
import threading
from typing import List

class InverterController:
    def __init__(self, port=None, baud=4800, timeout=0.5, max_power=950, send_interval=0.5):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.max_power = max_power
        self.send_interval = send_interval
        self.ser = None
        self.HEADER = [36, 86, 0, 33]
        self.BYTE6 = 128
        self._power = 0  # stored in watts
        self._running = False
        self._thread = None
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

    def set_power(self, power_kw: float):
        """Set output power in kW, internally converted to watts before sending."""
        power_watts = int(power_kw * 1000)
        self._power = max(0, min(power_watts, self.max_power))
        logging.info(f"Set power to {power_kw:.3f} kW ({self._power} W, sent every {self.send_interval}s)")

    def _send_loop(self):
        while self._running:
            self.send_power(self._power)
            time.sleep(self.send_interval)

    def scan_serial_ports(self) -> List[str]:
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

    def detect_com_port(self) -> str:
        ports = self.scan_serial_ports()
        if not ports:
            raise RuntimeError("No serial ports found. Please connect the inverter.")
        logging.info(f"Available serial ports: {ports}")
        for port in ports:
            try:
                ser = serial.Serial(port, self.baud, timeout=self.timeout)
                ser.close()
                logging.info(f"Using serial port: {port}")
                return port
            except Exception:
                logging.warning(f"Port {port} is not usable")
                continue
        raise RuntimeError("No usable serial ports found.")

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

    def start(self, initial_power_kw=0.0):
        if not self.port:
            self.port = self.detect_com_port()
        try:
            self.connect()
        except Exception as e:
            logging.error(f"Setup error: {e}")
            return
        self.set_power(initial_power_kw)
        self._running = True
        self._thread = threading.Thread(target=self._send_loop, daemon=True)
        self._thread.start()
        logging.info("Started background power sending thread.")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join()
        self.disconnect()
        logging.info("Stopped background power sending thread and disconnected.")

if __name__ == "__main__":
    inverter = InverterController()
    inverter.start(initial_power_kw=0.14)  # 0.14 kW = 140 W
    try:
        while True:
            time.sleep(10)
            inverter.set_power(0.13)  # 0.9 kW = 900 W
    except KeyboardInterrupt:
        inverter.stop()
