#!/usr/bin/env python3
import asyncio
import argparse
from datetime import datetime

from bleak import BleakScanner, BleakClient

async def do_scan(timeout: float = 6.0):
    print(f"[{datetime.now()}] Scanning for BLE devices for {timeout} seconds...")
    devices = await BleakScanner.discover(timeout=timeout)
    if not devices:
        print("No BLE devices found.")
        return
    for d in devices:
        name = d.name or "Unknown"
        print(f"Device {d.address}  Name: {name!r}  RSSI: {d.rssi} dBm")

async def dump_device(address: str):
    print(f"[{datetime.now()}] Connecting to {address} ...")
    async with BleakClient(address) as client:
        connected = client.is_connected
        if not connected:
            print("Failed to connect!")
            return
        print("Connected.")

        # Bleak 0.23+ uses 'services' property instead of get_services()
        services = client.services
        if services is None:
            # Trigger services discovery
            await client.get_services()  # some versions still require this
            services = client.services

        for service in services:
            print(f"[Service] {service.uuid}: {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                print(f"  [Characteristic] {char.uuid} ({props})")

def main():
    parser = argparse.ArgumentParser(description="BLE scanner and JK BMS service dumper")
    parser.add_argument("--scan", action="store_true", help="Scan for BLE devices")
    parser.add_argument("--address", type=str, help="BLE device address to dump services")
    parser.add_argument("--timeout", type=float, default=6.0, help="Scan timeout in seconds")
    args = parser.parse_args()

    if args.scan:
        asyncio.run(do_scan(timeout=args.timeout))
    elif args.address:
        asyncio.run(dump_device(args.address))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
