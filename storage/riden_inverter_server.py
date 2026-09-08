import json
import time
import threading
import paho.mqtt.client as mqtt
import os
import subprocess

from drivers.riden import Riden
from drivers.InverterController import InverterController
from drivers.PinDriver import PinDriver
from datetime import datetime

#BROKER = "192.168.2.42"
BROKER = "127.0.0.1"
PORT = 1883
TOPIC_CMD = "devices/command"
TOPIC_RESP = "devices/response"

WATCHDOG_TIMEOUT = 60.0          # silence before safety-off
WATCHDOG_REBOOT_TIMEOUT = 300.0  # continuous silence before reboot (5 min)
CHECK_INTERVAL = 0.5

# Persisted relay state survives server restarts (GPIO drops LOW when the
# process exits, which would otherwise unpower the charger on every restart)
PIN_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pin_state")


class DeviceServer:
    def __init__(self):
        # Per-device locks: command handlers, monitor and watchdog can work
        # on different devices concurrently without blocking each other.
        self._charger_lock = threading.Lock()
        self._inverter_lock = threading.Lock()
        self._pin_lock = threading.Lock()
        self.last_client_msg = time.time()

        self.charger = None
        self.inverter = None
        self.pindriver = None
        self.charger_required = False  # Track if charger was ever successfully connected
        self._charger_probe_fails = 0  # Consecutive unresponsive probes (relay-off detection)
        self._no_charger_warned = False  # Watchdog dedupe flag for inverter-only mode
        self._watchdog_silence_start = None  # When continuous silence began
        self._safety_off_done = False  # Safety shutdown already applied this silence period

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
                self._charger_probe_fails = 0
            except Exception as e:
                print(f"Charger connection test failed: {e}")
                # Close the serial port to free it for other devices
                if self.charger and self.charger.serial:
                    try:
                        self.charger.serial.close()
                    except:
                        pass
                self.charger = None

    def _init_inverter(self, port):
        """Create and start an InverterController on the given port. May raise."""
        inv = InverterController(port=port, baud=4800)
        inv.Connect()
        inv.ThreadLooping(start_power=0)
        print("Inverter OK")
        return inv

    def connect_inverter(self):
        # Try primary port first
        self.inverter = self._try_connect("inverter", lambda: self._init_inverter("/dev/ttyUSB1"))
        if self.inverter is None:
            # If primary fails, try alternative port (for when charger is not plugged)
            print("Inverter not found on /dev/ttyUSB1, trying /dev/ttyUSB0...")
            self.inverter = self._try_connect("inverter", lambda: self._init_inverter("/dev/ttyUSB0"))

    def connect_pindriver(self, pin=17):
        def init():
            pd = PinDriver(pin)
            print("PinDriver OK")
            return pd

        self.pindriver = self._try_connect("pindriver", init)
        self._restore_pin_state()

    # ------------------------------------------------------------
    # PIN STATE PERSISTENCE
    # ------------------------------------------------------------
    def _save_pin_state(self, connected: bool):
        try:
            with open(PIN_STATE_FILE, "w") as f:
                f.write("1" if connected else "0")
        except Exception as e:
            print(f"Could not persist pin state: {e}")

    def _load_pin_state(self):
        try:
            with open(PIN_STATE_FILE) as f:
                return f.read().strip() == "1"
        except Exception:
            return None  # no preference recorded

    def _restore_pin_state(self):
        """Re-apply the last requested relay state after a process restart.

        GPIO pins drop LOW when the process exits (gpiozero cleanup), which
        unpowers the charger. Without this, every server restart needs a
        fresh 'connect' command before the charger can come back.
        """
        if self.pindriver is None:
            return
        state = self._load_pin_state()
        if state is None:
            print("PinDriver: no saved state, leaving relay OFF")
            return
        try:
            if state:
                self.pindriver.connect()
                print("PinDriver: restored relay state -> CONNECTED (charger powered)")
            else:
                self.pindriver.disconnect()
                print("PinDriver: restored relay state -> DISCONNECTED")
        except Exception as e:
            print(f"PinDriver restore failed: {e}")

    def monitor_devices(self):
        """Proactively monitor and reconnect devices in the background.

        Charger handling goes beyond the serial port state: when the port is
        open but the device is unresponsive (e.g. relay cut its power), probe
        a cheap register; after repeated failures drop the connection object
        and clear charger_required so the watchdog doesn't stay armed for a
        deliberately powered-off charger.
        """
        print("Device monitor active...")
        while True:
            # --- Charger: reconnect if missing or unresponsive ---
            with self._charger_lock:
                charger_needs_reconnect = (
                    self.charger is None or not self.charger.is_connected()
                )
                # Port open but device silent (relay off): probe it
                if (not charger_needs_reconnect
                        and self._charger_probe_fails < 6):
                    try:
                        probe = self.charger.read(0, 1)
                    except Exception:
                        probe = None
                    if probe is None:
                        self._charger_probe_fails += 1
                        if self._charger_probe_fails >= 6:  # ~1 min of failures
                            print("Charger unresponsive ~60s -> dropping connection (relay off?)")
                            old = self.charger
                            self.charger = None
                            self.charger_required = False
                            try:
                                if old is not None and old.serial:
                                    old.serial.close()
                            except Exception:
                                pass
                    else:
                        if self._charger_probe_fails > 0:
                            print("Charger responsive again (probe OK)")
                        self._charger_probe_fails = 0

            if charger_needs_reconnect:
                print("Charger not connected, attempting reconnect...")
                temp_charger = None
                try:
                    # Try fresh connection (outside lock)
                    temp_charger = Riden(port="/dev/ttyUSB0", baudrate=115200, address=1)
                    # Test responsiveness
                    test = temp_charger.read(0, 1)
                    if test is None:
                        raise Exception("Reconnected device not responsive")

                    # Update state while holding lock; close old serial first
                    with self._charger_lock:
                        old = self.charger
                        self.charger = temp_charger
                        self.charger_required = True
                        self._charger_probe_fails = 0
                    temp_charger = None  # ownership transferred
                    if old is not None:
                        try:
                            if old.serial:
                                old.serial.close()
                        except Exception:
                            pass
                    print("Charger reconnected successfully.")
                except Exception as e:
                    print(f"Charger reconnect failed: {e}")
                    # Close the leaked serial handle from the failed attempt
                    if temp_charger is not None:
                        try:
                            if temp_charger.serial:
                                temp_charger.serial.close()
                        except Exception:
                            pass
                    with self._charger_lock:
                        self.charger = None

            # --- Inverter: retry connection while missing ---
            with self._inverter_lock:
                inverter_missing = self.inverter is None
            if inverter_missing:
                print("Inverter not connected, attempting reconnect...")
                # Try primary port, then fallback (same logic as connect_inverter)
                temp_inverter = self._try_connect(
                    "inverter", lambda: self._init_inverter("/dev/ttyUSB1"))
                if temp_inverter is None:
                    temp_inverter = self._try_connect(
                        "inverter", lambda: self._init_inverter("/dev/ttyUSB0"))
                if temp_inverter is not None:
                    with self._inverter_lock:
                        self.inverter = temp_inverter
                    print("Inverter reconnected successfully.")

            # --- PinDriver: retry connection while missing ---
            with self._pin_lock:
                pin_missing = self.pindriver is None
            if pin_missing:
                try:
                    temp_pin = self._try_connect("pindriver", lambda: PinDriver(17))
                    if temp_pin is not None:
                        with self._pin_lock:
                            self.pindriver = temp_pin
                        print("PinDriver reconnected successfully.")
                except Exception as e:
                    print(f"PinDriver reconnect failed: {e}")

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

        # Per-device lock so a slow charger command cannot block inverter/pin ops.
        device_lock = {
            "riden": self._charger_lock,
            "inverter": self._inverter_lock,
            "pindriver": self._pin_lock,
        }.get(device)

        if device_lock is None:
            return {"status": "error", "message": f"Unknown device {device}"}

        with device_lock:
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
            return {"status": "error", "message": "Riden not connected"}

        # BATCHED STATUS: one RPC instead of 12 sequential getter calls.
        # Normally a single fast block read (regs 4..20); every 6th call
        # also refreshes the battery block (32..41: ext temp, ah, wh).
        if action == "get_status":
            try:
                self._status_call_count = getattr(self, "_status_call_count", 0) + 1
                if self._status_call_count % 6 == 0:
                    self.charger.update()      # full refresh (2 block reads)
                else:
                    self.charger.update_fast()  # fast refresh (1 block read)
            except Exception as e:
                return {"status": "error", "message": str(e)}
            return {
                "status": "ok",
                "device": "riden",
                "result": {
                    "v_set": self.charger.v_set,
                    "v_out": self.charger.v_out,
                    "i_out": self.charger.i_out,
                    "p_out": self.charger.p_out,
                    "v_in": self.charger.v_in,
                    "temp_int": self.charger.int_c,
                    "temp_ext": self.charger.ext_c,
                    "mode": self.charger.cv_cc,
                    "fault": self.charger.ovp_ocp,
                    "output": self.charger.output,
                    "ah": getattr(self.charger, "ah", None),
                    "wh": getattr(self.charger, "wh", None),
                },
            }

        if not hasattr(self.charger, action):
            return {"status": "error", "message": f"No such riden method {action}"}

        fn = getattr(self.charger, action)

        # SPECIAL HANDLING FOR TIME
        if action == "set_date_time":
            try:
                if value:
                    # Accept ISO string from MQTT
                    dt = datetime.fromisoformat(value)
                else:
                    # If no value → use local time
                    dt = datetime.now()

                out = fn(dt)
                return {"status": "ok", "device": "riden", "result": "time_set"}

            except Exception as e:
                return {"status": "error", "message": f"Time parse failed: {e}"}

        # DEFAULT BEHAVIOR
        out = fn(value) if value is not None else fn()
        return {"status": "ok", "device": "riden", "result": out}

    def _cmd_inverter(self, action, value):
        print(f"Inverter command: {action} {value}")  # Debug: log inverter commands

        if action == "set_power":
            if self.inverter is not None:
                print(f"Setting inverter power to {value}")  # Debug
                self.inverter.ModifyPower(value)
                return {"status": "ok", "device": "inverter", "result": value}
            else:
                print("Inverter not connected")  # Debug
                return {"status": "error", "message": "Inverter not connected"}

        if action == "get_power":
            if self.inverter is not None:
                power = self.inverter.GetCurrentPower()
                print(f"Got last sent inverter power: {power}")  # Debug
                return {"status": "ok", "device": "inverter", "result": power}
            else:
                print("Inverter not connected")  # Debug
                return {"status": "error", "message": "Inverter not connected"}

        return {"status": "error", "message": f"Bad inverter action {action}"}

    def _cmd_pin(self, action, _):
        if self.pindriver is None:
            return {"status": "error", "message": "PinDriver not connected"}

        if action == "connect":
            self.pindriver.connect()
            self._save_pin_state(True)
        elif action == "disconnect":
            self.pindriver.disconnect()
            self._save_pin_state(False)
        else:
            return {"status": "error", "message": f"Bad pindriver action {action}"}

        return {"status": "ok", "device": "pindriver", "action": action}

    # ------------------------------------------------------------
    # WATCHDOG
    # ------------------------------------------------------------
    def watchdog(self):
        print("Watchdog active...")
        while True:
            silence = time.time() - self.last_client_msg

            if silence <= WATCHDOG_TIMEOUT:
                # Healthy: reset the escalation state
                self._no_charger_warned = False
                self._watchdog_silence_start = None
                self._safety_off_done = False
                time.sleep(CHECK_INTERVAL)
                continue

            # ---- Silence exceeds 60s: escalate ----
            if self._watchdog_silence_start is None:
                self._watchdog_silence_start = time.time()

            with self._charger_lock:
                charger_ok = self.charger is not None and self.charger.is_connected()

            if not self._safety_off_done:
                # Stage 1 (once): safety-off all outputs, but stay alive.
                # The measurement client may just be restarting; give it a
                # grace window before considering a reboot.
                if self.charger_required:
                    print(f"WATCHDOG: no client for {silence:.0f}s -> SAFETY OFF (reboot in {WATCHDOG_REBOOT_TIMEOUT - (time.time() - self._watchdog_silence_start):.0f}s if silence continues)")
                    try:
                        if self.inverter is not None:
                            self.inverter.ModifyPower(0)

                        if charger_ok:
                            self.charger.set_output(False)

                    except Exception as e:
                        print(f"WATCHDOG safety shutdown failed: {e}")
                else:
                    # Inverter-only mode is a legitimate steady state:
                    # warn once per silence period, no reboot.
                    if not self._no_charger_warned:
                        print("WATCHDOG: no charger required -> inverter safe mode only")
                        self._no_charger_warned = True
                self._safety_off_done = True

            # Stage 2 (after continuous silence): reboot only if the silence
            # persisted the full window AND a charger is part of the system.
            if (self.charger_required
                    and time.time() - self._watchdog_silence_start >= WATCHDOG_REBOOT_TIMEOUT):
                print("WATCHDOG: silence persisted 5 min -> REBOOTING SYSTEM NOW")
                #os.system("/sbin/reboot")
                subprocess.call(["sudo", "reboot"])

            time.sleep(CHECK_INTERVAL)

    # ------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------
    def on_connect(self, client, userdata, flags, rc):
        print("MQTT connected:", rc)
        client.subscribe(TOPIC_CMD)

    def on_message(self, client, userdata, msg):
        # Extract request_id defensively BEFORE dispatch so the error path
        # never has to re-parse a payload that may have failed to parse.
        request_id = None
        try:
            payload = json.loads(msg.payload.decode())
            if isinstance(payload, dict):
                request_id = payload.get("request_id")
            else:
                payload = None
        except Exception:
            payload = None

        if payload is None:
            # Unparseable/non-dict payload: reply with an error, never dispatch.
            error_out = {"status": "error", "message": "Invalid command payload"}
            if request_id is not None:
                error_out["request_id"] = request_id
            client.publish(TOPIC_RESP, json.dumps(error_out))
            return

        try:
            self.last_client_msg = time.time()  # Update watchdog timestamp
            print("CMD:", payload)
            out = self.handle_command(payload)
            if request_id is not None:
                out["request_id"] = request_id
            client.publish(TOPIC_RESP, json.dumps(out))
        except Exception as e:
            error_out = {"status": "error", "message": str(e)}
            if request_id is not None:
                error_out["request_id"] = request_id
            client.publish(TOPIC_RESP, json.dumps(error_out))

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
