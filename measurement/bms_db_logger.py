#!/usr/bin/env python3
"""BMS MQTT -> DB logger (runs on the measurement Pi, next to the DB writer).

Subscribes to bms_jk/status on the broker and stores every reading into
the MariaDB bms_jk table. Kept as a separate process from smainbat.py so
a BLE/BMS outage can never stall the control loop, and vice versa.

The log file can never grow unbounded: a RotatingFileHandler caps it at
BMS_LOG_MAXBYTES (default 1 MB) and keeps BMS_LOG_BACKUPS (default 2)
rotated copies.

Outage handling:
- error payloads (BLE outage reports from the bridge) are logged, not stored
- MQTT disconnects auto-reconnect via paho; a broker outage cannot crash us
- DB outages degrade to 'store failed' and retry with cooldown

Environment overrides:
  BMS_BROKER    MQTT broker  (default 192.168.2.42)
  DB_*          same as smainbat.py (host/user/password/database)
  BMS_LOG_*     log dir / max bytes / backups (see BmsConfig)
"""
import json
import logging
import os
import signal
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from logging.handlers import RotatingFileHandler

import paho.mqtt.client as mqtt

try:
    from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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

_HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.environ.get("BMS_LOG_DIR", os.path.join(_HERE, "logs"))
LOG_FILE = os.path.join(LOG_DIR, "bms_db.log")
LOG_MAX_BYTES = int(os.environ.get("BMS_LOG_MAXBYTES", str(1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("BMS_LOG_BACKUPS", "2"))

log = logging.getLogger("bmsdb")

storage = None
last_db_attempt = 0.0
DB_RECONNECT_COOLDOWN = 5.0
error_streak = 0
_shutdown = False

# Prometheus metrics
if PROMETHEUS_AVAILABLE:
    DB_STORES_TOTAL = Counter('bms_db_stores_total', 'Total DB store attempts', ['result'])
    DB_STORE_DURATION = Histogram('bms_db_store_duration_seconds', 'DB store duration')
    MQTT_MESSAGES_TOTAL = Counter('bms_mqtt_messages_total', 'Total MQTT messages received', ['topic', 'type'])
    DB_CONNECTION_STATUS = Gauge('bms_db_connection_status', 'DB connection status (1=connected)')
    DB_LATENCY_SECONDS = Gauge('bms_db_latency_seconds', 'Time between BMS timestamp and DB insert')


def _signal_handler(signum, frame):
    global _shutdown
    _shutdown = True


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    log.setLevel(logging.INFO)
    fh = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES,
                             backupCount=LOG_BACKUPS, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(fh)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    log.addHandler(ch)


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
            log.info("database connection established")
        else:
            s.close()
    except Exception as e:
        log.error(f"db connect failed: {e}")
    return storage


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe(TOPIC_STATUS)
        log.info(f"subscribed to {TOPIC_STATUS} on {BROKER}")
    else:
        log.error(f"MQTT connect failed: {reason_code}")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    log.warning(f"MQTT disconnected (code {reason_code}), paho will reconnect...")


def on_message(client, userdata, msg):
    global error_streak
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        log.error(f"bad payload on {msg.topic}: {e}")
        if PROMETHEUS_AVAILABLE:
            MQTT_MESSAGES_TOTAL.labels(topic=msg.topic, type='parse_error').inc()
        return

    if msg.topic == TOPIC_ONLINE:
        log.info(f"bms bridge online={payload}")
        if PROMETHEUS_AVAILABLE:
            MQTT_MESSAGES_TOTAL.labels(topic=TOPIC_ONLINE, type='online').inc()
        return

    # Outage report from the bridge: log it, never store, never crash
    if "battery_voltage_V" not in payload:
        error_streak += 1
        log.warning(f"BMS OUTAGE reported by bridge "
                    f"(#{error_streak}): {payload.get('error', '?')}")
        if PROMETHEUS_AVAILABLE:
            MQTT_MESSAGES_TOTAL.labels(topic=TOPIC_STATUS, type='outage').inc()
        return

    error_streak = 0
    if PROMETHEUS_AVAILABLE:
        MQTT_MESSAGES_TOTAL.labels(topic=TOPIC_STATUS, type='data').inc()

    s = get_storage()
    if s is None:
        log.warning("no DB connection; reading dropped")
        if PROMETHEUS_AVAILABLE:
            DB_STORES_TOTAL.labels(result='no_connection').inc()
        return
    
    if PROMETHEUS_AVAILABLE:
        DB_CONNECTION_STATUS.set(1)
    
    store_start = time.monotonic()
    if s.store(payload):
        log.info(f"stored: {payload.get('timestamp', '?')} "
                 f"V={payload.get('battery_voltage_V')} "
                 f"I={payload.get('current_A')} soc={payload.get('soc')}%")
        if PROMETHEUS_AVAILABLE:
            DB_STORES_TOTAL.labels(result='success').inc()
            DB_STORE_DURATION.observe(time.monotonic() - store_start)
            # Calculate latency between BMS timestamp and DB insert
            try:
                bms_ts = payload.get('timestamp')
                if bms_ts:
                    from datetime import datetime
                    bms_dt = datetime.fromisoformat(bms_ts.replace('Z', '+00:00'))
                    now = datetime.now(bms_dt.tzinfo)
                    latency = (now - bms_dt).total_seconds()
                    DB_LATENCY_SECONDS.set(latency)
            except Exception:
                pass
    else:
        log.warning("store failed (connection state logged above)")
        if PROMETHEUS_AVAILABLE:
            DB_STORES_TOTAL.labels(result='failed').inc()
            DB_CONNECTION_STATUS.set(0)


def main():
    setup_logging()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(BROKER, PORT, 60)
    log.info(f"bms_db_logger: {BROKER}:{PORT}{TOPIC_STATUS} -> "
             f"{DB['database']}.bms_jk | log={LOG_FILE} "
             f"(max {LOG_MAX_BYTES}B x {LOG_BACKUPS + 1})")

    # Start Prometheus metrics HTTP server
    if PROMETHEUS_AVAILABLE:
        METRICS_PORT = int(os.environ.get("BMS_METRICS_PORT", "9101"))

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
                pass

        metrics_server = HTTPServer(("0.0.0.0", METRICS_PORT), MetricsHandler)
        metrics_thread = threading.Thread(target=metrics_server.serve_forever, daemon=True)
        metrics_thread.start()
        log.info(f"Prometheus metrics on :{METRICS_PORT}/metrics")

    client.loop_start()
    try:
        while not _shutdown:
            time.sleep(1)
    finally:
        log.info("Shutdown signal received, cleaning up...")
        client.loop_stop()
        client.disconnect()
        global storage
        if storage is not None:
            storage.close()


if __name__ == "__main__":
    main()
