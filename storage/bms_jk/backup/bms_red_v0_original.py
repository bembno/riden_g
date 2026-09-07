#!/usr/bin/env python3
"""
bms_red.py - Read data from JK BMS (JK-B2A24S15P, BEKEN BLE module) over BLE.

Works with the newer JK BMS BLE module (BEKEN "BK-BLE-1.0", e.g. JK-B2A24S15P
with serial-style name like 601262R2E900463) that requires BONDING (PIN 1234)
before it answers.

Protocol knowledge from:
  https://github.com/jblance/mpp-solar/issues/59       (classic JK02 protocol)
  https://github.com/jaknewbie/JKBMS-charging-monitor  (BEKEN module pairing)
  https://github.com/syssi/esphome-jk-bms              (JK02_32S frame layouts)

Frame types (all 300 bytes, header 55 AA EB 90, crc8 = byte sum & 0xFF):
  0x01  settings / register frame  (arrives with the 0x96 read sequence)
  0x02  live cell data frame       (requested with 0x96)
  0x03  device info frame          (requested with 0x97)
  0x05  logbook frame             (requested with 0xA1)

Usage (on the Pi, in /home/pi/Desktop/bms_jk):
  python3 bms_red.py --scan                 # find JK BMS by ffe0 service
  python3 bms_red.py                       # read live cell data
  python3 bms_red.py --info                 # + device info block
  python3 bms_red.py --all_info             # everything the BMS can give
  python3 bms_red.py --loop                 # keep reading every 30 s
  python3 bms_red.py --json [--all_info]    # machine readable output
"""

import argparse
import asyncio
import json
import logging
import os
import struct
import sys
import time

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("bleak not installed: pip3 install --break-system-packages bleak dbus-fast")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bms_red")

# --- BLE endpoints ---
SVC = "0000ffe0-0000-1000-8000-00805f9b34fb"
CHR = "0000ffe1-0000-1000-8000-00805f9b34fb"

# --- protocol constants ---
HEADER = bytes([0x55, 0xAA, 0xEB, 0x90])   # start of BMS response record
CMD_SOR = bytes([0xAA, 0x55, 0x90, 0xEB])   # start of host command frame
FRAME_SIZE = 300
CMD_CELL_INFO = 0x96
CMD_DEVICE_INFO = 0x97
CMD_LOGBOOK = 0xA1
VALID_TYPES = (1, 2, 3, 5)
PIN = os.environ.get("JK_PIN", "1234")

DEFAULT_MAC = "C8:47:80:58:A3:A6"

# --- lookup tables (from syssi/esphome-jk-bms) ---
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
for _i in range(32):  # 0x64..0x83 cell over charge, 0xC8..0xE7 cell over discharge
    LOGBOOK_CODES[0x64 + _i] = f"Cell {_i + 1:02d} over charge protection"
    LOGBOOK_CODES[0xC8 + _i] = f"Cell {_i + 1:02d} over discharge protection"

BATTERY_TYPES = {0: "LiFePO4 (LFP)", 1: "Li-ion / Ternary", 2: "LTO (Lithium Titanate)"}
CHARGE_STATUS = {0: "Bulk", 1: "Absorption", 2: "Float"}
BALANCER_STATUS = {0: "Idle", 1: "Charging balancer", 2: "Discharging balancer"}


def crc8(data):
    return sum(data) & 0xFF


def jk_frame(cmd, data=b"", length=None):
    """Build the 20-byte JK command frame (per esphome build_frame)."""
    n = length if length is not None else len(data)
    body = CMD_SOR + bytes([cmd, n]) + data + bytes(13 - n)
    return body + bytes([crc8(body)])


def feed_frames(buf, chunk):
    """Append chunk to buf, extract complete CRC-valid 300-byte frames."""
    buf.extend(chunk)
    frames = []
    while True:
        if len(buf) < len(HEADER):
            break
        idx = buf.find(HEADER)
        if idx < 0:
            del buf[: max(0, len(buf) - 3)]
            break
        if idx > 0:
            del buf[:idx]
        if len(buf) < FRAME_SIZE:
            break
        frame = bytes(buf[:FRAME_SIZE])
        if crc8(frame[:-1]) == frame[-1] and frame[4] in VALID_TYPES:
            del buf[:FRAME_SIZE]
            frames.append(frame)
            continue
        nxt = buf.find(HEADER, len(HEADER))
        if nxt < 0:
            del buf[: max(0, len(buf) - 3)]
            break
        del buf[:nxt]
    return frames


