#!/usr/bin/env python3
"""BMS -> MQTT bridge (runs on the storage Pi, next to the JK BMS).

Polls the JK BMS over BLE every POLL_INTERVAL seconds, publishes the
decoded state as JSON to bms_jk/status, and prints a full color status
readout on stdout (watch live with: screen -r bms).

The log file can never grow unbounded: a RotatingFileHandler caps it at
BMS_LOG_MAXBYTES (default 1 MB) and keeps BMS_LOG_BACKUPS (default 2)
rotated copies. Console output mirrors the same lines.

BMS outages (asleep / out of range / BT blocked) are handled gracefully:
the read failure is logged, an error payload is published so downstream
consumers can see the outage, and retries back off progressively. The
process never exits on a read error.

Environment overrides:
  BMS_MAC            BLE MAC of the JK BMS    (default C8:47:80:58:A3:A6)
  JK_PIN             bonding PIN              (default 1234)
  BMS_POLL_SECONDS   poll interval            (default 30)
  BMS_BROKER         MQTT broker              (default 127.0.0.1)
  BMS_LOG_DIR        log directory            (default <script dir>/logs)
  BMS_LOG_MAXBYTES   rotate size in bytes     (default 1048576)
  BMS_LOG_BACKUPS    rotated files to keep    (default 2)
"""
import json
import logging
import os
import re
import sys
import time
from logging.handlers import RotatingFileHandler

import paho.mqtt.client as mqtt

# jkbms library lives next to this script in the repo (storage/bms_jk)
# or as a standalone checkout at /home/pi/Desktop/bms_jk on the Pi
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, "bms_jk"), "/home/pi/Desktop/bms_jk"):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
        break

from jkbms import read_live  # noqa: E402  (path setup above)

MAC = os.environ.get("BMS_MAC", "C8:47:80:58:A3:A6")
PIN = os.environ.get("JK_PIN", "1234")
POLL_INTERVAL = float(os.environ.get("BMS_POLL_SECONDS", "30"))
BROKER = os.environ.get("BMS_BROKER", "127.0.0.1")
PORT = 1883
TOPIC_STATUS = "bms_jk/status"
TOPIC_ONLINE = "bms_jk/online"

