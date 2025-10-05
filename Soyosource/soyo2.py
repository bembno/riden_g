import serial
import time

# --- Configuration ---
PORT = "COM8"
BAUDRATE = 4800
TIMEOUT = 1  # seconds

# The packet you want to send
packet = [36, 86, 0, 33, 0, 0, 128, 8]

# --- Open serial port ---
ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
print(f"Opened {PORT} at {BAUDRATE} baud")

try:
    while True:
        ser.write(bytearray(packet))
        print(">>> Sent:", packet)
        time.sleep(0.5)  # send every 0.5 seconds

except KeyboardInterrupt:
    print("Stopping...")
    ser.close()

