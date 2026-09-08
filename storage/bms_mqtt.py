#!/usr/bin/env python3
"""BMS -> MQTT bridge (runs on the storage Pi, near the JK BMS).

Polls the JK BMS over BLE every POLL_INTERVAL seconds and publishes the
decoded state as JSON to the local MQTT broker on topic bms_jk/status.
The measurement Pi runs bms_db_logger.py which subscribes and stores rows
into the MariaDB bms_jk table.

Run in a screen session:
  screen -S bms -dm bash -c 'cd /home/pi/Desktop/storage && exec python3 -u bms_mqtt.py > /tmp/bms_mqtt.log 2>&1'

Environment overrides:
  BMS_MAC          BLE MAC of the JK BMS   (default C8:47:80:58:A3:A6)
  JK_PIN           bonding PIN             (default 1234)
  BMS_POLL_SECONDS poll interval           (default 30)
  BMS_BROKER       MQTT broker             (default 127.0.0.1)
"""
import json
import os
import sys
import time

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
        "errors": cell.errors or [],
        "cells": cells,
    }


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.will_set(TOPIC_ONLINE, "0", retain=True)  # LWT: daemon died
    client.connect(BROKER, PORT, 60)
    client.loop_start()
    client.publish(TOPIC_ONLINE, "1", retain=True)
    print(f"bms_mqtt: polling {MAC} every {POLL_INTERVAL}s -> {BROKER}:{PORT}{TOPIC_STATUS}")

    failures = 0
    while True:
        start = time.monotonic()
        try:
            readings = read_live(MAC, pin=PIN)
            payload = extract(readings)
            client.publish(TOPIC_STATUS, json.dumps(payload))
            failures = 0
            print(f"published: V={payload['battery_voltage_V']} "
                  f"I={payload['current_A']} soc={payload['soc']}% "
                  f"cells={payload['cells_active']} "
                  f"errors={payload['errors'] or 'none'}")
        except Exception as e:
            failures += 1
            backoff = min(POLL_INTERVAL * (1 + failures), 300)
            print(f"read failed ({failures}x): {e}; backing off {backoff:.0f}s")
            # Report the outage on the status topic so the logger can see it
            client.publish(TOPIC_STATUS, json.dumps({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "error": str(e),
            }), retain=False)
            time.sleep(backoff)
            continue

        delay = max(0.0, POLL_INTERVAL - (time.monotonic() - start))
        time.sleep(delay)


if __name__ == "__main__":
    main()
