import asyncio
from bleak import BleakClient

# ====== CONFIGURATION ======
BMS_ADDRESS = "C8:47:80:41:43:E1"
BMS_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
PASSWORD = b"1234"
RETRY_COUNT = 3
CELL_COUNT = 16

# ====== BINARY COMMANDS ======
CMD_READ_BASIC = bytes.fromhex("DDA50300FFFD77")
CMD_READ_SOC   = bytes.fromhex("DDA50600FFFA77")
CMD_READ_VOLT  = bytes.fromhex("DDA50700FFF977")

# ====== GLOBAL DATA ======
notification_data = None

def parse_response(data: bytes):
    if not data or len(data) < 10:
        print("Frame too short:", data.hex())
        return None
    try:
        offset = 5
        voltages = []
        for i in range(CELL_COUNT):
            v = int.from_bytes(data[offset:offset+2], "little")
            voltages.append(v / 1000)
            offset += 2
        current = int.from_bytes(data[offset:offset+2], "little", signed=True) / 100
        offset += 2
        soc = data[offset]
        offset += 1
        temperatures = list(data[offset:offset+2])
        offset += 2
        balance_bits = int.from_bytes(data[offset:offset+2], "little")
        return {
            "voltages": voltages,
            "current": current,
            "soc": soc,
            "temps": temperatures,
            "balance_bits": balance_bits
        }
    except Exception as e:
        print("Failed parsing:", e)
        return None

def notification_handler(sender, data):
    """Callback for BLE notifications"""
    global notification_data
    notification_data = data

async def enable_binary_mode(client: BleakClient):
    for attempt in range(RETRY_COUNT):
        print(f"[+] Enabling binary mode attempt {attempt+1}")
        await client.write_gatt_char(BMS_UUID, b"AT+BINARY\r\n")
        await asyncio.sleep(1.5)
        if notification_data and b"OK" in notification_data:
            print("[+] Binary mode enabled!")
            return True
    print("[-] Failed to enable binary mode.")
    return False

async def send_command(client, cmd_name, cmd):
    global notification_data
    notification_data = None
    await client.write_gatt_char(BMS_UUID, cmd)
    # wait for notification to arrive
    for _ in range(20):  # 20 x 0.1s = 2 seconds
        await asyncio.sleep(0.1)
        if notification_data:
            print(f"[{cmd_name}] Raw:", notification_data.hex())
            parsed = parse_response(notification_data)
            if parsed:
                print(f"[{cmd_name}] Parsed:", parsed)
            print("-"*30)
            return
    print(f"[{cmd_name}] No response received!")

async def read_bms():
    async with BleakClient(BMS_ADDRESS) as client:
        print("[*] Connected to BMS")
        # Subscribe to notifications
        await client.start_notify(BMS_UUID, notification_handler)
        
        # Try to enable binary mode
        
        if not await enable_binary_mode_with_password(client):    
            print("[-] Cannot proceed without binary mode")
            return
        
        # Send commands
        for cmd_name, cmd in [("Basic Info", CMD_READ_BASIC), 
                              ("SOC", CMD_READ_SOC), 
                              ("Voltages", CMD_READ_VOLT)]:
            await send_command(client, cmd_name, cmd)
        
        await client.stop_notify(BMS_UUID)

async def enable_binary_mode_with_password(client: BleakClient):
    """
    Sends password first, then switches to binary mode.
    """
    global notification_data
    for attempt in range(RETRY_COUNT):
        print(f"[+] Attempt {attempt+1} to enable binary mode with password")
        notification_data = None

        # 1️⃣ Send password
        await client.write_gatt_char(BMS_UUID, PASSWORD + b"\r\n")
        await asyncio.sleep(1.0)
        if notification_data and b"OK" in notification_data:
            print("[+] Password accepted")
        else:
            print("[!] No OK after password, retrying...")
            continue

        # 2️⃣ Send AT+BINARY
        notification_data = None
        await client.write_gatt_char(BMS_UUID, b"AT+BINARY\r\n")
        await asyncio.sleep(1.5)
        if notification_data and b"OK" in notification_data:
            print("[+] Binary mode enabled!")
            return True
        print("[!] No OK after AT+BINARY, retrying...")
    print("[-] Failed to enable binary mode with password.")
    return False

if __name__ == "__main__":
    asyncio.run(read_bms())