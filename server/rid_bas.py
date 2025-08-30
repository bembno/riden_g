from riden import Riden

# These are the default values for port, baudrate, and address
r = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)

# Getters and Setters are available
r.set_v_set(4.20)
r.set_i_set(0.69)
print(r.get_v_set())
print(r.get_i_set())

# Mass polling is available as well
# This reduces the number of reads to the device
r.update()
print(r.v_set)
print(r.i_set)