# --- decoding helpers (little endian) ---
def u16(b, i):
    return b[i] | (b[i + 1] << 8)

def i16(b, i):
    v = u16(b, i)
    return v - 0x10000 if v >= 0x8000 else v

def u32(b, i):
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)

def i32(b, i):
    v = u32(b, i)
    return v - 0x100000000 if v >= 0x80000000 else v

def s8(b, i):
    v = b[i]
    return v - 0x100 if v >= 0x80 else v

def sstr(b, off, ln):
    try:
        end = b.index(0x00, off)
    except ValueError:
        end = min(off + ln, len(b))
    return b[off:min(end, off + ln)].decode("utf-8", "replace")

def error_bits(mask):
    out = []
    for bit in range(32):
        if mask & (1 << bit):
            name = ERRORS_JK02[bit]
            if name:
                out.append(name)
    return out

def fmt_secs(v):
    v = int(v)
    d, v = divmod(v, 86400)
    h, v = divmod(v, 3600)
    m, s = divmod(v, 60)
    return f"{d}d {h}h {m}m {s}s"


# ---- BlueZ pairing agent (PIN 1234), from test_cut_real.py ----
async def pair_with_pin(mac):
    """Register a BlueZ agent answering PIN 1234, then pair the device."""
    try:
        from dbus_fast import Message, Variant
        from dbus_fast.service import ServiceInterface, method
        from dbus_fast.aio.message_bus import MessageBus
        from dbus_fast.constants import BusType
    except ImportError:
        log.warning("dbus-fast not installed; skipping pairing step")
        return None

    class Agent(ServiceInterface):
        def __init__(self):
            super().__init__("org.bluez.Agent1")

        @method()
        def Release(self):
            pass

        @method()
        def RequestPinCode(self, d: "s") -> "s":
            log.info("PIN requested, sending %s", PIN)
            return PIN

        @method()
        def DisplayPinCode(self, d: "s", p: "s"):
            pass

        @method()
        def RequestPasskey(self, d: "s") -> "u":
            return int(PIN)

        @method()
        def DisplayPasskey(self, d: "s", pk: "u", e: "y"):
            pass

        @method()
        def ConfirmModeAndPinCode(self, d: "s", kb: "b", pc: "s") -> "b":
            return True

        @method()
        def Authorize(self, d: "s", u: "s"):
            pass

        @method()
        def AuthorizeService(self, d: "s", u: "s"):
            pass

        @method()
        def Cancel(self):
            pass

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    agent = Agent()
    bus.export("/bms_red/agent", agent)
    await bus.call(Message(
        destination="org.bluez", path="/org/bluez",
        interface="org.bluez.AgentManager1", member="RegisterAgent",
        signature="os", body=["/bms_red/agent", "KeyboardDisplay"]))
    await bus.call(Message(
        destination="org.bluez", path="/org/bluez",
        interface="org.bluez.AgentManager1", member="RequestDefaultAgent",
        signature="o", body=["/bms_red/agent"]))

    mgr = await bus.call(Message(
        destination="org.bluez", path="/",
        interface="org.freedesktop.DBus.ObjectManager",
        member="GetManagedObjects"))
    objs = mgr.body
    if isinstance(objs, (list, tuple)):
        for el in objs:
            if isinstance(el, dict):
                objs = el
                break
    dev_path = None
    for p, ifs in objs.items():
        if "org.bluez.Device1" in ifs:
            ad = ifs["org.bluez.Device1"].get("Address")
            if isinstance(ad, Variant):
                ad = ad.value
            if ad and ad.upper() == mac.upper():
                dev_path = p
    if not dev_path:
        log.warning("device %s not known to BlueZ yet (scan first)", mac)
        return None
    try:
        await bus.call(Message(
            destination="org.bluez", path=dev_path,
            interface="org.bluez.Device1", member="Pair"))
        log.info("paired/bonded with %s", mac)
    except Exception as e:
        if "AlreadyExists" in str(e):
            log.info("already bonded with %s", mac)
        else:
            log.warning("pair failed: %s", e)
    return bus


