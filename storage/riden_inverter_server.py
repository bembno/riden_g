import json
import time
import threading
import paho.mqtt.client as mqtt

from drivers.riden import Riden
from drivers.InverterController import InverterController
from drivers.PinDriver import PinDriver


BROKER = "localhost"
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
    def _connect_loop(self, name, fn):
        while True:
            try:
                print(f"Connecting to {name}...")
                return fn()
            except Exception as e:
                print(f"{name} connection failed: {e} → retry in 5s")
                time.sleep(5)

    def connect_charger(self):
        def init():
            c = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
            print(f"Charger OK")
            return c

        self.charger = self._connect_loop("charger", init)

    def connect_inverter(self):
        def init():
            inv = InverterController(port="/dev/ttyUSB1", baud=4800)
            inv.Connect()
            inv.ThreadLooping(start_power=0)
            print("Inverter OK")
            return inv

        self.inverter = self._connect_loop("inverter", init)

    def connect_pindriver(self, pin=17):
        def init():
            pd = PinDriver(pin)
            print("PinDriver OK")
            return pd

        self.pindriver = self._connect_loop("pindriver", init)

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
        # Connect devices
        self.connect_charger()
        self.connect_inverter()
        self.connect_pindriver()

        # Start watchdog
        threading.Thread(target=self.watchdog, daemon=True).start()

        # MQTT
        client = mqtt.Client()
        client.on_connect = self.on_connect
        client.on_message = self.on_message
        client.connect(BROKER, PORT, 60)
        client.loop_forever()


if __name__ == "__main__":
    DeviceServer().start()
