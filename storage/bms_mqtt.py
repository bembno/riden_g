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

Diagnostics / watchdog (24 h test run): every main-loop iteration appends
a JSON line to abms_log.txt (cycle result, BLE read duration, backoff,
failure counters, RSS, thread count, CPU time, BlueZ adapter state and
the jkbms phase timings). A watchdog thread writes heartbeat records and,
if the loop makes no progress for WATCHDOG_STUCK_S seconds (or spins
tightly without ever completing a successful read), dumps thread stacks
plus BlueZ state to abms_log.txt and restarts the process via os.execv.
Normal operation and legitimate long backoffs (up to MAX_BACKOFF) never
trigger a reset - see bms_watchdog.py for the threshold math.

Environment overrides:
  BMS_MAC            BLE MAC of the JK BMS    (default C8:47:80:58:A3:A6)
  JK_PIN             bonding PIN              (default 1234)
  BMS_POLL_SECONDS   poll interval            (default 120 = every 2 min)
  BMS_BROKER         MQTT broker              (default 127.0.0.1)
  BMS_LOG_DIR        log directory            (default <script dir>/logs)
  BMS_LOG_MAXBYTES   rotate size in bytes     (default 1048576)
  BMS_LOG_BACKUPS    rotated files to keep    (default 2)
  BMS_DIAG_FILE      diagnostics JSONL file   (default <script dir>/abms_log.txt)
  BMS_DIAG_HOURS     diagnostics window       (default 24)
  BMS_DIAG_MAXBYTES  diagnostics size cap     (default 8388608)
  BMS_DIAG_UNTIL     absolute diag end (set automatically across execv)
  BMS_WATCHDOG_STUCK_S  no-progress reset threshold (default 600)
  BMS_WATCHDOG_CHECK_S  watchdog cadence           (default 30)
  BMS_WATCHDOG_HB_S     heartbeat cadence          (default 120)