async def scan_jk():
    print("Scanning 10s for JK BMS (service ffe0 / name like serial number)...")
    devices = await BleakScanner.discover(timeout=10.0, return_adv=True)
    found = []
    for d, adv in devices.values():
        uuids = [str(u) for u in (adv.service_uuids or [])]
        if any("ffe0" in u for u in uuids):
            print(f"  JK BMS candidate: {d.address}  name={d.name}  uuids={uuids}")
            found.append(d.address)
    if not found:
        print("  No ffe0 devices found. BMS may be asleep; wake it and retry.")
    return found


async def read_bms_frames(mac, want_types=(2,), required=(2,), timeout=25,
                          bond=True, commands=None, optional_wait=0):
    """Connect, optionally bond, run command sequence, collect frames.

    commands: list of (cmd_byte, wait_s) sent in order. Default: 0x97 then 0x96.
    Waits up to `timeout` for the required frame types; once those are in,
    keeps collecting up to `optional_wait` more seconds for the rest.
    Returns dict {frame_type: frame}.
    """
    dev = await BleakScanner.find_device_by_address(mac, timeout=15)
    if not dev:
        raise RuntimeError("device not found (asleep / out of range?)")

    if bond:
        await pair_with_pin(mac)
        await asyncio.sleep(1)

    if commands is None:
        commands = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5)]

    buf = bytearray()
    frames = {}

    def handler(_sender, data):
        for f in feed_frames(buf, bytes(data)):
            frames[f[4]] = f

    async with BleakClient(dev) as client:
        log.info("connected to %s", mac)
        await client.start_notify(CHR, handler)
        for cmd, wait_s in commands:
            await client.write_gatt_char(CHR, jk_frame(cmd), response=False)
            await asyncio.sleep(wait_s)

        deadline = time.time() + timeout
        grace_end = None
        while True:
            now = time.time()
            have_req = all(t in frames for t in required)
            have_all = all(t in frames for t in want_types)
            if have_req:
                if grace_end is None:
                    grace_end = now + optional_wait
                if have_all or now >= grace_end:
                    break
            if now >= deadline:
                break
            await asyncio.sleep(0.2)
        await client.stop_notify(CHR)
    if not all(t in frames for t in required):
        missing = [t for t in required if t not in frames]
        raise RuntimeError(f"no frame(s) {missing} within {timeout}s "
                           f"(is the BMS bonded with PIN {PIN}?)")
    return frames


