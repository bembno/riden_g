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

    # ----------------------------
    # Internal callback
    # ----------------------------
    def _on_message(self, client, userdata, msg):
        try:
            self.last_response = json.loads(msg.payload.decode())
        except Exception as e:
            self.last_response = {"status": "error", "message": f"Invalid JSON: {e}"}

    # ----------------------------
    # Generic send
    # ----------------------------
    def _send_command(self, device: str, function: str, value=None, timeout=2.0, retries=3):
        """Internal method to send command and wait for response with retry."""
        for attempt in range(retries):
            self.last_response = None
            cmd = {"device": device, "action": function}
            if value is not None:
                cmd["value"] = value

            self.client.publish(self.topic_cmd, json.dumps(cmd))

            start_time = time.time()
            while self.last_response is None:
                if time.time() - start_time > timeout:
                    break
                time.sleep(0.05)

            if self.last_response is not None:
                return self.last_response

            print(f"Timeout waiting for response from {device}.{function}, attempt {attempt+1}/{retries}")
            time.sleep(2)
            # Try reconnecting to MQTT broker before next retry
            try:
                self.client.reconnect()
            except Exception:
                print("Reconnecting MQTT client failed, will retry...")

        return {"status": "error", "message": "Timeout waiting for response after retries"}



    def set_value(self, device: str, function: str, value, timeout=2.0):
        """Set a value on a device (Riden or Inverter)."""
        resp = self._send_command(device, function, value=value, timeout=timeout)
        if resp.get("status") != "ok":
            raise RuntimeError(f"Failed to set {device}.{function}: {resp.get('message')}")
        return resp.get("result")

    def get_value(self, device: str, function: str, timeout=2.0):
        """Get a value from a device. Returns the 'result' directly."""
        resp = self._send_command(device, function, value=None, timeout=timeout)
        if resp.get("status") != "ok":
            raise RuntimeError(f"Failed to get {device}.{function}: {resp.get('message')}")
        return resp.get("result")

    # ----------------------------
    # Stop MQTT loop gracefully
    # ----------------------------
    def close(self):
        self.client.loop_stop()
        self.client.disconnect()


# ----------------------------
# Example usage
# ----------------------------
if __name__ == "__main__":
    bat = Batclant()

    # Set Riden values
    bat.set_value("riden", "set_v_set", 56.0)
    bat.set_value("riden", "set_i_set", 1.0)
    bat.set_value("riden", "set_output", True)

    # Get Riden values
    print("V_SET:", bat.get_value("riden", "get_v_set"))
    print("V_OUT:", bat.get_value("riden", "get_v_out"))
    print("I_OUT:", bat.get_value("riden", "get_i_out"))
    print("P_OUT:", bat.get_value("riden", "get_p_out"))
    print("Output status:", bat.get_value("riden", "is_output"))

    # Set and get inverter power
    bat.set_value("inverter", "set_power", 100)
    print("Inverter power:", bat.get_value("inverter", "get_power"))

    # Close connection
    bat.close()
