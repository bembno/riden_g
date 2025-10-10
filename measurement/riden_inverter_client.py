import json
import time
import paho.mqtt.client as mqtt

BROKER = "192.168.2.38"  # Pi IP
PORT = 1883
TOPIC_CMD = "devices/command"
TOPIC_RESP = "devices/response"

# Handle responses from server
def on_message(client, userdata, msg):
    print("Server response:", msg.payload.decode())

client = mqtt.Client()
client.on_message = on_message
client.connect(BROKER, PORT, 60)
client.loop_start()
client.subscribe(TOPIC_RESP)

time.sleep(1)

# ----------------------------
# Example commands
# ----------------------------

# Set Riden voltage
cmd = {"device": "riden", "action": "set_v_set", "value": 57.0}
client.publish(TOPIC_CMD, json.dumps(cmd))
cmd = {"device": "riden", "action": "set_i_set", "value": 1.1}
client.publish(TOPIC_CMD, json.dumps(cmd))
# Get Riden voltage
cmd = {"device": "riden", "action": "get_v_set"}
client.publish(TOPIC_CMD, json.dumps(cmd))

cmd = {"device": "riden", "action": "set_output", "value": True}
client.publish(TOPIC_CMD, json.dumps(cmd))


# Set inverter power
cmd = {"device": "inverter", "action": "set_power", "value": 110}
client.publish(TOPIC_CMD, json.dumps(cmd))

# Get inverter current power
cmd = {"device": "inverter", "action": "get_power"}
client.publish(TOPIC_CMD, json.dumps(cmd))

# Keep client running to receive responses
time.sleep(5)
client.loop_stop()