# ---- frame decoders (offsets per syssi/esphome-jk-bms JK02_24S/JK02_32S) ----
def decode_cell_data(s):
    """Decode record 0x02 (live cell data).

    Layout auto-detection: newer firmware (SW >= 11, e.g. 19.x) reserves
    32 cell slots (32 voltages + 32 resistances) instead of the classic 24.
    This shifts avg/delta/maxcell/mincell/resistances by +16 bytes and all
    tail fields (battery voltage onward) by +32 bytes. Detected by comparing
    the avg-cell field against the actual cell mean and pack voltage against
    the sum of cells.
    """
    volts = [u16(s, 6 + i * 2) for i in range(32)]
    active_mv = [v for v in volts if 0 < v < 5000]
    total_mv = sum(active_mv)
    mean_mv = total_mv / len(active_mv) if active_mv else 0

    nslots = 24
    if active_mv and abs(u16(s, 74) - mean_mv) <= 5:
        nslots = 32
    elif active_mv and abs(u16(s, 58) - mean_mv) <= 5:
        nslots = 24

    tail = 32 if nslots == 32 else 0
    if active_mv:
        for cand in (0, 32):
            if abs(u32(s, 118 + cand) - total_mv) <= total_mv * 0.15:
                tail = cand
                break

    head = 16 if nslots == 32 else 0
    cells = [volts[i] / 1000.0 for i in range(nslots)]
    res = [u16(s, 64 + head + i * 2) for i in range(nslots)]
    res = [None if (r == 0xFFFF or c == 0) else r for r, c in zip(res, cells)]
    active = [c for c in cells if c > 0]

    # MOS temp: JK02_32S keeps it at 112+tail; classic 24S at 134+tail
    if nslots == 32:
        mos_raw = i16(s, 112 + tail)
        err_mask, err_bits_n = u32(s, 134 + tail), 32
    else:
        mos_raw = i16(s, 134 + tail)
        err_mask, err_bits_n = u16(s, 136 + tail), 16

    def temp(off):
        v = i16(s, off)
        return None if v <= -100 else v / 10.0

    v = u32(s, 118 + tail) / 1000.0
    i = i32(s, 126 + tail) / 1000.0
    bal_status = s[140 + tail]
    charge_status = s[248 + tail] if nslots == 32 else None

    d = {
        "layout": f"{nslots}-slot, tail+{tail}",
        "frame_counter": s[5],
        "cells": [round(c, 3) for c in cells],
        "cell_resistance_mOhm": res,
        "cells_active": len(active),
        "enabled_cells_bitmask": u32(s, 54 + head),
        "high_v": round(max(active), 3) if active else 0,
        "low_v": round(min(active), 3) if active else 0,
        "vdiff_mV": round((max(active) - min(active)) * 1000) if active else 0,
        "avg_cell_mV": u16(s, 58 + head),
        "delta_cell_mV": u16(s, 60 + head),
        "max_voltage_cell": s[62 + head] + 1,
        "min_voltage_cell": s[63 + head] + 1,
        "mos_temp_C": mos_raw / 10.0,
        "t1_C": temp(130 + tail),
        "t2_C": temp(132 + tail),
        "wire_resistance_warning_bitmask": u32(s, 114 + tail),
        "battery_voltage_V": round(v, 2),
        "current_A": round(i, 2),
        "power_W": round(v * i, 1),
        "errors_bitmask": err_mask,
        "errors": error_bits(err_mask),
        "balance_current_A": i16(s, 138 + tail) / 1000.0,
        "balancer_status": BALANCER_STATUS.get(bal_status, f"unknown(0x{bal_status:02x})"),
        "balancing": bal_status != 0,
        "soc": s[141 + tail],
        "capacity_remaining_Ah": round(u32(s, 142 + tail) / 1000.0, 2),
        "nominal_capacity_Ah": round(u32(s, 146 + tail) / 1000.0, 2),
        "cycles": u32(s, 150 + tail),
        "cycle_capacity_Ah": round(u32(s, 154 + tail) / 1000.0, 2),
        "soh": s[158 + tail],
        "precharge": bool(s[159 + tail]),
        "user_alarm": u16(s, 160 + tail),
        "total_runtime_s": u32(s, 162 + tail),
        "total_runtime": fmt_secs(u32(s, 162 + tail)),
        "charge_mosfet": bool(s[166 + tail]),
        "discharge_mosfet": bool(s[167 + tail]),
        "precharging": bool(s[168 + tail]),
        "balancer_working": bool(s[169 + tail]),
        "discharge_ocp_release_timer": u16(s, 170 + tail),
        "discharge_scp_release_timer": u16(s, 172 + tail),
        "charge_ocp_release_timer": u16(s, 174 + tail),
        "charge_scp_release_timer": u16(s, 176 + tail),
        "uvp_release_timer": u16(s, 178 + tail),
        "ovp_release_timer": u16(s, 180 + tail),
        "temp_sensor_absent_bitmask": u16(s, 182 + tail),
        "heating": bool(s[183 + tail]),
        "emergency_countdown_s": u16(s, 186 + tail),
        "discharge_current_correction": u16(s, 188 + tail),
        "charge_sensor_voltage_V": u16(s, 190 + tail) / 1000.0,
        "discharge_sensor_voltage_V": u16(s, 192 + tail) / 1000.0,
        "battery_voltage_correction_factor": u32(s, 194 + tail),
        "battery_voltage_alt_V": u16(s, 202 + tail) / 100.0,
        "heating_current_A": i16(s, 204 + tail) / 1000.0,
        "charger_plugged": bool(s[213 + tail]),
        "smart_sleep_countdown_s": u32(s, 238 + tail),
        "pcl_module_active": bool(s[242 + tail]),
        "detail_log_entry_count": u32(s, 234 + tail),
        "battery_type_code": s[243 + tail] if nslots == 32 else None,
        "battery_type": BATTERY_TYPES.get(s[243 + tail], "unknown") if nslots == 32 else None,
        "charge_status_time": u16(s, 246 + tail) if nslots == 32 else None,
        "charge_status": CHARGE_STATUS.get(charge_status, "unknown") if nslots == 32 else None,
    }
    if nslots == 32:
        d["t3_C"] = temp(226 + tail)
        d["t4_C"] = temp(224 + tail)
        d["t5_C"] = temp(222 + tail)
        dry = s[249 + tail]
        d["dry_contact_1"] = bool(dry & 0x02)
        d["dry_contact_2"] = bool(dry & 0x04)
    return d


