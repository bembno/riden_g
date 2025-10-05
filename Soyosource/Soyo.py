#!/usr/bin/env python3
import serial
import time

# -----------------------------
# CONFIGURATION
# -----------------------------
PORT = "COM8"
BAUD = 4800
TIMEOUT = 0.5
MAX_POWER = 900      # safe max power for inverter
SEND_INTERVAL=0.5
# -----------------------------
# CONSTANTS
# -----------------------------
HEADER = [36, 86, 0, 33]  # packet header
BYTE6 = 128               # fixed byte index 6

# -----------------------------
# FUNCTION TO BUILD PACKET
# -----------------------------
def build_packet(power_watts: int) -> list:
    """Build a valid 8-byte packet for the inverter."""
    power = max(0, min(power_watts, MAX_POWER))
    b4 = (power >> 8) & 0xFF
    b5 = power & 0xFF
    chk = (264 - b4 - b5) & 0xFF
    return HEADER + [b4, b5, BYTE6, chk]

# -----------------------------
# FUNCTION TO SEND POWER
# -----------------------------
def send_power(ser: serial.Serial, power_watts: int):
    packet = build_packet(power_watts)
    ser.write(bytearray(packet))
    ser.flush()
    print(f">>> Sent {power_watts} W: {packet}")

# -----------------------------
# MAIN LOOP
# -----------------------------
def main():
    try:
        ser = serial.Serial(PORT, BAUD, timeout=TIMEOUT)
        print(f"Opened {PORT} @ {BAUD}bps")
    except Exception as e:
        print("Failed to open serial port:", e)
        return

    try:
        while True:
            # Example: send 100 W, wait, then 200 W
            send_power(ser, 100)
            time.sleep(SEND_INTERVAL)


    except KeyboardInterrupt:
        print("Interrupted by user — stopping.")
    finally:
        ser.close()
        print("Serial port closed.")

if __name__ == "__main__":
    main()
