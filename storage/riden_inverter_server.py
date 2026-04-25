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
        self.charger_required = False  # Track if charger was ever successfully connected

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
            try:
                # Test if device is actually responsive (not just serial connected)
                test = self.charger.read(0, 1)  # Try reading device ID
                if test is None:
                    raise Exception("Device read failed - not responsive")
                print("Charger OK")
                self.charger_required = True
            except Exception as e:
                print(f"Charger connection test failed: {e}")
                # Close the serial port to free it for other devices
                if self.charger and self.charger.serial:
                    try:
                        self.charger.serial.close()
                    except:
                        pass
                self.charger = None

    def connect_inverter(self):
        def init(port):
            inv = InverterController(port=port, baud=4800)
            inv.Connect()
            inv.ThreadLooping(start_power=0)
            print("Inverter OK")
            return inv

        # Try primary port first
        self.inverter = self._try_connect("inverter", lambda: init("/dev/ttyUSB1"))
        if self.inverter is None:
            # If primary fails, try alternative port (for when charger is not plugged)
            print("Inverter not found on /dev/ttyUSB1, trying /dev/ttyUSB0...")
            self.inverter = self._try_connect("inverter", lambda: init("/dev/ttyUSB0"))

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
                            self.charger.reconnect()
                            # Test responsiveness after reconnect
                            test = self.charger.read(0, 1)
                            if test is None:
                                raise Exception("Reconnected device not responsive")
                        else:
                            # Try fresh connection
                            temp_charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
                            # Test responsiveness
                            test = temp_charger.read(0, 1)
                            if test is None:
                                raise Exception("Reconnected device not responsive")
                            self.charger = temp_charger
                        if self.charger and self.charger.is_connected():
                            self.charger_required = True
                            print("Charger reconnected successfully.")
                    except Exception as e:
                        print(f"Charger reconnect failed: {e}")
                        self.charger = None  # Ensure it's None if test failed
                # Optionally add similar checks for inverter/pindriver if needed
            time.sleep(10)  # Check every 10 seconds (adjust as needed)

    # ------------------------------------------------------------
    # COMMAND HANDLING
    # ------------------------------------------------------------
    def handle_command(self, payload):
        print(f"Handling command: {payload}")  # Debug: log received commands
        self.last_client_msg = time.time()

        device = payload.get("device")
        action = payload.get("action")
        value = payload.get("value")

        with self.lock:
            try:
                return self._dispatch(device, action, value)
            except Exception as e:
                print(f"Command failed: {e}")  # Debug: log errors
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
        print(f"Inverter command: {action} {value}")  # Debug: log inverter commands
        if self.inverter is None:
            print("Inverter not connected, attempting to connect...")  # Debug
            self.connect_inverter()

        if action == "set_power":
            if self.inverter is not None:
                print(f"Setting inverter power to {value}")  # Debug
                self.inverter.ModifyPower(value)
                return {"status": "ok", "device": "inverter", "result": value}
            else:
                print("Inverter connection failed")  # Debug
                return {"status": "error", "message": "Inverter not connected"}

        if action == "get_power":
            if self.inverter is not None:
                power = self.inverter.GetLastSentPower()
                print(f"Got last sent inverter power: {power}")  # Debug
                return {"status": "ok", "device": "inverter", "result": power}
            else:
                print("Inverter connection failed")  # Debug
                return {"status": "error", "message": "Inverter not connected"}

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
                    charger_ok = self.charger is not None and self.charger.is_connected()
                    
                    if self.charger_required:
                        # Charger was connected before → Enforce safety
                        print("WATCHDOG: Charger required, forcing safety shutdown")
                        try:
                            if self.inverter is not None:
                                self.inverter.ModifyPower(0)
                            if charger_ok:
                                self.charger.set_output(False)
                        except Exception as e:
                            print(f"WATCHDOG safety shutdown failed: {e}")
                    else:
                        # Charger never connected → Allow independent operation
                        print("WATCHDOG: Charger not required, inverter operating independently (no shutdown)")
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