def decode_info(info):
    d = {
        "model": sstr(info, 6, 16),
        "hardware_version": sstr(info, 22, 8),
        "software_version": sstr(info, 30, 8),
        "uptime_s": u32(info, 38),
        "power_on_count": u32(info, 42),
        "device_name": sstr(info, 46, 16),
        "device_passcode": sstr(info, 62, 16),
        "manufacturing_date": ("20" + sstr(info, 78, 6)) if info[78] != 0 else "",
        "serial_number": sstr(info, 86, 11),
        "passcode": sstr(info, 97, 5),
        "user_data": sstr(info, 102, 16),
        "setup_passcode": sstr(info, 118, 16),
    }
    return d


def decode_settings(s, nslots):
    """Decode record 0x01 (settings / protection thresholds)."""
    is32 = nslots == 32
    d = {
        "frame_counter": s[5],
        "smart_sleep_voltage_V": u32(s, 6) / 1000.0,
        "cell_uvp_V": u32(s, 10) / 1000.0,
        "cell_uvp_recovery_V": u32(s, 14) / 1000.0,
        "cell_ovp_V": u32(s, 18) / 1000.0,
        "cell_ovp_recovery_V": u32(s, 22) / 1000.0,
        "balance_trigger_delta_mV": u32(s, 26),
        "soc_100_cell_V": u32(s, 30) / 1000.0,
        "soc_0_cell_V": u32(s, 34) / 1000.0,
        "request_charge_voltage_V": u32(s, 38) / 1000.0,
        "request_float_voltage_V": u32(s, 42) / 1000.0,
        "power_off_voltage_V": u32(s, 46) / 1000.0,
        "max_charge_current_A": u32(s, 50) / 1000.0,
        "charge_ocp_delay_s": u32(s, 54),
        "charge_ocp_recovery_s": u32(s, 58),
        "max_discharge_current_A": u32(s, 62) / 1000.0,
        "discharge_ocp_delay_s": u32(s, 66),
        "discharge_ocp_recovery_s": u32(s, 70),
        "short_circuit_recovery_s": u32(s, 74),
        "max_balance_current_A": u32(s, 78) / 1000.0,
        "charge_otp_C": u32(s, 82) / 10.0,
        "charge_otp_recovery_C": u32(s, 86) / 10.0,
        "discharge_otp_C": u32(s, 90) / 10.0,
        "discharge_otp_recovery_C": u32(s, 94) / 10.0,
        "charge_utp_C": i32(s, 98) / 10.0,
        "charge_utp_recovery_C": i32(s, 102) / 10.0,
        "mos_otp_C": i32(s, 106) / 10.0,
        "mos_otp_recovery_C": i32(s, 110) / 10.0,
        "cell_count_setting": s[114],
        "charge_switch": bool(s[118]),
        "discharge_switch": bool(s[122]),
        "balancer_switch": bool(s[126]),
        "nominal_battery_capacity_Ah": u32(s, 130) / 1000.0,
        "scp_delay_us": u32(s, 134),
        "balance_start_voltage_V": u32(s, 138) / 1000.0,
    }
    if is32:
        d["wire_resistance_mOhm"] = [u32(s, 142 + i * 4) for i in range(32)]
        d["device_address"] = s[270]
        d["precharge_time_s"] = s[274]
        mask = s[282] | (s[283] << 8)
        bits = {
            0: "Heating enabled", 1: "Disable temperature sensors",
            2: "GPS Heartbeat", 3: "Port switch (RS485)", 4: "Display always on",
            5: "Special charger", 6: "Smart sleep", 7: "Disable PCL module",
            8: "Timed stored data", 9: "Charging float mode",
            10: "Button trigger emergency", 11: "DRY ARM intermittent",
            12: "Discharge OCP II", 13: "Discharge OCP III",
            14: "GPS locked charging", 15: "GPS locked discharging",
        }
        d["controls_bitmask"] = mask
        d["controls_enabled"] = [name for bit, name in bits.items() if mask & (1 << bit)]
        d["heating_start_C"] = s8(s, 284)
        d["heating_stop_C"] = s8(s, 285)
        d["smart_sleep_delay_min"] = s[286]
        d["discharge_utp_C"] = s8(s, 296)
        d["discharge_utp_recovery_C"] = s8(s, 297)
    else:
        d["wire_resistance_mOhm"] = [u32(s, 158 + i * 4) for i in range(24)]
    return d


