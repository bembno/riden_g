import serial
import time

ser = serial.Serial("COM8", 4800, timeout=1)  # try 9600 first

# Example: read 1 register at address 0 (MODBUS function 3)
#packet = [0x01, 0x03, 0x00, 0x00, 0x00, 0x01, 0x84, 0x0A]
packet =[36, 86, 0, 33, 0, 0, 128, 8]

print(">>> Sent:", packet)
ser.write(bytearray(packet))

time.sleep(0.5)

if ser.in_waiting:
    response = ser.read(ser.in_waiting)
    print("<<< Raw recv:", list(response))
else:
    print("<<< No response")