"""
import json
import logging
import os
import random
import re
import signal
import subprocess
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from logging.handlers import RotatingFileHandler

import paho.mqtt.client as mqtt

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

# jkbms library lives next to this script in the repo (storage/bms_jk)
# or as a standalone checkout at /home/pi/Desktop/bms_jk on the Pi
_HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (os.path.join(_HERE, "bms_jk"), "/home/pi/Desktop/bms_jk"):
    if os.path.isdir(_p):
        sys.path.insert(0, _p)
        break

from jkbms import read_live  # noqa: E402  (path setup above)
import jkbms.client as _jk_client  # noqa: E402  (LAST_DIAG phase timings)

from bms_watchdog import (  # noqa: E402
    LoopRateDetector, WatchdogConfig, check_progress, heartbeat_due)

MAC = os.environ.get("BMS_MAC", "C8:47:80:58:A3:A6")
PIN = os.environ.get("JK_PIN", "1234")
POLL_INTERVAL = float(os.environ.get("BMS_POLL_SECONDS", "120"))
BROKER = os.environ.get("BMS_BROKER", "127.0.0.1")
PORT = 1883
TOPIC_STATUS = "bms_jk/status"
TOPIC_ONLINE = "bms_jk/online"

LOG_DIR = os.environ.get("BMS_LOG_DIR", os.path.join(_HERE, "logs"))
LOG_FILE = os.path.join(LOG_DIR, "bms_mqtt.log")
LOG_MAX_BYTES = int(os.environ.get("BMS_LOG_MAXBYTES", str(1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("BMS_LOG_BACKUPS", "2"))

MAX_BACKOFF = 300.0
BACKOFF_JITTER = 5.0  # seconds

# Hard deadline for one BLE read cycle. bleak/BlueZ DBus calls can hang
# indefinitely (observed in production: bridge silent for 10 h); this
# watchdog restarts the process to clear the stuck BlueZ state.
READ_HARD_TIMEOUT = 120.0
# Consecutive hard timeouts before a full process restart
RESTART_AFTER_HARD_TIMEOUTS = 2

# --- diagnostics: JSON lines appended to DIAG_FILE for DIAG_HOURS ---
DIAG_FILE = os.environ.get(
    "BMS_DIAG_FILE", os.path.join(_HERE, "abms_log.txt"))
DIAG_HOURS = float(os.environ.get("BMS_DIAG_HOURS", "24"))
DIAG_MAX_BYTES = int(os.environ.get("BMS_DIAG_MAXBYTES", str(8 * 1024 * 1024)))
# Absolute end of the diagnostics window. Preserved across os.execv
# restarts via BMS_DIAG_UNTIL so a reset never silently extends the
# 24 h test window.
_DIAG_END = float(os.environ.get("BMS_DIAG_UNTIL") or 0.0) \
    or (time.time() + DIAG_HOURS * 3600)
_diag_capped_logged = False
_diag_end_logged = False

# Watchdog thresholds. stuck_s must stay above WatchdogConfig.worst_legit_gap_s
# (~305 s of error backoff or ~130 s of BLE read) so normal outages and
# legitimate long-running reads never reset the bridge.
WATCHDOG = WatchdogConfig(
    stuck_s=float(os.environ.get("BMS_WATCHDOG_STUCK_S", "600")),
    check_s=float(os.environ.get("BMS_WATCHDOG_CHECK_S", "30")),
    hb_s=float(os.environ.get("BMS_WATCHDOG_HB_S", "120")),
    poll_interval_s=POLL_INTERVAL,
    read_hard_timeout_s=READ_HARD_TIMEOUT,
    max_backoff_s=MAX_BACKOFF,
    backoff_jitter_s=BACKOFF_JITTER,
)

# Shared between the main loop, the watchdog thread and the restart path.
STATE = {
    "pid": os.getpid(),
    "started_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    "main_ident": 0,
    "cycles": 0,
    "failures": 0,
    "hard_timeouts": 0,
    "last_progress": time.time(),
    "last_success": 0.0,
    "last_error": None,
    "last_backoff": 0.0,
    "reset_attempts": 0,
}

_mqtt_client = None  # set in main(); used by _restart_process from watchdog
_read_thread = None   # current/last BLE worker (single-flight guard)

# Prometheus metrics
if PROMETHEUS_AVAILABLE:
    BLE_READS_TOTAL = Counter('bms_ble_reads_total', 'Total BLE read attempts', ['result'])
    BLE_READ_DURATION = Histogram('bms_ble_read_duration_seconds', 'BLE read duration')
    BLE_BACKOFF_SECONDS = Gauge('bms_ble_backoff_seconds', 'Current backoff duration')
    MQTT_PUBLISH_TOTAL = Counter('bms_mqtt_publish_total', 'Total MQTT publishes', ['topic', 'result'])
    BMS_VOLTAGE = Gauge('bms_battery_voltage', 'Battery voltage (V)')
    BMS_CURRENT = Gauge('bms_battery_current', 'Battery current (A)')
    BMS_SOC = Gauge('bms_soc', 'State of charge (%)')
    BMS_CELL_DELTA_MV = Gauge('bms_cell_delta_mv', 'Cell voltage delta (mV)')
    BMS_MOS_TEMP = Gauge('bms_mos_temperature', 'MOS temperature (C)')
    BMS_BALANCE_CURRENT = Gauge('bms_balance_current', 'Balance current (A)')
    BMS_CYCLES = Gauge('bms_cycles', 'Cycle count')
    BMS_SOH = Gauge('bms_soh', 'State of health (%)')
    BMS_ERRORS = Gauge('bms_errors', 'Number of active errors')

_shutdown = False


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True


def _on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.publish(TOPIC_ONLINE, "1", retain=True)
    else:
        logging.getLogger("bms").error(f"MQTT connect failed: {reason_code}")


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    logging.getLogger("bms").warning(f"MQTT disconnected (code {reason_code})")

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


def read_live_with_timeout(mac, pin, timeout=READ_HARD_TIMEOUT):
    """Run a BLE read in a daemon thread with a hard deadline.

    A raw daemon thread is used instead of ThreadPoolExecutor on purpose:
    the executor's __exit__ calls shutdown(wait=True) and would block the
    main thread forever when the worker is hung in an uninterruptible
    BlueZ/DBus call - that exact hang was observed in production as a
    bridge that stayed alive but went silent.  The daemon worker dies
    with the process; os.execv on repeated hangs clears BlueZ state.

    Only one worker is allowed at a time: if the previous attempt is
    still hung when the next cycle starts, TimeoutError is raised
    immediately instead of opening a second concurrent BLE connection
    (and instead of leaking a new thread every cycle).
    """
    global _read_thread
    if _read_thread is not None and _read_thread.is_alive():
        _read_thread.join(1.0)
        if _read_thread.is_alive():
            raise TimeoutError(
                "previous BLE read worker still hung (BlueZ/DBus leak)")

    box = {}

    def _worker():
        try:
            box["readings"] = read_live(mac, pin=pin)
        except BaseException as e:  # noqa: BLE001 - propagate to joiner
            box["error"] = e

    t = threading.Thread(target=_worker, name="bms-read", daemon=True)
    _read_thread = t
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"BLE read exceeded {timeout}s (BlueZ/DBus hang?)")
    if "error" in box:
        raise box["error"]
    return box["readings"]


# ---------------------------------------------------------------------------
# Diagnostic file & watchdog helpers (shared between main() and watchdog)
# ---------------------------------------------------------------------------

def _bluez_state():
    """Adapter state: power control sysfs + hciconfig (address/UP) + service."""
    out = {"powered": None, "power_control": None, "hci_address": None,
           "bluetooth_service": None}
    try:
        with open("/sys/class/bluetooth/hci0/device/power/control") as f:
            out["power_control"] = f.read().strip()
    except Exception:
        pass
    try:
        r = subprocess.run(  # fast local ioctl; gives BD address + UP/RUNNING
            ["hciconfig", "hci0"],
            capture_output=True, text=True, timeout=5,
        )
        text = r.stdout or ""
        out["powered"] = "UP RUNNING" in text
        for line in text.splitlines():
            if line.strip().startswith("BD Address:"):
                out["hci_address"] = line.split(":", 1)[1].strip().split()[0]
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "bluetooth"],
            capture_output=True, text=True, timeout=5,
        )
        out["bluetooth_service"] = r.stdout.strip() or None
    except Exception:
        pass
    return out


def _rss_kb():
    """Resident set size in kB from /proc/self/status (Linux)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except Exception:
        pass
    return None