def decode_logbook(s):
    """Decode record 0x05 (event logbook)."""
    count = u32(s, 6)
    entries = []
    for i in range(min(count, 50)):
        base = 11 + i * 5
        if base + 5 > len(s):
            break
        ts = u32(s, base)
        code = s[base + 4]
        entries.append({
            "time": fmt_secs(ts),
            "code": code,
            "event": LOGBOOK_CODES.get(code, f"Unknown (0x{code:02X})"),
        })
    return {"count": count, "entries": entries}


# ---- printing ----
def print_cell_line(d):
    print(f"  SOC: {d['soc']}%  SOH: {d['soh']}%  Cycles: {d['cycles']}"
          f"  (cycle cap {d['cycle_capacity_Ah']} Ah)")
    print(f"  Pack: {d['battery_voltage_V']} V   I: {d['current_A']:+.2f} A"
          f"   P: {d['power_W']:+.1f} W")
    print(f"  Cells ({d['cells_active']}): {d['low_v']} ~ {d['high_v']} V"
          f"  (delta {d['vdiff_mV']} mV, avg {d['avg_cell_mV']} mV)")
    print(f"  Highest cell: #{d['max_voltage_cell']}  Lowest cell: #{d['min_voltage_cell']}")
    for i, c in enumerate(d["cells"], 1):
        if c > 0:
            r = d["cell_resistance_mOhm"][i - 1]
            rtxt = f"{r} mOhm" if r is not None else "n/a"
            print(f"    Cell {i:02d}: {c:.3f} V   R={rtxt}")
    t = [f"T1 {d['t1_C']} C", f"T2 {d['t2_C']} C", f"MOS {d['mos_temp_C']} C"]
    if "t3_C" in d:
        t += [f"T3 {d['t3_C']} C", f"T4 {d['t4_C']} C", f"T5 {d['t5_C']} C"]
    print(f"  Temps: " + "  ".join(t))
    print(f"  Balancer: {d['balancer_status']}"
          f"  bal I: {d['balance_current_A']} A  runtime: {d['total_runtime']}")
    print(f"  Capacity: {d['capacity_remaining_Ah']} / {d['nominal_capacity_Ah']} Ah")
    print(f"  Chg MOS: {'ON' if d['charge_mosfet'] else 'OFF'}"
          f"  Dsg MOS: {'ON' if d['discharge_mosfet'] else 'OFF'}")
    errs = "; ".join(d["errors"]) if d["errors"] else "none"
    print(f"  Errors (0x{d['errors_bitmask']:08X}): {errs}")


def print_report(frames):
    d = decode_cell_data(frames[2])
    info = decode_info(frames[3]) if 3 in frames else {}
    print("=== JK BMS Cell Data ===")
    if info:
        print(f"  Model: {info['model']}  SW: {info['software_version']}"
              f"  HW: {info['hardware_version']}")
    print_cell_line(d)
    return d


