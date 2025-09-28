import asyncio
from bleak import BleakClient
from datetime import datetime
import struct

# JK BMS UUIDs
BMS_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# JK BMS binary commands
CMD_SWITCH_BINARY = b"AT+MODE=BINARY\r\n"
CMD_READ_BASIC = bytes.fromhex("DDA50300FFFD77")
CMD_READ_TEMPS = bytes.fromhex("DDA50400FFFC77")
CMD_READ_BALANCE = bytes.fromhex("DDA50500FFFB77")
CMD_READ_SOC = bytes.fromhex("DDA50600FFFA77")
CMD_READ_VOLTAGES = bytes.fromhex("DDA50700FFF977")
CMD_READ_CURRENT = bytes.fromhex("DDA50800FFF877")

# BMS MAC
BMS_ADDRESS = "C8:47:80:41:43:E1"

# Timeout for notifications
NOTIF_WAIT = 1.0  # seconds

# Global storage for received data
responses = {}

def parse_basic_info(data: bytearray):
    # Example parsing; adjust based on JK BMS documentation
    if len(data) < 10:
        return {}
    return {
        "Pack Voltage (V)": struct.unpack_from("<H", data, 0)[0] / 100,
        "Pack Current (A)": struct.unpack_from("<h", data, 2)[0] / 100,
        "Number of Cells": data[4],
        "Number of Temperatures": data[5],
        "Balance Status": data[6]
    }

def parse_soc(data: bytearray):
    if len(data) < 3:
        return {}
    return {"SOC (%)": data[0]}

def parse_voltages(data: bytearray):
    if len(data) < 1:
        return {"Cell Voltages (V)": []}
    num_cells = data[0]
    voltages = []
    expected_len = 1 + num_cells * 2
    if len(data) < expected_len:
        print(f"[Warning] Expected {expected_len} bytes for voltages, got {len(data)}. Using available data.")
        num_cells = (len(data) - 1) // 2  # adjust number of cells
    for i in range(num_cells):
        offset = 1 + i * 2
        if offset + 2 <= len(data):
            val = struct.unpack_from("<H", data, offset)[0] / 1000
            voltages.append(val)
    return {"Cell Voltages (V)": voltages}


def parse_current(data: bytearray):
    if len(data) < 2:
        return {}
    return {"Current (A)": struct.unpack_from("<h", data, 0)[0] / 100}

def parse_temperatures(data: bytearray):
    """
    Parse temperature data from JK BMS.
    First byte: number of temperature sensors
    Following bytes: temperatures in °C
    """
    if len(data) < 1:
        return {"Temperatures (°C)": []}

    num_sensors = data[0]
    temps = []

    # Adjust num_sensors if data is shorter than expected
    if len(data) - 1 < num_sensors:
        print(f"[Warning] Expected {num_sensors} temperature bytes, got {len(data)-1}. Using available data.")
        num_sensors = len(data) - 1

    for i in range(num_sensors):
        offset = 1 + i
        if offset < len(data):
            temps.append(data[offset])
    return {"Temperatures (°C)": temps}


def parse_balance(data: bytearray):
    # Each bit indicates balancing status of a cell
    bits = struct.unpack("<H", data[0:2])[0]
    return {"Balance Bits": bin(bits)}

async def run_bms():
    async with BleakClient(BMS_ADDRESS) as client:
        if not client.is_connected:
            print("Failed to connect!")
            return
        print(f"[{datetime.now()}] Connected to BMS")

        def handler(sender, data):
            # store last notification for each command
            responses[sender] = data

        await client.start_notify(BMS_CHAR_UUID, handler)

        # Switch to binary mode
        await client.write_gatt_char(BMS_CHAR_UUID, CMD_SWITCH_BINARY, response=True)
        await asyncio.sleep(0.5)

        # Send commands and wait for response
        commands = [
            ("Basic Info", CMD_READ_BASIC, parse_basic_info),
            ("SOC", CMD_READ_SOC, parse_soc),
            ("Voltages", CMD_READ_VOLTAGES, parse_voltages),
            ("Current", CMD_READ_CURRENT, parse_current),
            ("Temperatures", CMD_READ_TEMPS, parse_temperatures),
            ("Balance", CMD_READ_BALANCE, parse_balance)
        ]

        for name, cmd, parser in commands:
            print(f"[{datetime.now()}] Reading {name}...")
            await client.write_gatt_char(BMS_CHAR_UUID, cmd, response=True)
            await asyncio.sleep(NOTIF_WAIT)

            # Use last notification
            data = list(responses.values())[-1] if responses else bytearray()
            parsed = parser(data)
            print(f"--- {name} ---")
            for k, v in parsed.items():
                print(f"{k}: {v}")
            print("")

        await client.stop_notify(BMS_CHAR_UUID)
        print(f"[{datetime.now()}] Finished reading BMS")

if __name__ == "__main__":
    asyncio.run(run_bms())
