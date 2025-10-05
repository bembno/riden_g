#!/usr/bin/env python3
import serial
import time
import logging
import platform
import serial
import time
import logging
import platform
import glob
from typing import List

class InverterController:
    def __init__(self, port=None, baud=4800, timeout=0.5, max_power=950, send_interval=0.5, power_inc_interval=1.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.max_power = max_power
        self.send_interval = send_interval
        self.power_inc_interval = power_inc_interval
        self.ser = None
        self.HEADER = [36, 86, 0, 33]
        self.BYTE6 = 128
        logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

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

    def run(self):
        if not self.port:
            self.port = self.detect_com_port()
        try:
            self.connect()
        except Exception as e:
            logging.error(f"Setup error: {e}")
            return

        
        last_send_time = time.time()
        last_inc_time = time.time()

        try:
            while power <= self.max_power:
                current_time = time.time()
                if current_time - last_send_time >= self.send_interval:
                    self.send_power(power)
                    last_send_time = current_time
                if current_time - last_inc_time >= self.power_inc_interval:
                    # power += 1
                    last_inc_time = current_time
                time.sleep(0.01)
            logging.info(f"Reached MAX_POWER {self.max_power} W. Stopping.")
        except KeyboardInterrupt:
            logging.info("Interrupted by user — stopping.")
        finally:
            self.disconnect()

if __name__ == "__main__":
    inverter = InverterController()
    power = 140
    inverter.run()
    inverter.send_power(power)
