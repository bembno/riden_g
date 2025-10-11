import json
import time
import paho.mqtt.client as mqtt

class Batclant:
    def __init__(self, broker="192.168.2.38", port=1883,
                 topic_cmd="devices/command", topic_resp="devices/response"):
        self.broker = broker
        self.port = port
        self.topic_cmd = topic_cmd
        self.topic_resp = topic_resp
        self.client = mqtt.Client()
        self.last_response = None

        # MQTT callbacks
        self.client.on_message = self._on_message
        self.client.connect(self.broker, self.port, 60)
        self.client.subscribe(self.topic_resp)
        self.client.loop_start()
        time.sleep(0.5)  # wait for subscription

    # Internal callback
    def _on_message(self, client, userdata, msg):
        try:
            self.last_response = json.loads(msg.payload.decode())
        except Exception as e:
            self.last_response = {"status": "error", "message": f"Invalid JSON: {e}"}

    # Generic send command
    def send(self, device: str, function: str, value=None, timeout=2.0):

        self.last_response = None
        cmd = {"device": device, "action": function}
        if value is not None:
            cmd["value"] = value

        #print(f"➡️ Sending: {cmd}")
        self.client.publish(self.topic_cmd, json.dumps(cmd))

        # Wait for response
        start_time = time.time()
        while self.last_response is None:
            if time.time() - start_time > timeout:
                return {"status": "error", "message": "Timeout waiting for response"}
            time.sleep(0.05)
        return self.last_response

    # Optional convenience for get commands
    def get(self, device: str, function: str, timeout=2.0):
        return self.send(device, function, value=None, timeout=timeout)

    # Stop MQTT loop gracefully
    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


# ----------------------------
# Example usage
# ----------------------------
if __name__ == "__main__":
    bat = Batclant()

    # Set and get Riden values
    bat.send("riden", "set_v_set", 56.0)
    bat.send("riden", "set_i_set", 1.0)
    bat.send("riden", "set_output", True)
    print("V_SET:", bat.get("riden", "get_v_set")["result"])
    print("V_OUT:", bat.get("riden", "get_v_out")["result"])
    print("I_OUT:", bat.get("riden", "get_i_out")["result"])
    print("P_OUT:", bat.get("riden", "get_p_out")["result"])
    print("Output status:", bat.get("riden", "is_output")["result"])
    

    # Set and get inverter power
    bat.send("inverter", "set_power", 100)
    print("Inverter power:", bat.get("inverter", "get_power")["result"])

    # Close connection
    bat.close()
