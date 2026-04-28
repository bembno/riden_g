import json
import time
import threading
import uuid
import paho.mqtt.client as mqtt


class Batclant:
    def __init__(self, broker="192.168.2.38", port=1883,
                 topic_cmd="devices/command", topic_resp="devices/response"):
        self.broker = broker
        self.port = port
        self.topic_cmd = topic_cmd
        self.topic_resp = topic_resp
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2 )  
        self.last_response = None
        self.connected = False 
        self._response_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending_request_id = None
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        
        self._connect()
        self.client.loop_start()
        

    def _connect(self):
        while True:
            try:
                self.client.connect(self.broker, self.port, 60)
                break
            except Exception:
                print("MQTT connect failed, retrying in 2s...")
                time.sleep(1)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected = True
            print("MQTT connected, subscribing to response topic...")
            self.client.subscribe(self.topic_resp)
        else:
            print(f"MQTT connection failed with code {reason_code}")
            self.connected = False 
    
    def _on_message(self, client, userdata, msg):
        try:
            response = json.loads(msg.payload.decode())
        except Exception as e:
            response = {"status": "error", "message": f"Invalid JSON: {e}"}

        request_id = response.get("request_id")
        with self._response_lock:
            if request_id is None or request_id == self._pending_request_id:
                self.last_response = response
    
    def _restart_mqtt(self):
        try:
            print("Restarting MQTT client loop...")
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
        time.sleep(1)
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        with self._response_lock:
            self.last_response = None
        self.connected = False
        self.client.loop_start()
        self._connect()

    # ----------------------------
    # Generic send
    # ----------------------------
    def _send_command(self, device, function, value=None, timeout=1.0):
        request_id = uuid.uuid4().hex
        cmd = {"device": device, "action": function, "request_id": request_id}
        if value is not None:
            cmd["value"] = value

        with self._send_lock:
            with self._response_lock:
                self.last_response = None
                self._pending_request_id = request_id

            self.client.publish(self.topic_cmd, json.dumps(cmd))

            deadline = time.time() + timeout
            while time.time() < deadline:
                with self._response_lock:
                    response = self.last_response
                if response is not None:
                    return response
                time.sleep(0.05)

            with self._response_lock:
                self._pending_request_id = None

            return {
                "status": "error",
                "message": f"Timeout waiting for response to {device}.{function}",
                "request_id": request_id,
            }
    
    
    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        self.connected = False
        print(f"MQTT disconnected (code {reason_code}), reconnecting...")

        def try_reconnect():
            while not self.connected:
                try:
                    self.client.reconnect()
                except Exception as e:
                    print(f"Reconnect failed: {e}, retrying in 1s")
                    time.sleep(1)
                time.sleep(1)

        threading.Thread(target=try_reconnect, daemon=True).start()


    def set_value(self, device: str, function: str, value, timeout=2):
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
    bat.set_value("inverter", "set_power", 0)
    bat.set_value("riden", "set_v_set", 56.0)
    # Close connection
    bat.close()
