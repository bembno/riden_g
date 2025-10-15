from mqqt.mqqt_server import MQTTServer, start_server
import socket
import threading
import json
import traceback
import os
import signal
import subprocess
import sys
import time
from riden.riden import Riden
from concurrent.futures import ThreadPoolExecutor
from mqqt.mqqt_server import MQTTServer

# Globals
riden = None
server_socket = None
shutdown_flag = False
riden_status = {"ok": False, "last_error": None, "ttl": 0}


# ---------------- Riden Handling ----------------
def init_riden():
    global riden, riden_status
    try:
        riden = Riden()
        riden_status["ok"] = True
        riden_status["last_error"] = None
        riden_status["ttl"] = 0
        print("[INFO] Riden initialized")
    except Exception as e:
        riden = None
        riden_status["ok"] = False
        riden_status["last_error"] = f"Init error: {e}"
        print(f"[ERROR] Could not initialize Riden: {e}")


def error_service():
    global riden, shutdown_flag
    while not shutdown_flag:
        if riden is None:
            init_riden()
        else:
            try:
                _ = riden.get_id()
                riden_status["ok"] = True
                riden_status["last_error"] = None
                riden_status["ttl"] = 0
            except Exception as e:
                print(f"[ERROR] Lost connection to Riden: {e}")
                riden_status["ok"] = False
                riden_status["last_error"] = str(e)
                riden_status["ttl"] += 1
                riden = None
        time.sleep(2)


def handle_riden_command(command: dict) -> dict:
    """Dispatch command to Riden class methods."""
    if command.get("cmd") == "get_status":
        return {"status": riden_status}
    if riden is None:
        return {"error": "Riden device not connected", "status": riden_status}
    try:
        method = command.get("cmd")
        args = command.get("args", [])
        kwargs = command.get("kwargs", {})
        if not hasattr(riden, method):
            return {"error": f"Unknown command: {method}"}
        func = getattr(riden, method)
        result = func(*args, **kwargs)
        return {"result": result}
    except Exception as e:
        return {"error": str(e), "trace": traceback.format_exc()}



# ---------------- Signal Handling ----------------
def handle_sigint(sig, frame):
    global shutdown_flag
    print("\n[INFO] Caught Ctrl+C, shutting down...")
    shutdown_flag = True
    if riden:
        try:
            riden.close()
            print("[INFO] Riden closed.")
        except Exception as e:
            print(f"[WARN] Error closing Riden: {e}")
    sys.exit(0)


signal.signal(signal.SIGINT, handle_sigint)


# ---------------- Main ----------------
if __name__ == "__main__":
    # Import InverterController and set up MQTT-driven power control
    from Soyosource.InverterController import InverterController
    inverter = InverterController()
    inverter.start(initial_power_kw=0.0)

    # Set up MQTT server to receive set_power commands
    def set_power_callback(power_kw):
        inverter.set_power(power_kw)

    mqtt_server = MQTTServer(
        broker='localhost',
        port=1883,
        status_topic='riden/status',
        set_power_topic='riden/set_power',
        set_power_callback=set_power_callback
    )
    mqtt_server.start()

    # Start the TCP server first so it is immediately responsive
    threading.Thread(target=lambda: start_server(handle_riden_command, lambda: shutdown_flag), daemon=True).start()
    # Then initialize Riden and start error_service
    init_riden()
    threading.Thread(target=error_service, daemon=True).start()
    # Keep main thread alive
    while not shutdown_flag:
        time.sleep(1)
