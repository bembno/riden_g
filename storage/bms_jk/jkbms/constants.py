"""Protocol constants and lookup tables for the JK BMS JK02-style BLE protocol."""

from __future__ import annotations

import os

# --- BLE endpoints ---
SVC = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHR = "0000ffe1-0000-1000-8000-00805f9b34fb"

# --- protocol constants ---
HEADER = bytes([0x55, 0xAA, 0xEB, 0x90])   # start of BMS response record
CMD_SOR = bytes([0xAA, 0x55, 0x90, 0xEB])  # start of host command frame
FRAME_SIZE = 300

# host command bytes
CMD_CELL_INFO = 0x96
CMD_DEVICE_INFO = 0x97
CMD_LOGBOOK = 0xA1

# BMS response frame types
FRAME_TYPE_SETTINGS = 0x01
FRAME_TYPE_CELL_INFO = 0x02
FRAME_TYPE_DEVICE_INFO = 0x03
FRAME_TYPE_LOGBOOK = 0x05
VALID_TYPES = (FRAME_TYPE_SETTINGS, FRAME_TYPE_CELL_INFO,
               FRAME_TYPE_DEVICE_INFO, FRAME_TYPE_LOGBOOK)

# bonding PIN of the BEKEN BLE module (override with the JK_PIN env var)
DEFAULT_PIN = os.environ.get("JK_PIN", "1234")

DEFAULT_MAC = "C8:47:80:58:A3:A6"

ERRORS_JK02 = [
    "Wire resistance",                      # bit 0
    "MOSFET overtemperature",               # bit 1
    "Cell count is not equal to settings",  # bit 2
    "",                                     # bit 3
    "Battery is fully charged",             # bit 4
    "Battery pack overvoltage",             # bit 5
    "Charge overcurrent",                   # bit 6
    "Charge short circuit",                 # bit 7
    "Charge overtemperature",               # bit 8
    "Charge undertemperature",              # bit 9
    "Coprocessor communication error",      # bit 10
    "Cell undervoltage",                    # bit 11
    "Battery pack undervoltage",            # bit 12
    "Discharge overcurrent",                # bit 13
    "Discharge short circuit",              # bit 14
    "Discharge overtemperature",            # bit 15
    "Charging MOSFET abnormal",             # bit 16
    "Discharging MOSFET abnormal",          # bit 17
    "GPS disconnected",                     # bit 18
    "Modify password in time",              # bit 19
    "Discharge on failed",                  # bit 20
    "Battery overtemperature",              # bit 21
    "Temperature sensor anomaly",           # bit 22
    "PL module anomaly",                    # bit 23
    "SCP release failed",                   # bit 24
    "Discharge OCP II",                     # bit 25
    "Discharge OCP III",                    # bit 26
    "Discharge undertemperature alarm",     # bit 27
    "GPS remote lock",                      # bit 28
    "",                                     # bit 29
    "",                                     # bit 30
    "",                                     # bit 31
]

LOGBOOK_CODES = {
    0x01: "Boot", 0x02: "Shutdown",
    0x03: "APP close charge", 0x04: "APP open charge",
    0x05: "APP close discharge", 0x06: "APP open discharge",
    0x07: "Remote close charge", 0x08: "Remote open charge",
    0x09: "Remote close discharge", 0x0A: "Remote open discharge",
    0x0B: "MOS over temperature protection",
    0x0C: "MOS over-temperature protection released",
    0x0D: "Abnormal current sensor", 0x0E: "Current sensor abnormality released",
    0x0F: "Abnormal coprocessor communication",
    0x10: "Coprocessor communication recovered",
    0x11: "Cell overcharge protection", 0x12: "Cell overcharge protection released",
    0x13: "Battery overcharge protection", 0x14: "Battery overcharge protection released",
    0x15: "Charge overcurrent protection", 0x16: "Charge overcurrent protection released",
    0x17: "Charge short circuit protection", 0x18: "Charge short circuit protection released",
    0x19: "Charge over temperature protection",
    0x1A: "Charge over temperature protection released",
    0x1B: "Charge low temperature protection",
    0x1C: "Charge low temperature protection released",
    0x1D: "Cell undervoltage protection", 0x1E: "Cell undervoltage protection released",
    0x1F: "Battery undervoltage protection", 0x20: "Battery undervoltage protection released",
    0x21: "Discharge overcurrent protection",
    0x22: "Discharge overcurrent protection released",
    0x23: "Discharge short circuit protection",
    0x24: "Discharge short circuit protection released",
    0x25: "Discharge over temperature protection",
    0x26: "Discharge over-temperature protection released",
    0x27: "Reset Watch-Dog",
    0x28: "Discharge level 2 short circuit protection",
    0x29: "Manually enable the emergency mode",
    0x2A: "Manually turn off the emergency mode",
    0x2B: "Emergency mode turned off automatically",
    0x2C: "APP to turn it off", 0x2D: "Button to turn it off",
    0x2E: "Discharge On Failed", 0x2F: "RS485 power off",
    0x30: "CAN charge off", 0x31: "CAN charge on",
    0x32: "CAN discharge off", 0x33: "CAN discharge on",
    0x34: "RS485 charge off", 0x35: "RS485 charge on",
    0x36: "RS485 discharge off", 0x37: "RS485 discharge on",
    0x38: "Enter sleep",
    0x39: "Charge MOS abnormal", 0x3A: "Discharge MOS abnormal",
    0x3B: "Time calibration", 0x3C: "Cells Count Incorrect",
    0x3D: "Button Emergency On", 0x3E: "Button Emergency Off",
    0x3F: "Button Forced Heating",
    0x40: "Discharge OCP II", 0x41: "Discharge OCP III",
    0x42: "SCP Release Failed",
    0x43: "Factory setting LION", 0x44: "Factory setting LFP",
    0x45: "Factory setting LTO",
    0x46: "Remote Emergency On", 0x47: "Remote Emergency Off",
    0x48: "Discharge under temperature protection",
    0x49: "Discharge under temperature protection released",
}

# 0x64..0x83 cell over charge, 0xC8..0xE7 cell over discharge
for _code in range(32):
    LOGBOOK_CODES[0x64 + _code] = f"Cell {_code + 1:02d} over charge protection"
    LOGBOOK_CODES[0xC8 + _code] = f"Cell {_code + 1:02d} over discharge protection"
del _code

BATTERY_TYPES = {0: "LiFePO4 (LFP)", 1: "Li-ion / Ternary", 2: "LTO (Lithium Titanate)"}
CHARGE_STATUS = {0: "Bulk", 1: "Absorption", 2: "Float"}
BALANCER_STATUS = {0: "Idle", 1: "Charging balancer", 2: "Discharging balancer"}

# bitmask of the settings "controls" flags (frame 0x01, 32-slot layout only)
CONTROL_BITS = {
    0: "Heating enabled", 1: "Disable temperature sensors",
    2: "GPS Heartbeat", 3: "Port switch (RS485)", 4: "Display always on",
    5: "Special charger", 6: "Smart sleep", 7: "Disable PCL module",
    8: "Timed stored data", 9: "Charging float mode",
    10: "Button trigger emergency", 11: "DRY ARM intermittent",
    12: "Discharge OCP II", 13: "Discharge OCP III",
    14: "GPS locked charging", 15: "GPS locked discharging",
}