def _cpu_s():
    """Cumulative process CPU time in seconds from /proc/self/stat."""
    try:
        with open("/proc/self/stat") as f:
            parts = f.read().split()
        ticks = int(parts[13]) + int(parts[14])  # utime + stime
        return round(ticks / os.sysconf("SC_CLK_TCK"), 1)
    except Exception:
        return None


def _thread_stacks():
    """Compact stack summaries of all live threads.

    Identifies the main-loop thread via STATE['main_ident'] so a stuck
    main thread (and the BlueZ call it is blocked in) is obvious in the
    dump written before a reset.
    """
    ident2name = {t.ident: t.name for t in threading.enumerate()}
    main_ident = STATE["main_ident"]
    stacks = {}
    for tid, frame in sys._current_frames().items():
        stacks[str(tid)] = {
            "name": ident2name.get(tid, "?"),
            "main_loop": tid == main_ident,
            "frames": [ln.strip() for ln in
                       traceback.format_stack(frame, limit=12)],
        }
    return stacks


def _diag_snapshot():
    """Everything the watchdog wants in a heartbeat / reset record."""
    now = time.time()
    try:
        jk = dict(_jk_client.LAST_DIAG)
    except Exception:
        jk = {}
    return {
        "cycles": STATE["cycles"],
        "failures": STATE["failures"],
        "hard_timeouts": STATE["hard_timeouts"],
        "progress_age_s": round(now - STATE["last_progress"], 1),
        "success_age_s": (round(now - STATE["last_success"], 1)
                          if STATE["last_success"] else None),
        "last_error": STATE["last_error"],
        "last_backoff_s": STATE["last_backoff"],
        "reset_attempts": STATE["reset_attempts"],
        "rss_kb": _rss_kb(),
        "cpu_s": _cpu_s(),
        "threads": threading.active_count(),
        "jkbms": jk,
        "bluez": _bluez_state(),
    }


