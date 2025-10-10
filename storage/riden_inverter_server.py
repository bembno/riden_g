import json
import threading
import paho.mqtt.client as mqtt
from drivers.riden import Riden
from drivers.InverterController import InverterController
import time

BROKER = "localhost"  # MQTT broker on Pi
PORT = 1883
TOPIC_CMD = "devices/command"
TOPIC_RESP = "devices/response"

# Initialize devices
charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
time.sleep(0.5)  # Allow time for connection
charger.set_v_set(55.0)
charger.set_i_set(0.1)
time.sleep(1)
print("Riden charger initialized:", charger.get_v_out(), "A")
inverter = InverterController()
inverter.Connect()
inverter.ThreadLooping(start_power=0)

# Thread lock for safe device access
lock = threading.Lock()

def handle_command(payload: dict):
    device = payload.get("device")
    action = payload.get("action")
    value = payload.get("value", None)

    response = {"status": "error", "message": "Unknown error"}

    try:
        with lock:
            if device == "riden":
                if hasattr(charger, action):
                    method = getattr(charger, action)
                    response["result"] = method(value) if value is not None else method()
                    response["status"] = "ok"
                else:
                    response["message"] = f"No such method: {action}"

            elif device == "inverter":
                if action == "set_power" and value is not None:
                    inverter.ModifyPower(value)
                    response = {"status": "ok", "current_power": inverter.GetCurrentPower()}
                elif action == "get_power":
                    response = {"status": "ok", "current_power": inverter.GetCurrentPower()}
                else:
                    response["message"] = f"Invalid inverter command: {action}"
            else:
                response["message"] = f"Unknown device: {device}"
    except Exception as e:
        response = {"status": "error", "message": str(e)}

    return response

# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    print("Connected to broker, code:", rc)
    client.subscribe(TOPIC_CMD)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        response = handle_command(payload)
        client.publish(TOPIC_RESP, json.dumps(response))
    except Exception as e:
        client.publish(TOPIC_RESP, json.dumps({"status": "error", "message": str(e)}))

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, PORT, 60)
client.loop_forever()
