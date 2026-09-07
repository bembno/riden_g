"""Command-line interface for the JK BMS BLE reader.

Examples::

    jkbms read [--mac C8:47:80:58:A3:A6] [--all] [--json] [--pretty]
    jkbms log --mac C8:47:80:58:A3:A6 --interval 30 --out readings.jsonl
    jkbms scan
    jkbms show readings.jsonl --last 5 --fields timestamp,cell.battery_voltage_V

``jkbms log`` is the daemon-style command: it reads regularly and appends
each reading as one JSON line to ``--out`` (JSON Lines format, append-only,
safe to stop/resume; read it with ``jq``/``pandas`` or ``jkbms show``).
"""


"""
# One-shot reads (synchronous — simplest for scripts/cron)
from jkbms import read_live, read_all

r = read_live()                    # uses default MAC C8:47:80:58:A3:A6
print(r.cell.battery_voltage_V, r.cell.soc, r.cell.current_A, r.cell.errors)
print(r.info.software_version)     # "19.30"

r = read_all()                     # also settings + logbook
print(r.settings.cell_ovp_V, r.settings.controls_enabled)
print([e.event for e in r.logbook.entries])

"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from typing import Optional, Sequence

from .constants import DEFAULT_MAC
from .decoders import fmt_secs
from .models import ABSENT, JkReadings

log = logging.getLogger("jkbms.cli")

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="jkbms", description="Read JK BMS (JK-B2A24S15P) over BLE")
    ap.add_argument("--debug", action="store_true", help="verbose logging")
    sub = ap.add_subparsers(dest="cmd")

    p_read = sub.add_parser("read", help="read once and print")
    p_read.add_argument("mac", nargs="?", default=DEFAULT_MAC,
                        help="BMS MAC address (default: %(default)s)")
    p_read.add_argument("--all", action="store_true",
                        help="read everything: info, live data, settings, logbook")
    p_read.add_argument("--json", action="store_true", help="JSON output")
    p_read.add_argument("--pretty", action="store_true",
                        help="human-readable report (default)")
    p_read.add_argument("--raw", action="store_true", help="dump raw frame hex")
    p_read.add_argument("--no-bond", action="store_true", help="skip pairing")

    p_log = sub.add_parser(
        "log", help="read regularly and append each reading to a JSONL file")
    p_log.add_argument("--mac", default=DEFAULT_MAC)
    p_log.add_argument("--out", default="readings.jsonl",
                       help="output JSONL file (default: readings.jsonl)")
    p_log.add_argument("--interval", type=float, default=30.0,
                       help="seconds between reads (default: 30)")
    p_log.add_argument("--all", action="store_true",
                        help="log everything (info+live+settings+logbook) "
                             "instead of just info+live")
    p_log.add_argument("--sections", default=None,
                       help="comma-separated sections to store, e.g. cell,info "
                            "(default: all received)")
    p_log.add_argument("--count", type=int, default=None,
                       help="stop after N readings (default: run forever)")
    p_log.add_argument("--no-bond", action="store_true", help="skip pairing")

    p_scan = sub.add_parser("scan", help="discover JK BMS by ffe0 service")
    p_scan.add_argument("--timeout", type=float, default=10.0)
    p_show = sub.add_parser("show", help="inspect a JSONL log file")
    p_show.add_argument("file")
    p_show.add_argument("--last", type=int, default=None,
                        help="show only the last N records")
    p_show.add_argument("--fields", default=None,
                        help="comma-separated 'dotted' fields, e.g. "
                             "timestamp,cell.battery_voltage_V,cell.soc")

    return ap


# --- read command output ------------------------------------------------
def print_cell_line(d) -> None:
    print(f"  SOC: {d.soc}%  SOH: {d.soh}%  Cycles: {d.cycles}"
          f"  (cycle cap {d.cycle_capacity_Ah} Ah)")
    print(f"  Pack: {d.battery_voltage_V} V   I: {d.current_A:+.2f} A"
          f"   P: {d.power_W:+.1f} W")
    print(f"  Cells ({d.cells_active}): {d.low_v} ~ {d.high_v} V"
          f"  (delta {d.vdiff_mV} mV, avg {d.avg_cell_mV} mV)")
    print(f"  Highest cell: #{d.max_voltage_cell}  Lowest cell: #{d.min_voltage_cell}")
    for i, c in enumerate(d.cells, 1):
        if c > 0:
            r = d.cell_resistance_mOhm[i - 1]
            rtxt = f"{r} mOhm" if r is not None else "n/a"
            print(f"    Cell {i:02d}: {c:.3f} V   R={rtxt}")
    t = [f"T1 {d.t1_C} C", f"T2 {d.t2_C} C", f"MOS {d.mos_temp_C} C"]
    if d.t3_C is not ABSENT:
        t += [f"T3 {d.t3_C} C", f"T4 {d.t4_C} C", f"T5 {d.t5_C} C"]
    print("  Temps: " + "  ".join(t))
    print(f"  Balancer: {d.balancer_status}"
          f"  bal I: {d.balance_current_A} A  runtime: {d.total_runtime}")
    print(f"  Capacity: {d.capacity_remaining_Ah} / {d.nominal_capacity_Ah} Ah")
    print(f"  Chg MOS: {'ON' if d.charge_mosfet else 'OFF'}"
          f"  Dsg MOS: {'ON' if d.discharge_mosfet else 'OFF'}")
    errs = "; ".join(d.errors) if d.errors else "none"
    print(f"  Errors (0x{d.errors_bitmask:08X}): {errs}")


def print_report(readings: JkReadings) -> None:
    print("=== JK BMS Cell Data ===")
    if readings.info is not None:
        info = readings.info
        print(f"  Model: {info.model}  SW: {info.software_version}"
              f"  HW: {info.hardware_version}")
    if readings.cell is not None:
        print_cell_line(readings.cell)


def print_all(readings: JkReadings) -> None:
    if readings.info is not None:
        print("=== Device info (frame 0x03) ===")
        for k, v in readings.info.to_dict().items():
            print(f"  {k:24s}: {v}")
        print(f"  {'uptime':24s}: {fmt_secs(readings.info.uptime_s)}")
    else:
        print("=== Device info (frame 0x03): NOT RECEIVED ===")

    print()
    if readings.cell is not None:
        d = readings.cell
        print("=== Live cell data (frame 0x02) ===")
        print_cell_line(d)
        print("  --- status flags ---")
        print(f"  Precharging: {d.precharging}   Heating: {d.heating}"
              f"   Charger plugged: {d.charger_plugged}")
        print(f"  PCL module active: {d.pcl_module_active}"
              f"   Smart sleep in: {d.smart_sleep_countdown_s} s")
        print(f"  User alarm: 0x{d.user_alarm:04X}   "
              f"Wire-resist.warn: 0x{d.wire_resistance_warning_bitmask:08X}   "
              f"Enabled cells: 0x{d.enabled_cells_bitmask:08X}")
        print(f"  Charge status: {d.charge_status}"
              f"   Battery type: {d.battery_type}"
              f"   Detail log entries: {d.detail_log_entry_count}")
        if d.dry_contact_1 is not ABSENT:
            print(f"  Dry contacts: DRY1={d.dry_contact_1} DRY2={d.dry_contact_2}"
                  f"   Emergency countdown: {d.emergency_countdown_s} s")
        print(f"  Release timers (dchg-OCP/SCP, chg-OCP/SCP, UVP, OVP): "
              f"{d.discharge_ocp_release_timer}/{d.discharge_scp_release_timer}"
              f"/{d.charge_ocp_release_timer}/{d.charge_scp_release_timer}"
              f"/{d.uvp_release_timer}/{d.ovp_release_timer}")
    else:
        print("=== Live cell data (frame 0x02): NOT RECEIVED ===")

    print()
    if readings.settings is not None:
        st = readings.settings
        print("=== Settings / protection (frame 0x01) ===")
        print(f"  Layout: {readings.cell.nslots if readings.cell else 24}-slot")
        print(f"  -- voltages --")
        print(f"  Cell OVP: {st.cell_ovp_V} V  recovery {st.cell_ovp_recovery_V} V")
        print(f"  Cell UVP: {st.cell_uvp_V} V  recovery {st.cell_uvp_recovery_V} V")
        print(f"  Balance start: {st.balance_start_voltage_V} V"
              f"   trigger delta: {st.balance_trigger_delta_mV} mV"
              f"   max bal I: {st.max_balance_current_A} A")
        print(f"  Power off voltage: {st.power_off_voltage_V} V"
              f"   Smart sleep voltage: {st.smart_sleep_voltage_V} V")
        print(f"  SOC 100% cell: {st.soc_100_cell_V} V   SOC 0% cell: {st.soc_0_cell_V} V")
        print(f"  Request charge V: {st.request_charge_voltage_V} V"
              f"   float V: {st.request_float_voltage_V} V")
        print(f"  -- currents --")
        print(f"  Max charge: {st.max_charge_current_A} A"
              f"  (OCP delay {st.charge_ocp_delay_s}s, rec {st.charge_ocp_recovery_s}s)")
        print(f"  Max discharge: {st.max_discharge_current_A} A"
              f"  (OCP delay {st.discharge_ocp_delay_s}s,"
              f" rec {st.discharge_ocp_recovery_s}s)")
        print(f"  SCP delay: {st.scp_delay_us} us"
              f"   SCP recovery: {st.short_circuit_recovery_s} s")
        print(f"  -- temperatures --")
        print(f"  Charge OTP {st.charge_otp_C} C / rec {st.charge_otp_recovery_C} C;"
              f"  Dsg OTP {st.discharge_otp_C} C / rec {st.discharge_otp_recovery_C} C")
        print(f"  Charge UTP {st.charge_utp_C} C / rec {st.charge_utp_recovery_C} C;"
              f"  MOS OTP {st.mos_otp_C} C / rec {st.mos_otp_recovery_C} C")
        if st.discharge_utp_C is not ABSENT:
            print(f"  Dsg UTP {st.discharge_utp_C} C / rec {st.discharge_utp_recovery_C} C;"
                  f"  Heating {st.heating_start_C}..{st.heating_stop_C} C")
        print(f"  -- switches / config --")
        print(f"  Cell count setting: {st.cell_count_setting}"
              f"   Nominal capacity: {st.nominal_battery_capacity_Ah} Ah")
        print(f"  Charge sw: {st.charge_switch}   Discharge sw: {st.discharge_switch}"
              f"   Balancer sw: {st.balancer_switch}")
        if st.controls_bitmask is not ABSENT:
            print(f"  Controls bitmask 0x{st.controls_bitmask:04X}: "
                  + (", ".join(st.controls_enabled) or "none"))
            print(f"  Device address: {st.device_address}"
                  f"   Precharge time: {st.precharge_time_s} s"
                  f"   Smart sleep delay: {st.smart_sleep_delay_min} min")
        wr = [r for r in st.wire_resistance_mOhm if r]
        print(f"  Wire resistances (non-zero): "
              + (", ".join(f"#{i+1}:{r}" for i, r in
                           enumerate(st.wire_resistance_mOhm) if r) or "all zero"))
    else:
        print("=== Settings (frame 0x01): NOT RECEIVED ===")

    print()
    if readings.logbook is not None:
        lb = readings.logbook
        print(f"=== Logbook (frame 0x05): {lb.count} events ===")
        for i, e in enumerate(lb.entries, 1):
            print(f"  [{i:3d}] {e.time:>16s}  {e.event}")
    else:
        print("=== Logbook (frame 0x05): NOT RECEIVED ===")


def print_raw_frames(frames: dict) -> None:
    for ftype, f in sorted(frames.items()):
        print(f"RAW FRAME type 0x{ftype:02X} (300B):")
        for off in range(0, 300, 20):
            print(f"  {off:3d} (0x{off:02X}): {f[off:off+20].hex(' ')}")


# --- subcommand runners -------------------------------------------------
async def _cmd_read(args) -> int:
    from .client import JkBmsClient

    client = JkBmsClient(args.mac, bond=not args.no_bond)
    read = client.read_all if args.all else client.read_live
    try:
        readings = await read()
    except Exception as e:
        log.error("read failed: %s", e)
        return 1
    if args.raw and readings.raw_frames:
        print_raw_frames(readings.raw_frames)
    if args.json:
        print(json.dumps(readings.to_dict(), ensure_ascii=False, indent=2))
    elif args.all:
        print_all(readings)
    else:
        print_report(readings)
    return 0


async def _cmd_log(args) -> int:
    from .client import JkBmsClient
    from .storage import JsonlStore

    sections = args.sections.split(",") if args.sections else None
    client = JkBmsClient(args.mac, bond=not args.no_bond)
    store = JsonlStore(args.out, sections=sections)
    read = client.read_all if args.all else client.read_live
    n = 0
    try:
        while True:
            start = asyncio.get_running_loop().time()
            try:
                readings = await read()
                store.append(readings)
                n += 1
                print(f"[{readings.timestamp}] appended #{n} -> {store.path}",
                      flush=True)
            except Exception as e:
                log.error("read failed: %s", e)
            if args.count is not None and n >= args.count:
                break
            elapsed = asyncio.get_running_loop().time() - start
            await asyncio.sleep(max(0.0, args.interval - elapsed))
    except KeyboardInterrupt:
        pass
    print(f"logged {n} reading(s) to {store.path}")
    return 0 if n else 1


async def _cmd_scan(args) -> int:
    from .client import JkBmsClient

    print(f"Scanning {args.timeout:.0f}s for JK BMS "
          "(service ffe0 / name like serial number)...")
    client = JkBmsClient()
    found = await client.scan(timeout=args.timeout)
    for c in found:
        print(f"  JK BMS candidate: {c.address}  name={c.name}  "
              f"uuids={c.service_uuids}")
    if not found:
        print("  No ffe0 devices found. BMS may be asleep; wake it and retry.")
    return 0


def _dig(data, dotted: str):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


async def _cmd_show(args) -> int:
    from .storage import JsonlStore

    store = JsonlStore(args.file)
    records = list(store.iter())
    if args.last is not None:
        records = records[-args.last:]
    fields = args.fields.split(",") if args.fields else None
    for rec in records:
        if fields:
            row = {f: _dig(rec, f) for f in fields}
            print(json.dumps(row, ensure_ascii=False))
        else:
            print(json.dumps(rec, ensure_ascii=False))
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format=LOG_FORMAT)
    if args.cmd is None:
        build_arg_parser().print_help()
        return 2
    runners = {"read": _cmd_read, "log": _cmd_log, "scan": _cmd_scan,
               "show": _cmd_show}
    return asyncio.run(runners[args.cmd](args))


if __name__ == "__main__":
    sys.exit(main())
