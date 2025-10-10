# mqtt_server_waiting.py
import paho.mqtt.client as mqtt
import json
import threading

# ---- MQTT Settings ----
BROKER = "localhost"   # or IP of your Pi
PORT = 1883
TOPIC_CMD = "inverter/command"

# ---- MQTT Callbacks ----
def on_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker")
    client.subscribe(TOPIC_CMD)
    print(f"Subscribed to {TOPIC_CMD}")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload)
        device = payload.get("device")
        action = payload.get("action")
        value = payload.get("value", None)
        print(f"Received command -> Device: {device}, Action: {action}, Value: {value}")
        # Here you just receive the command, **no driver action is executed**
    except Exception as e:
        print("Error processing message:", e)

# ---- Setup MQTT Client ----
client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, PORT, 60)

# ---- Start MQTT loop in background ----
threading.Thread(target=client.loop_forever, daemon=True).start()

print("MQTT server running and waiting for commands... Press Ctrl+C to exit.")

# Keep main thread alive
try:
    while True:
        pass
except KeyboardInterrupt:
    print("Exiting MQTT server.")
