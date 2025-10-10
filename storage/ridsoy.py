from drivers.riden import Riden
from drivers.InverterController import InverterController
import serial, time

# These are the default values for port, baudrate, and address
charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)


inverter = InverterController()
inverter.Connect()
inverter.ThreadLooping(start_power=0)
time.sleep(5)
inverter.ModifyPower(120)
time.sleep(10)
# Getters and Setters are available
charger.set_v_set(57)
charger.set_i_set(0.69)

charger.set_output(True)

print(charger.get_v_set())
print(charger.get_i_set())
print(charger.get_v_out())
print(charger.get_i_out())
# Mass polling is available as well
# This reduces the number of reads to the device
charger.update()
print(charger.v_set)
print(charger.i_set)
print(charger.i_out)