import json
import time
import threading
import paho.mqtt.client as mqtt

from drivers.riden import Riden
from drivers.InverterController import InverterController
from drivers.PinDriver import PinDriver


BROKER = "192.168.2.38"
PORT = 1883
TOPIC_CMD = "devices/command"
TOPIC_RESP = "devices/response"

WATCHDOG_TIMEOUT = 5.0
CHECK_INTERVAL = 0.5


class DeviceServer:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_client_msg = time.time()

        self.charger = None
        self.inverter = None
        self.pindriver = None

    # ------------------------------------------------------------
    # CONNECTION HELPERS
    # ------------------------------------------------------------
    def _try_connect(self, name, fn):
        try:
            print(f"Connecting to {name}...")
            return fn()
        except Exception as e:
            print(f"{name} connection failed: {e}")
            return None

    def connect_charger(self):
        self.charger = self._try_connect("charger", lambda: Riden(port="/dev/ttyUSB0", baudrate=115200, address=1))
        if self.charger:
            print("Charger OK")

    def connect_inverter(self):
        def init():
            inv = InverterController(port="/dev/ttyUSB1", baud=4800)
            inv.Connect()
            inv.ThreadLooping(start_power=0)
            print("Inverter OK")
            return inv

        self.inverter = self._try_connect("inverter", init)

    def connect_pindriver(self, pin=17):
        def init():
            pd = PinDriver(pin)
            print("PinDriver OK")
            return pd

        self.pindriver = self._try_connect("pindriver", init)

    def monitor_devices(self):
        """Proactively monitor and reconnect devices in the background."""
        print("Device monitor active...")
        while True:
            with self.lock:
                # Monitor charger
                if self.charger is None or not self.charger.is_connected():
                    print("Charger not connected, attempting reconnect...")
                    try:
                        if self.charger:
                            self.charger.reconnect()  # Use Riden's built-in reconnect
                        else:
                            self.connect_charger()  # Try initial connection
                        if self.charger and self.charger.is_connected():
                            print("Charger reconnected successfully.")
                    except Exception as e:
                        print(f"Charger reconnect failed: {e}")
                # Optionally add similar checks for inverter/pindriver if needed
            time.sleep(10)  # Check every 10 seconds (adjust as needed)

    # ------------------------------------------------------------
    # COMMAND HANDLING
    # ------------------------------------------------------------
    def handle_command(self, payload):
        self.last_client_msg = time.time()

        device = payload.get("device")
        action = payload.get("action")
        value = payload.get("value")

        with self.lock:
            try:
                return self._dispatch(device, action, value)
            except Exception as e:
                return {"status": "error", "message": str(e)}

    def _dispatch(self, device, action, value):
        routes = {
            "riden": self._cmd_riden,
            "inverter": self._cmd_inverter,
            "pindriver": self._cmd_pin,
        }

        if device not in routes:
            return {"status": "error", "message": f"Unknown device {device}"}

        return routes[device](action, value)

    def _cmd_riden(self, action, value):
        if self.charger is None:
            self.connect_charger()

        if not hasattr(self.charger, action):
            return {"status": "error", "message": f"No such riden method {action}"}

        fn = getattr(self.charger, action)
        out = fn(value) if value is not None else fn()
        return {"status": "ok", "device": "riden", "result": out}

    def _cmd_inverter(self, action, value):
        if self.inverter is None:
            self.connect_inverter()

        if action == "set_power":
            self.inverter.ModifyPower(value)
            return {"status": "ok", "device": "inverter", "result": value}

        if action == "get_power":
            return {"status": "ok", "device": "inverter", "result": self.inverter.GetCurrentPower()}

        return {"status": "error", "message": f"Bad inverter action {action}"}

    def _cmd_pin(self, action, _):
        if self.pindriver is None:
            self.connect_pindriver()

        if action == "connect":
            self.pindriver.connect()
        elif action == "disconnect":
            self.pindriver.disconnect()
        else:
            return {"status": "error", "message": f"Bad pindriver action {action}"}

        return {"status": "ok", "device": "pindriver", "action": action}

    # ------------------------------------------------------------
    # WATCHDOG
    # ------------------------------------------------------------
    def watchdog(self):
        print("Watchdog active...")
        while True:
            if time.time() - self.last_client_msg > WATCHDOG_TIMEOUT:
                with self.lock:
                    print("WATCHDOG: forcing inverter=0W, charger OFF")
                    try:
                        self.inverter.ModifyPower(0)
                        self.charger.set_output(False)
                    except:
                        pass
            time.sleep(CHECK_INTERVAL)

    # ------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------
    def on_connect(self, client, userdata, flags, rc):
        print("MQTT connected:", rc)
        client.subscribe(TOPIC_CMD)

    def on_message(self, client, userdata, msg):
        try:
            self.last_client_msg = time.time()  # Update watchdog timestamp
            payload = json.loads(msg.payload.decode())
            print("CMD:", payload)
            out = self.handle_command(payload)
            client.publish(TOPIC_RESP, json.dumps(out))
        except Exception as e:
            client.publish(TOPIC_RESP, json.dumps({"status": "error", "message": str(e)}))

    # ------------------------------------------------------------
    # MAIN START
    # ------------------------------------------------------------
    def start(self):
        # Connect devices (non-blocking now)
        self.connect_charger()
        self.connect_inverter()
        self.connect_pindriver()

        # Start device monitor
        threading.Thread(target=self.monitor_devices, daemon=True).start()

        # Start watchdog
        threading.Thread(target=self.watchdog, daemon=True).start()

        # MQTT
        print(f"Connecting to MQTT broker at {BROKER}:{PORT}...")
        try:
            client = mqtt.Client()
            client.on_connect = self.on_connect
            client.on_message = self.on_message
            client.connect(BROKER, PORT, 60)
            print("MQTT connect() called, starting loop...")
            client.loop_forever()
        except Exception as e:
            print(f"MQTT connection failed: {e}")
            return


if __name__ == "__main__":
    DeviceServer().start()