def _diag_write(rec):
    """Append one JSON line to the diagnostics file while the window is open.

    The file is hard-capped at DIAG_MAX_BYTES so a runaway process can
    never fill the Pi's disk; the cap and the window expiry are logged
    once each.
    """
    global _diag_capped_logged, _diag_end_logged
    now = time.time()
    if now >= _DIAG_END:
        if not _diag_end_logged:
            _diag_end_logged = True
            logging.getLogger("bms").info(
                f"diagnostics window closed ({DIAG_HOURS:g} h); "
                f"no more records in {DIAG_FILE}")
        return
    if os.path.exists(DIAG_FILE) and os.path.getsize(DIAG_FILE) >= DIAG_MAX_BYTES:
        if not _diag_capped_logged:
            _diag_capped_logged = True
            logging.getLogger("bms").warning(
                f"diagnostics file {DIAG_FILE} reached {DIAG_MAX_BYTES} B cap; "
                f"no more records")
        return
    try:
        with open(DIAG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
    except Exception as e:
        logging.getLogger("bms").warning(f"diag write failed: {e}")


def _write_cycle_diag(seq, result, err, read_ms, backoff, payload=None):
    """One JSON-line record per main-loop iteration - the core of the 24 h test."""
    rec = {
        "type": "cycle",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "seq": seq,
        "result": result,
        "read_ms": round(read_ms, 1) if read_ms is not None else None,
        "backoff_s": round(backoff, 1),
        "state": {
            "failures": STATE["failures"],
            "hard_timeouts": STATE["hard_timeouts"],
            "last_error": STATE["last_error"],
        },
        "sys": {
            "rss_kb": _rss_kb(),
            "cpu_s": _cpu_s(),
            "threads": threading.active_count(),
        },
        "bluez": _bluez_state(),
    }
    if err is not None:
        rec["error"] = err
    if payload is not None:
        rec["bms"] = {
            "v": payload.get("battery_voltage_V"),
            "i": payload.get("current_A"),
            "soc": payload.get("soc"),
        }
    try:
        rec["diag"] = dict(_jk_client.LAST_DIAG)
    except Exception:
        pass
    _diag_write(rec)


def _mark_progress():
    """Tell the watchdog the main loop completed a step this iteration."""
    STATE["last_progress"] = time.time()


def _restart_process(reason: str):
    """Dump diagnostics to abms_log.txt, then restart via os.execv.

    Always logs + writes the reset record BEFORE restarting so the cause
    can be post-analysed.  execv keeps the same screen session ('bms')
    and log files.  If execv somehow returns/fails, progress is bumped so
    the watchdog retries after another stuck window instead of spinning.
    """
    global _mqtt_client, STATE
    STATE["last_error"] = reason
    log = logging.getLogger("bms")
    log.error(f"RESTARTING bms_mqtt process ({reason})")

    rec = {
        "type": "reset",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "reason": reason,
        "pid": STATE["pid"],
        "started_at": STATE["started_at"],
        "sys": {
            "rss_kb": _rss_kb(),
            "cpu_s": _cpu_s(),
            "threads": threading.active_count(),
        },
        "bluez": _bluez_state(),
        "stacks": _thread_stacks(),
    }
    rec.update(_diag_snapshot())
    _diag_write(rec)

    try:
        if _mqtt_client is not None:
            _mqtt_client.publish(TOPIC_ONLINE, "0", retain=True)
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()
    except Exception:
        pass
    time.sleep(1)

    env = dict(os.environ)
    env["BMS_DIAG_UNTIL"] = str(int(_DIAG_END))
    try:
        os.execve(sys.executable, [sys.executable, "-u"] + sys.argv, env)
    except Exception as e:
        STATE["reset_attempts"] += 1
        STATE["last_progress"] = time.time()  # retry after another window
        log.error(f"os.execv failed ({e}); continuing with reset_attempts="
                  f"{STATE['reset_attempts']}")


def _watchdog():
    """Background thread: heartbeat records + stuck / tight-loop detection.

    Only fires when the loop has genuinely made no progress for
    WATCHDOG_STUCK_S (> worst legitimate gap, see bms_watchdog.WatchdogConfig)
    or when it spins several times faster than POLL_INTERVAL allows without
    a single successful read - so normal operation and legitimate long
    reads/backoffs never reset the bridge.
    """
    detector = LoopRateDetector(WATCHDOG)
    last_hb = time.time()
    while not _shutdown:
        time.sleep(max(5.0, WATCHDOG.check_s))
        if _shutdown:
            break
        now = time.time()

        if heartbeat_due(last_hb, now, WATCHDOG):
            last_hb = now
            _diag_write({
                "type": "heartbeat",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                **_diag_snapshot(),
            })

        reason = check_progress(STATE["last_progress"], now, WATCHDOG)
        if reason is None:
            reason = detector.observe(STATE["cycles"], STATE["last_success"],
                                      now)
        if reason is not None:
            logging.getLogger("bms").error(f"WATCHDOG: {reason} -- "
                                           f"dumping diagnostics")
            _restart_process(reason)


def main():
    global _mqtt_client
    log = setup_logging()
    _mqtt_client = None  # set below; watchdog restart path reads this global
    STATE["main_ident"] = threading.get_ident()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.will_set(TOPIC_ONLINE, "0", retain=True)
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect
    client.connect(BROKER, PORT, 60)
    client.loop_start()
    client.publish(TOPIC_ONLINE, "1", retain=True)
    _mqtt_client = client
    log.info(f"bms_mqtt: polling {MAC} every {POLL_INTERVAL:.0f}s -> "
             f"{BROKER}:{PORT}{TOPIC_STATUS} | log={LOG_FILE} "
             f"(max {LOG_MAX_BYTES}B x {LOG_BACKUPS + 1})")
    log.info(f"diagnostics: {DIAG_FILE} for {DIAG_HOURS:g} h "
             f"(cap {DIAG_MAX_BYTES} B, until "
             f"{time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(_DIAG_END))}) "
             f"| watchdog: stuck>{WATCHDOG.stuck_s:.0f}s, "
             f"check {WATCHDOG.check_s:.0f}s, hb {WATCHDOG.hb_s:.0f}s "
             f"(worst legit gap {WATCHDOG.worst_legit_gap_s:.0f}s)")

    # First record of the 24 h window: config + environment (no secrets).
    _diag_write({
        "type": "boot",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "pid": STATE["pid"],
        "diag_until": time.strftime("%Y-%m-%dT%H:%M:%S",
                                    time.localtime(_DIAG_END)),
        "config": {
            "mac": MAC,
            "poll_interval_s": POLL_INTERVAL,
            "read_hard_timeout_s": READ_HARD_TIMEOUT,
            "max_backoff_s": MAX_BACKOFF,
            "restart_after_hard_timeouts": RESTART_AFTER_HARD_TIMEOUTS,
            "watchdog_stuck_s": WATCHDOG.stuck_s,
            "watchdog_check_s": WATCHDOG.check_s,
            "watchdog_hb_s": WATCHDOG.hb_s,
            "worst_legit_gap_s": WATCHDOG.worst_legit_gap_s,
            "diag_max_bytes": DIAG_MAX_BYTES,
        },
        "sys": {"rss_kb": _rss_kb(), "cpu_s": _cpu_s(),
                "threads": threading.active_count()},
        "bluez": _bluez_state(),
    })

    # Watchdog: heartbeats + stuck / tight-loop detection (see _watchdog).
    threading.Thread(target=_watchdog, daemon=True,
                     name="bms-watchdog").start()

    # Start Prometheus metrics HTTP server
    if PROMETHEUS_AVAILABLE:
        METRICS_PORT = int(os.environ.get("BMS_METRICS_PORT", "9100"))

        class MetricsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/metrics":
                    self.send_response(200)
                    self.send_header("Content-Type", CONTENT_TYPE_LATEST)
                    self.end_headers()
                    self.wfile.write(generate_latest())
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, format, *args):
                pass  # Suppress default HTTP log

        metrics_server = HTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
        metrics_thread = threading.Thread(target=metrics_server.serve_forever, daemon=True)
        metrics_thread.start()
        log.info(f"Prometheus metrics on :{METRICS_PORT}/metrics")

    failures = 0
    hard_timeouts = 0
    while not _shutdown:
        start = time.monotonic()
        STATE["cycles"] += 1
        seq = STATE["cycles"]
        result, err, read_ms, backoff = "ok", None, None, 0.0
        _mark_progress()
        try:
            read_start = time.monotonic()
            readings = read_live_with_timeout(MAC, pin=PIN)
            read_ms = (time.monotonic() - read_start) * 1000.0
            if readings.cell is None:
                raise RuntimeError("no cell frame in readings")

            payload = extract(readings)
            client.publish(TOPIC_STATUS, json.dumps(payload))
            if PROMETHEUS_AVAILABLE:
                MQTT_PUBLISH_TOTAL.labels(topic=TOPIC_STATUS, result='success').inc()

            line1, line2 = status_lines(payload)
            log.info(line1)
            log.info(line2)

            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result='success').inc()
                BLE_READ_DURATION.observe(read_ms / 1000.0)
                cell = readings.cell
                BMS_VOLTAGE.set(cell.battery_voltage_V)
                BMS_CURRENT.set(cell.current_A)
                BMS_SOC.set(cell.soc)
                BMS_CELL_DELTA_MV.set(cell.delta_cell_mV)
                BMS_MOS_TEMP.set(cell.mos_temp_C or 0)
                BMS_BALANCE_CURRENT.set(cell.balance_current_A or 0)
                BMS_CYCLES.set(cell.cycles or 0)
                BMS_SOH.set(cell.soh or 0)
                BMS_ERRORS.set(len(cell.errors or []))

            failures = 0
            hard_timeouts = 0
            STATE["failures"] = 0
            STATE["hard_timeouts"] = 0
            STATE["last_success"] = time.time()
            STATE["last_error"] = None
            _mark_progress()
            _write_cycle_diag(seq, result, err, read_ms, backoff, payload)

            delay = max(0.0, POLL_INTERVAL - (time.monotonic() - start))
            time.sleep(delay)
            _mark_progress()
            continue

        except TimeoutError as te:
            result, err = "timeout", str(te)
            if read_ms is None:
                read_ms = (time.monotonic() - read_start) * 1000.0
            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result='timeout').inc()
            # bleak hung on a DBus call - retrying in-process often stays
            # stuck; restart the whole process after N consecutive hangs
            # (_restart_process uses os.execv: same screen session/logs).
            hard_timeouts += 1
            STATE["hard_timeouts"] = hard_timeouts
            STATE["last_error"] = err
            log.error(f"BLE HARD TIMEOUT ({hard_timeouts}/"
                      f"{RESTART_AFTER_HARD_TIMEOUTS}): {te}")
            _mark_progress()
            _write_cycle_diag(seq, result, err, read_ms, backoff)
            if hard_timeouts >= RESTART_AFTER_HARD_TIMEOUTS:
                _restart_process(
                    f"hard timeout x{hard_timeouts}: {te}")
            time.sleep(POLL_INTERVAL)
            _mark_progress()
            continue

        except Exception as e:
            result, err = "error", str(e)
            if read_ms is None:
                read_ms = (time.monotonic() - read_start) * 1000.0
            failures += 1
            STATE["failures"] = failures
            STATE["last_error"] = err
            backoff = min(POLL_INTERVAL * (1 + failures) + random.uniform(0, BACKOFF_JITTER), MAX_BACKOFF)
            STATE["last_backoff"] = backoff
            if PROMETHEUS_AVAILABLE:
                BLE_READS_TOTAL.labels(result='error').inc()
                BLE_BACKOFF_SECONDS.set(backoff)
            log.error(f"BMS READ FAILED (#{failures}): {e} | "
                      f"retrying in {backoff:.0f}s")
            try:
                client.publish(TOPIC_STATUS, json.dumps({
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime()),
                    "error": str(e),
                }))
                if PROMETHEUS_AVAILABLE:
                    MQTT_PUBLISH_TOTAL.labels(topic=TOPIC_STATUS, result='error').inc()
            except Exception as pe:
                log.error(f"publish of error payload failed: {pe}")
            _mark_progress()
            _write_cycle_diag(seq, result, err, read_ms, backoff)
            time.sleep(backoff)
            _mark_progress()
            continue

    log.info("Shutdown signal received, cleaning up...")
    client.publish(TOPIC_ONLINE, "0", retain=True)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
