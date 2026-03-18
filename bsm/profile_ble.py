import asyncio
from bleak import BleakClient, BleakScanner
import struct

# JK‑BMS BLE MAC address
BMS_ADDRESS = "C8:47:80:41:43:E1"

# This is the main BLE characteristic the app uses for notifications and reads
CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Command that Android/official apps appear to send to get a full snapshot
CMD_READ_FULL = bytes.fromhex("AA5590EB9600F45F")  # based on reverse‑engineering

responses = []

def notification_handler(_, data: bytearray):
    responses.append(bytearray(data))

def parse_frame(data: bytearray):
    """
    Parse a JK BMS full data frame from BLE.
    The reverse‑engineered structure (from community BLE clients) typically yields:
      • total voltage
      • current
      • SOC
      • cell voltages
      • temperatures
    """
    info = {}

    # Minimum length check
    if len(data) < 8:
        return info

    # Example: total pack voltage is first 2 bytes (little endian, *0.01 V)
    info["total_voltage"] = struct.unpack_from("<H", data, 0)[0] / 100

    # Next 2 bytes: current (signed, *0.01 A)
    info["current"] = struct.unpack_from("<h", data, 2)[0] / 100

    # Next byte: SOC (%) directly
    info["soc"] = data[4]

    # Next: number of cell voltage measurements
    cell_count = data[5] if len(data) > 5 else 0
    cell_voltages = []
    idx = 6
    for i in range(cell_count):
        if idx + 2 <= len(data):
            cell_voltages.append(struct.unpack_from("<H", data, idx)[0] / 1000)
            idx += 2
    info["cell_voltages"] = cell_voltages

    # After voltages: if present, temperatures
    if idx + 1 < len(data):
        temp_count = data[idx]
        idx += 1
        temps = []
        for i in range(temp_count):
            if idx < len(data):
                temps.append(data[idx] - 40)  # offset if signed
                idx += 1
        info["temps"] = temps

    return info

async def run():
    device = await BleakScanner.find_device_by_address(BMS_ADDRESS, timeout=10.0)
    if not device:
        print("BMS device not found!")
        return

    async with BleakClient(device) as client:
        print("Connected, subscribing for notifications...")
        await client.start_notify(CHAR_UUID, notification_handler)

        # Send the command (observed in apps)
        await client.write_gatt_char(CHAR_UUID, CMD_READ_FULL, response=True)
        await asyncio.sleep(1.5)  # give time for notifications

        await client.stop_notify(CHAR_UUID)

    if not responses:
        print("No notifications received.")
        return

    last = responses[-1]
    result = parse_frame(last)

    print("Parsed JK‑BMS values:")
    for k, v in result.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    asyncio.run(run())