#!/usr/bin/env python3
"""BMS MQTT -> DB logger (runs on the measurement Pi, next to the DB writer).

Subscribes to bms_jk/status on the broker and stores every reading into
the MariaDB bms_jk table. Kept as a separate process from smainbat.py so
a BLE/BMS outage can never stall the control loop, and vice versa.

Run in a screen session:
  screen -S bms -dm bash -c 'cd /home/pi/Desktop/prog/measurement && exec python3 -u bms_db_logger.py > /tmp/bms_db.log 2>&1'

Environment overrides:
  BMS_BROKER   MQTT broker  (default 192.168.2.42)
  DB_*          same as smainbat.py (host/user/password/database)
"""
import json
import os
import time

import paho.mqtt.client as mqtt

from lib.BmsStorage import BmsStorage

BROKER = os.environ.get("BMS_BROKER", "192.168.2.42")
PORT = 1883
TOPIC_STATUS = "bms_jk/status"
TOPIC_ONLINE = "bms_jk/online"

DB = {
    "host": os.environ.get("DB_HOST", "192.168.2.33"),
    "user": os.environ.get("DB_USER", "admin"),
    "password": os.environ.get("DB_PASSWORD", "aaa"),
    "database": os.environ.get("DB_DATABASE", "energy"),
}

storage = None
last_db_attempt = 0.0
DB_RECONNECT_COOLDOWN = 5.0


def get_storage():
    global storage, last_db_attempt
    now = time.time()
    if storage is not None:
        return storage
    if now - last_db_attempt < DB_RECONNECT_COOLDOWN:
        return None
    last_db_attempt = now
    try:
        s = BmsStorage(**DB)
        if s.connection is not None and s.cursor is not None:
            storage = s
            print("Database connection established")
        else:
            s.close()
    except Exception as e:
        print(f"WARNING: DB connect failed: {e}")
    return storage


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(TOPIC_STATUS)
        print(f"subscribed to {TOPIC_STATUS} on {BROKER}")
    else:
        print(f"MQTT connect failed: {reason_code}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"bad payload on {msg.topic}: {e}")
        return

    if msg.topic == TOPIC_ONLINE:
        print(f"bms bridge online={payload}")
        return

    s = get_storage()
    if s is None:
        return
    if s.store(payload):
        ts = payload.get("timestamp", "?")
        print(f"stored: {ts} V={payload.get('battery_voltage_V')} "
              f"I={payload.get('current_A')} soc={payload.get('soc')}%")
    else:
        print("store failed (connection state logged above)")


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    client.loop_forever()


if __name__ == "__main__":
    main()
