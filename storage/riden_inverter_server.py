import json
import threading
import paho.mqtt.client as mqtt
from drivers.riden import Riden
from drivers.InverterController import InverterController
import time
from drivers.PinDriver import PinDriver

# -----------------------------
# CONFIG
# -----------------------------
BROKER = "localhost"
PORT = 1883
TOPIC_CMD = "devices/command"
TOPIC_RESP = "devices/response"

WATCHDOG_TIMEOUT = 5.0   # seconds → if no client msg → inverter to 0 W
CHECK_INTERVAL = 0.5     # watchdog loop sleep time

# -----------------------------
# GLOBALS
# -----------------------------
lock = threading.Lock()
charger = None
inverter = None
pindriver = None
last_client_msg = time.time()

# ============================================================
#  DEVICE CONNECTION FUNCTIONS
# ============================================================

def connect_charger():
    """Connect to Riden charger with retry loop."""
    global charger
    while True:
        try:
            print("Trying to connect to charger on /dev/ttyUSB0...")
            charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
            print(f"Connected to charger ID {charger.id}")
            return
        except Exception as e:
            print(" Charger connection failed, retrying in 5s:", e)
            time.sleep(5)


def connect_inverter():
    """Connect to InverterController on /dev/ttyUSB1 with retry loop."""
    global inverter
    while True:
        try:
            print("Trying to connect to inverter on /dev/ttyUSB1...")
            inverter = InverterController(port="/dev/ttyUSB1", baud=4800)
            inverter.Connect()
            inverter.ThreadLooping(start_power=0)
            print("Inverter connected and control loop started")
            return
        except Exception as e:
            print("Inverter connection failed, retrying in 5s:", e)
            time.sleep(5)


def connect_pindriver(pin=17):
    """Initialize the GPIO PinDriver."""
    global pindriver
    try:
        print(f"Initializing PinDriver on GPIO{pin}...")
        pindriver = PinDriver(pin)
    except Exception as e:
        print("PinDriver init failed:", e)

# ============================================================
#  HANDLING COMMANDS
# ============================================================

def handle_riden(action, value):
    global charger
    if charger is None:
        connect_charger()

    if hasattr(charger, action):
        method = getattr(charger, action)
        result = method(value) if value is not None else method()
        return {"status": "ok", "device": "riden", "action": action, "result": result}

    return {"status": "error", "device": "riden", "message": f"No such method: {action}"}


def handle_inverter(action, value):
    global inverter
    if inverter is None:
        connect_inverter()

    if action == "set_power" and value is not None:
        inverter.ModifyPower(value)
        return {"status": "ok", "device": "inverter", "result": value}

    if action == "get_power":
        return {"status": "ok", "device": "inverter", "result": inverter.GetCurrentPower()}

    return {
        "status": "error",
        "device": "inverter",
        "message": f"Invalid inverter command: {action}",
    }


def handle_pindriver(action):
    global pindriver
    if pindriver is None:
        connect_pindriver()

    if action == "connect":
        pindriver.connect()
        return {"status": "ok", "device": "pindriver", "action": "connect"}

    if action == "disconnect":
        pindriver.disconnect()
        return {"status": "ok", "device": "pindriver", "action": "disconnect"}

    return {"status": "error", "device": "pindriver", "message": f"Invalid pin driver command: {action}"}


def handle_command(payload: dict):
    """Main command handler."""
    global last_client_msg
    last_client_msg = time.time()  # update watchdog timestamp

    device = payload.get("device")
    action = payload.get("action")
    value = payload.get("value")

    try:
        with lock:
            if device == "riden":
                return handle_riden(action, value)

            elif device == "inverter":
                return handle_inverter(action, value)

            elif device == "pindriver":
                return handle_pindriver(action)

            else:
                return {"status": "error", "message": f"Unknown device: {device}"}

    except Exception as e:
        return {"status": "error", "message": f"Exception: {str(e)}"}


# ============================================================
# MQTT CALLBACKS
# ============================================================

def on_connect(client, userdata, flags, rc):
    print("Connected to broker, code:", rc)
    client.subscribe(TOPIC_CMD)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print("Received command:", payload)
        response = handle_command(payload)
        client.publish(TOPIC_RESP, json.dumps(response))
    except Exception as e:
        err = {"status": "error", "message": f"Exception: {str(e)}"}
        client.publish(TOPIC_RESP, json.dumps(err))
        print("Exception in on_message:", e)


# ============================================================
# WATCHDOG
# ============================================================

def watchdog_loop():
    """Runs forever, ensures inverter is set to 0 when client stops sending data."""
    global last_client_msg, inverter

    print("MQTT loop started, watchdog active...")

    while True:
        now = time.time()

        if now - last_client_msg > WATCHDOG_TIMEOUT:
            try:
                with lock:
                    print("WATCHDOG: No client messages → forcing inverter and riden to 0 W and out_off")
                    inverter.ModifyPower(0)
                    charger.set_output(False)
            except Exception as e:
                print("WATCHDOG ERROR:", e)

        time.sleep(CHECK_INTERVAL)


# ============================================================
# MAIN PROGRAM INITIALIZATION
# ============================================================

def main():

    # Connect hardware (blocking loops)
    connect_charger()
    connect_inverter()
    connect_pindriver()

    # Setup MQTT
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, 60)
    client.loop_start()

    # Start watchdog
    watchdog_loop()


if __name__ == "__main__":
    main()