def print_all(frames):
    out = {}

    if 3 in frames:
        info = decode_info(frames[3])
        out["info"] = info
        print("=== Device info (frame 0x03) ===")
        for k, v in info.items():
            print(f"  {k:24s}: {v}")
        print(f"  {'uptime':24s}: {fmt_secs(info['uptime_s'])}")
    else:
        print("=== Device info (frame 0x03): NOT RECEIVED ===")

    print()
    if 2 in frames:
        d = decode_cell_data(frames[2])
        out["cell"] = d
        print("=== Live cell data (frame 0x02) ===")
        print_cell_line(d)
        print("  --- status flags ---")
        print(f"  Precharging: {d['precharging']}   Heating: {d['heating']}"
              f"   Charger plugged: {d['charger_plugged']}")
        print(f"  PCL module active: {d['pcl_module_active']}"
              f"   Smart sleep in: {d['smart_sleep_countdown_s']} s")
        print(f"  User alarm: 0x{d['user_alarm']:04X}   "
              f"Wire-resist.warn: 0x{d['wire_resistance_warning_bitmask']:08X}   "
              f"Enabled cells: 0x{d['enabled_cells_bitmask']:08X}")
        print(f"  Charge status: {d['charge_status']}"
              f"   Battery type: {d['battery_type']}"
              f"   Detail log entries: {d['detail_log_entry_count']}")
        if "dry_contact_1" in d:
            print(f"  Dry contacts: DRY1={d['dry_contact_1']} DRY2={d['dry_contact_2']}"
                  f"   Emergency countdown: {d['emergency_countdown_s']} s")
        print(f"  Release timers (dchg-OCP/SCP, chg-OCP/SCP, UVP, OVP): "
              f"{d['discharge_ocp_release_timer']}/{d['discharge_scp_release_timer']}"
              f"/{d['charge_ocp_release_timer']}/{d['charge_scp_release_timer']}"
              f"/{d['uvp_release_timer']}/{d['ovp_release_timer']}")
    else:
        print("=== Live cell data (frame 0x02): NOT RECEIVED ===")

    print()
    if 1 in frames:
        nslots = 32 if decode_cell_data(frames[2])["layout"].startswith("32") else 24
        st = decode_settings(frames[1], nslots)
        out["settings"] = st
        print("=== Settings / protection (frame 0x01) ===")
        print(f"  Layout: {nslots}-slot")
        print(f"  -- voltages --")
        print(f"  Cell OVP: {st['cell_ovp_V']} V  recovery {st['cell_ovp_recovery_V']} V")
        print(f"  Cell UVP: {st['cell_uvp_V']} V  recovery {st['cell_uvp_recovery_V']} V")
        print(f"  Balance start: {st['balance_start_voltage_V']} V"
              f"   trigger delta: {st['balance_trigger_delta_mV']} mV"
              f"   max bal I: {st['max_balance_current_A']} A")
        print(f"  Power off voltage: {st['power_off_voltage_V']} V"
              f"   Smart sleep voltage: {st['smart_sleep_voltage_V']} V")
        print(f"  SOC 100% cell: {st['soc_100_cell_V']} V   SOC 0% cell: {st['soc_0_cell_V']} V")
        print(f"  Request charge V: {st['request_charge_voltage_V']} V"
              f"   float V: {st['request_float_voltage_V']} V")
        print(f"  -- currents --")
        print(f"  Max charge: {st['max_charge_current_A']} A"
              f"  (OCP delay {st['charge_ocp_delay_s']}s, rec {st['charge_ocp_recovery_s']}s)")
        print(f"  Max discharge: {st['max_discharge_current_A']} A"
              f"  (OCP delay {st['discharge_ocp_delay_s']}s,"
              f" rec {st['discharge_ocp_recovery_s']}s)")
        print(f"  SCP delay: {st['scp_delay_us']} us"
              f"   SCP recovery: {st['short_circuit_recovery_s']} s")
        print(f"  -- temperatures --")
        print(f"  Charge OTP {st['charge_otp_C']} C / rec {st['charge_otp_recovery_C']} C;"
              f"  Dsg OTP {st['discharge_otp_C']} C / rec {st['discharge_otp_recovery_C']} C")
        print(f"  Charge UTP {st['charge_utp_C']} C / rec {st['charge_utp_recovery_C']} C;"
              f"  MOS OTP {st['mos_otp_C']} C / rec {st['mos_otp_recovery_C']} C")
        if "discharge_utp_C" in st:
            print(f"  Dsg UTP {st['discharge_utp_C']} C / rec {st['discharge_utp_recovery_C']} C;"
                  f"  Heating {st['heating_start_C']}..{st['heating_stop_C']} C")
        print(f"  -- switches / config --")
        print(f"  Cell count setting: {st['cell_count_setting']}"
              f"   Nominal capacity: {st['nominal_battery_capacity_Ah']} Ah")
        print(f"  Charge sw: {st['charge_switch']}   Discharge sw: {st['discharge_switch']}"
              f"   Balancer sw: {st['balancer_switch']}")
        if "controls_bitmask" in st:
            print(f"  Controls bitmask 0x{st['controls_bitmask']:04X}: "
                  + (", ".join(st["controls_enabled"]) or "none"))
            print(f"  Device address: {st['device_address']}"
                  f"   Precharge time: {st['precharge_time_s']} s"
                  f"   Smart sleep delay: {st['smart_sleep_delay_min']} min")
        wr = [r for r in st["wire_resistance_mOhm"] if r]
        print(f"  Wire resistances (non-zero): "
              + (", ".join(f"#{i+1}:{r}" for i, r in
                           enumerate(st["wire_resistance_mOhm"]) if r) or "all zero"))
    else:
        print("=== Settings (frame 0x01): NOT RECEIVED ===")

    print()
    if 5 in frames:
        lb = decode_logbook(frames[5])
        out["logbook"] = lb
        print(f"=== Logbook (frame 0x05): {lb['count']} events ===")
        for i, e in enumerate(lb["entries"], 1):
            print(f"  [{i:3d}] {e['time']:>16s}  {e['event']}")
    else:
        print("=== Logbook (frame 0x05): NOT RECEIVED ===")

    return out