LOG_DIR = os.environ.get("BMS_LOG_DIR", os.path.join(_HERE, "logs"))
LOG_FILE = os.path.join(LOG_DIR, "bms_mqtt.log")
LOG_MAX_BYTES = int(os.environ.get("BMS_LOG_MAXBYTES", str(1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("BMS_LOG_BACKUPS", "2"))

MAX_BACKOFF = 300.0

# --- console colors (stripped from the file log by _PlainFormatter) ---
RESET = "\033[0m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BRIGHT = "\033[97m"

_ANSI_RE = re.compile(r"\033\[[0-9;]*m")


class _PlainFormatter(logging.Formatter):
    """Formatter that strips ANSI colors (used for the file log)."""

    def format(self, record):
        return _ANSI_RE.sub("", super().format(record))


def setup_logging() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    log = logging.getLogger("bms")
    log.setLevel(logging.INFO)

    # Bounded, rotated file log
    fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES,
                             backupCount=LOG_BACKUPS, encoding="utf-8")
    fh.setFormatter(_PlainFormatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)

    # Live console view (screen session shows this)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    log.addHandler(ch)
    return log


def extract(readings) -> dict:
    """Flatten JkReadings into the small JSON payload for the DB logger."""
    cell = readings.cell
    if cell is None:
        raise RuntimeError("no cell frame in readings")

    cells = list(cell.cells or [])
    active = int(cell.cells_active or 0)
    if 0 < active <= len(cells):
        cells = cells[:active]  # drop unused trailing slots (zeros)

    return {
        "timestamp": readings.timestamp,
        "battery_voltage_V": cell.battery_voltage_V,
        "current_A": cell.current_A,
        "power_W": cell.power_W,
        "soc": cell.soc,
        "capacity_remaining_Ah": cell.capacity_remaining_Ah,
        "nominal_capacity_Ah": cell.nominal_capacity_Ah,
        "soh": cell.soh,
        "cycles": cell.cycles,
        "cells_active": active,
        "cell_high_V": cell.high_v,
        "cell_low_V": cell.low_v,
        "cell_delta_mV": cell.delta_cell_mV,
        "cell_avg_mV": cell.avg_cell_mV,
        "mos_temp_C": cell.mos_temp_C,
        "t1_C": cell.t1_C,
        "t2_C": cell.t2_C,
        "balance_current_A": cell.balance_current_A,
        "balancing": bool(cell.balancing),
        "charge_mosfet": bool(cell.charge_mosfet),
        "discharge_mosfet": bool(cell.discharge_mosfet),
        "charge_status": cell.charge_status,
        "errors": cell.errors or [],
        "cells": cells,
    }


def _f(v, nd=2):
    """Format a float, tolerating None."""
    if v is None:
        return "?"
    return f"{v:.{nd}f}"


def status_lines(p: dict, colored: bool = True):
    """Build the two-line human status readout."""
    def C(s, c):
        return f"{c}{s}{RESET}" if colored else str(s)

    v = p.get("battery_voltage_V")
    i = p.get("current_A")
    soc = p.get("soc")
    errs = p.get("errors") or []

    v_s = C(f"V={_f(v)}V", GREEN)
    i_s = C(f"I={_f(i)}A", YELLOW if (i or 0) < 0 else GREEN)
    p_s = f"P={_f(p.get('power_W'), 0)}W"
    soc_color = RED if (soc or 100) < 20 else YELLOW if (soc or 100) < 50 else GREEN
    soc_s = C(f"SOC={soc if soc is not None else '?'}%", soc_color)
    cap_s = (f"cap={_f(p.get('capacity_remaining_Ah'), 1)}/"
             f"{_f(p.get('nominal_capacity_Ah'), 0)}Ah")
    soh_s = f"SOH={p.get('soh', '?')}%"
    cyc_s = f"cyc={p.get('cycles', '?')}"
    cells_s = C(f"cells={p.get('cells_active', '?')}", CYAN)
    hi_lo_s = (f"hi={_f(p.get('cell_high_V'), 3)} "
               f"lo={_f(p.get('cell_low_V'), 3)} "
               f"avg={p.get('cell_avg_mV', '?')}mV "
               f"d={p.get('cell_delta_mV', '?')}mV")
    temps = (f"Tmos={_f(p.get('mos_temp_C'), 1)} "
             f"t1={_f(p.get('t1_C'), 1)} t2={_f(p.get('t2_C'), 1)}C")
    bal = p.get("balancing")
    bal_s = (C(f"bal=ON({_f(p.get('balance_current_A'))}A)", CYAN) if bal
             else "bal=off")
    mos_s = (f"chgMOS={'on' if p.get('charge_mosfet') else 'off'} "
             f"disMOS={'on' if p.get('discharge_mosfet') else 'off'}")
    chg = p.get("charge_status")
    chg_s = f"phase={chg}" if chg else ""
    err_s = C("err=" + (",".join(errs) if errs else "none"),
              RED if errs else GREEN)

    line1 = " | ".join(x for x in
                       (v_s, i_s, p_s, soc_s, soh_s, cap_s, cyc_s, cells_s,
                        hi_lo_s, temps, bal_s, mos_s, chg_s, err_s) if x)
    cells_v = p.get("cells") or []
    line2 = "cells[V]: " + " ".join(f"{c:.3f}" for c in cells_v)
    return line1, line2


def main():
    log = setup_logging()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.will_set(TOPIC_ONLINE, "0", retain=True)  # LWT: daemon died
    client.connect(BROKER, PORT, 60)
    client.loop_start()
    client.publish(TOPIC_ONLINE, "1", retain=True)
    log.info(f"bms_mqtt: polling {MAC} every {POLL_INTERVAL:.0f}s -> "
             f"{BROKER}:{PORT}{TOPIC_STATUS} | log={LOG_FILE} "
             f"(max {LOG_MAX_BYTES}B x {LOG_BACKUPS + 1})")

    failures = 0
    while True:
        start = time.monotonic()
        try:
            readings = read_live(MAC, pin=PIN)
            payload = extract(readings)
            client.publish(TOPIC_STATUS, json.dumps(payload))
            line1, line2 = status_lines(payload)
            log.info(line1)
            log.info(line2)
            failures = 0
        except Exception as e:
            failures += 1
            backoff = min(POLL_INTERVAL * (1 + failures), MAX_BACKOFF)
            log.error(f"BMS READ FAILED (#{failures}): {e} | "
                      f"retrying in {backoff:.0f}s")
            # Publish the outage so the logger / dashboards can see it
            try:
                client.publish(TOPIC_STATUS, json.dumps({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime()),
                    "error": str(e),
                }))
            except Exception as pe:
                log.error(f"publish of error payload failed: {pe}")
            time.sleep(backoff)
            continue

        delay = max(0.0, POLL_INTERVAL - (time.monotonic() - start))
        time.sleep(delay)


if __name__ == "__main__":
    main()
