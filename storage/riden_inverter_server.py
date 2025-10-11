import json
import threading
import paho.mqtt.client as mqtt
from drivers.riden import Riden
from drivers.InverterController import InverterController
import time

BROKER = "localhost"
PORT = 1883
TOPIC_CMD = "devices/command"
TOPIC_RESP = "devices/response"

# Thread lock for safety
lock = threading.Lock()

# Global device references
charger = None
inverter = None


def connect_charger():
    global charger
    while True:
        try:
            print("Trying to connect to charger on /dev/ttyUSB0...")
            charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
            print(f"Connected to charger ID {charger.id}")
            return
        except Exception as e:
            print("⚠️ Charger connection failed, retrying in 5s:", e)
            time.sleep(5)


def connect_inverter():
    """Connect to InverterController on /dev/ttyUSB1 with retries."""
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


# Initialize devices (blocking until successful)
connect_charger()
connect_inverter()


def handle_command(payload: dict):
    global charger, inverter
    device = payload.get("device")
    action = payload.get("action")
    value = payload.get("value", None)

    response = {}

    try:
        with lock:
            if device == "riden":
                if charger is None:
                    connect_charger()
                if hasattr(charger, action):
                    method = getattr(charger, action)
                    result = method(value) if value is not None else method()
                    response = {
                        "status": "ok",
                        "device": "riden",
                        "action": action,
                        "result": result,
                    }
                else:
                    response = {
                        "status": "error",
                        "device": "riden",
                        "message": f"No such method: {action}",
                    }

            elif device == "inverter":
                if inverter is None:
                    connect_inverter()
                if action == "set_power" and value is not None:
                    inverter.ModifyPower(value)
                    response = {
                        "status": "ok",
                        "device": "inverter",
                        "result": inverter.GetCurrentPower(),
                    }
                elif action == "get_power":
                    response = {
                        "status": "ok",
                        "device": "inverter",
                        "result": inverter.GetCurrentPower(),
                    }
                else:
                    response = {
                        "status": "error",
                        "device": "inverter",
                        "message": f"Invalid inverter command: {action}",
                    }

            else:
                response = {
                    "status": "error",
                    "message": f"Unknown device: {device}",
                }

    except Exception as e:
        response = {
            "status": "error",
            "message": f"Exception: {str(e)}",
        }

    print("Response:", response)
    return response


# MQTT Callbacks
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


# MQTT Setup
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_forever()