async def main_async():
    ap = argparse.ArgumentParser(description="Read JK BMS (JK-B2A24S15P) over BLE")
    ap.add_argument("mac", nargs="?", default=DEFAULT_MAC)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--info", action="store_true", help="also print device info block")
    ap.add_argument("--all_info", action="store_true",
                    help="read everything: device info, live data, settings, logbook")
    ap.add_argument("--loop", action="store_true", help="repeat every 30 s")
    ap.add_argument("--no-bond", action="store_true", help="skip pairing attempt")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--raw", action="store_true", help="dump raw frame hex (debug)")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.scan:
        await scan_jk()
        return

    if args.all_info:
        commands = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5), (CMD_LOGBOOK, 0.3)]
        want, required, opt_wait = (1, 2, 3, 5), (2,), 8
    elif args.info:
        commands = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5)]
        want, required, opt_wait = (2, 3), (2,), 3
    else:
        commands = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5)]
        want, required, opt_wait = (2,), (2,), 0

    while True:
        try:
            frames = await read_bms_frames(args.mac, want_types=want,
                                           required=required, bond=not args.no_bond,
                                           commands=commands, optional_wait=opt_wait)
            if args.raw:
                for ftype, f in sorted(frames.items()):
                    print(f"RAW FRAME type 0x{ftype:02X} (300B):")
                    for off in range(0, 300, 20):
                        print(f"  {off:3d} (0x{off:02X}): {f[off:off+20].hex(' ')}")
            if args.json:
                result = {}
                if 3 in frames:
                    result["info"] = decode_info(frames[3])
                if 2 in frames:
                    result["cell"] = decode_cell_data(frames[2])
                if 1 in frames:
                    nslots = 32 if result.get("cell", {}).get("layout", "").startswith("32") else 24
                    result["settings"] = decode_settings(frames[1], nslots)
                if 5 in frames:
                    result["logbook"] = decode_logbook(frames[5])
                print(json.dumps(result, ensure_ascii=False, indent=2))
            elif args.all_info:
                print_all(frames)
            elif args.info:
                print_report(frames)
            else:
                print_report(frames)
        except Exception as e:
            log.error("read failed: %s", e)
        if not args.loop:
            break
        time.sleep(30)


if __name__ == "__main__":
    asyncio.run(main_async())
