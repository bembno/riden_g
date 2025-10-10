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

# Initialize devices
charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
inverter = InverterController()
inverter.Connect()
inverter.ThreadLooping(start_power=0)

# Thread lock for safety
lock = threading.Lock()


def handle_command(payload: dict):
    device = payload.get("device")
    action = payload.get("action")
    value = payload.get("value", None)

    response = {}  # start clean each time

    try:
        with lock:
            if device == "riden":
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

    # Always log for debugging
    print("Response:", response)
    return response


# MQTT Callbacks
def on_connect(client, userdata, flags, rc):
    print("Connected to broker, code:", rc)
    client.subscribe(TOPIC_CMD)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        print("📨 Received command:", payload)
        response = handle_command(payload)
        client.publish(TOPIC_RESP, json.dumps(response))
    except Exception as e:
        err = {"status": "error", "message": f"Exception: {str(e)}"}
        client.publish(TOPIC_RESP, json.dumps(err))
        print("⚠️ Exception in on_message:", e)


# MQTT Setup
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_forever()
