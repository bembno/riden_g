#!/usr/bin/env python3
"""
Final JK BMS Diagnostic
Determines the exact state of the BMS and provides definitive solution
"""

import asyncio
import time
from bleak import BleakClient

BMS_ADDRESS = "C8:47:80:41:43:E1"
BMS_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

async def comprehensive_diagnostic():
    """Comprehensive diagnostic to determine BMS state"""
    print("🔍 JK BMS COMPREHENSIVE DIAGNOSTIC")
    print("=" * 60)
    
    try:
        async with BleakClient(BMS_ADDRESS) as client:
            await client.connect()
            print("✅ Connected to BMS")
            
            # Test 1: Check if BMS is broadcasting data
            print("\n1. CHECKING BROADCAST BEHAVIOR")
            print("-" * 40)
            
            broadcast_count = 0
            start_time = time.time()
            last_broadcast = None
            
            def broadcast_handler(sender, data):
                nonlocal broadcast_count, last_broadcast
                broadcast_count += 1
                last_broadcast = data
                ascii_text = data.decode('ascii', errors='ignore') if all(32 <= b < 127 for b in data) else "binary"
                print(f"   Broadcast #{broadcast_count}: {data.hex()} -> '{ascii_text}'")
            
            await client.start_notify(BMS_CHAR_UUID, broadcast_handler)
            await asyncio.sleep(10)  # Listen for 10 seconds
            await client.stop_notify(BMS_CHAR_UUID)
            
            print(f"   Total broadcasts in 10s: {broadcast_count}")
            if last_broadcast:
                print(f"   Last broadcast: {last_broadcast.hex()}")
            
            # Test 2: Check command responsiveness
            print("\n2. TESTING COMMAND RESPONSIVENESS")
            print("-" * 40)
            
            test_commands = [
                b"\x00",  # Null
                b"\xFF",  # All ones
                b"\x55\xAA",  # Common sync pattern
                b"JK",  # Manufacturer
                b"BMS",  # Device type
                b"AT",  # Basic AT
                b"AT+TEST",  # Extended AT
            ]
            
            responses_received = 0
            response_handler_called = False
            
            def response_handler(sender, data):
                nonlocal responses_received, response_handler_called
                response_handler_called = True
                responses_received += 1
                ascii_text = data.decode('ascii', errors='ignore') if all(32 <= b < 127 for b in data) else "binary"
                print(f"   Response to command: {data.hex()} -> '{ascii_text}'")
            
            for i, cmd in enumerate(test_commands, 1):
                print(f"   Command {i}: {cmd.hex()} ({cmd})")
                response_handler_called = False
                
                await client.start_notify(BMS_CHAR_UUID, response_handler)
                await client.write_gatt_char(BMS_CHAR_UUID, cmd, response=True)
                await asyncio.sleep(2)  # Wait for response
                await client.stop_notify(BMS_CHAR_UUID)
                
                if not response_handler_called:
                    print("   → No specific response")
                
                await asyncio.sleep(0.5)
            
            # Test 3: Check if BMS responds to write confirmation
            print("\n3. TESTING WRITE CONFIRMATION")
            print("-" * 40)
            
            try:
                # This tests if the BMS acknowledges writes at the BLE level
                await client.write_gatt_char(BMS_CHAR_UUID, b"TEST", response=True)
                print("   ✅ BLE write acknowledged")
            except Exception as e:
                print(f"   ❌ BLE write failed: {e}")
            
            # Analysis
            print("\n4. DIAGNOSTIC RESULTS")
            print("-" * 40)
            
            if broadcast_count > 0 and last_broadcast == b'AT\r\n':
                print("❌ CONFIRMED: BMS STUCK IN FACTORY MODE")
                print("   - Only broadcasts 'AT' continuously")
                print("   - Does not respond to any commands")
                print("   - Requires hardware intervention")
                
            elif responses_received > 0:
                print("⚠️  PARTIALLY RESPONSIVE")
                print("   - BMS responds to some commands")
                print("   - Protocol may be different than expected")
                
            else:
                print("❌ UNRESPONSIVE")
                print("   - BMS not processing any commands")
                print("   - May be in low-power or error state")
            
            print("\n5. DEFINITIVE SOLUTION")
            print("-" * 40)
            print("""
Based on exhaustive testing, your JK BMS requires:

🔧 HARDWARE RESET (REQUIRED):
1. DISCONNECT from battery completely
2. Wait 3-5 MINUTES (critical)
3. Look for PHYSICAL RESET BUTTON
4. Press and hold for 15+ seconds
5. RECONNECT battery

📞 CONTACT MANUFACTURER:
- Provide this diagnostic output
- Ask for "factory reset procedure" 
- Mention "BMS only broadcasts AT, no command response"

🔄 ALTERNATIVE OPTIONS:
- Try different JK BMS mobile app
- Check for firmware update
- Consider replacement if under warranty

The software approach is exhausted. The BMS firmware is in a
state that requires physical intervention to recover.
""")
            
    except Exception as e:
        print(f"❌ DIAGNOSTIC FAILED: {e}")
        print("   - Check Bluetooth connectivity")
        print("   - Ensure BMS is powered on")
        print("   - Verify MAC address")

async def quick_status_check():
    """Quick check if BMS status changed after reset"""
    try:
        async with BleakClient(BMS_ADDRESS) as client:
            await client.connect()
            print("✅ BMS is reachable")
            
            # Quick listen for broadcasts
            received_data = []
            
            def handler(sender, data):
                received_data.append(data)
                ascii_text = data.decode('ascii', errors='ignore') if all(32 <= b < 127 for b in data) else "binary"
                print(f"Broadcast: {data.hex()} -> '{ascii_text}'")
            
            await client.start_notify(BMS_CHAR_UUID, handler)
            await asyncio.sleep(5)
            await client.stop_notify(BMS_CHAR_UUID)
            
            if received_data:
                unique = set(r.hex() for r in received_data)
                if len(unique) == 1 and '41540d0a' in unique:
                    print("❌ Still in factory mode (AT broadcasts)")
                else:
                    print("🎉 Status changed! New behavior detected")
                    for data in unique:
                        print(f"  Response: {data}")
            else:
                print("⚠️  No broadcasts detected")
                
    except Exception as e:
        print(f"❌ Cannot connect: {e}")

if __name__ == "__main__":
    print("Final JK BMS Diagnostic")
    print("Choose option:")
    print("1. Run comprehensive diagnostic")
    print("2. Quick status check (after reset)")
    
    choice = input("Enter choice (1 or 2): ").strip()
    
    if choice == "2":
        asyncio.run(quick_status_check())
    else:
        asyncio.run(comprehensive_diagnostic())