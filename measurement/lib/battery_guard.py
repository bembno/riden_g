"""Battery guard: control-loop override layer based on live BMS data.

Solar-only charging policy: the battery is NEVER charged from the grid.
Charging only happens from house export (solar surplus) via the normal
PID charge path.

Subscribes to bms_jk/status on the broker (published by the storage Pi's
bms_mqtt.py bridge every ~30 s). When the battery approaches empty or
full, the guard overrides the grid-neutral PID decision:

  - empty (pack <= 45 V policy: SOC <= 1%, cell <= 2.81 V, or fallback
    v_bat <= 45 V) -> block discharge (inverter stays at 0 W; charging
    from solar surplus remains allowed and is the only recovery path).
    Released at SOC >= 12% AND cells >= 3.00 V (fallback v_bat >= 47 V)
    - latched hysteresis, so it never chatters at the boundary.
  - full (SOC >= 95% or cell >= 3.50 V; fallback v_bat >= 57 V) ->
    block charge. Released at SOC <= 90% / cells <= 3.45 V
    (fallback: v_bat <= 56.5 V).
  - data stale (> BMS_STALE_AFTER) -> fall back to Riden v_bat if
    fresh; if neither is fresh the last latched mode persists.
  - everything normal -> no override

Thread-safe: values arrive on the MQTT client thread, are read by the
control loop thread. All access guarded by a lock.
"""
import json
import threading
import time

import paho.mqtt.client as mqtt

# ---------------- tunables ----------------
# LiFePO4 16S (48V) voltage-based guard policy
# Based on LiFePO4 SoC voltage chart (resting voltages):
# 100% = 58.40V, 90% = 54.40V, 80% = 53.60V, 50% = 52.32V
# 20% = 51.20V, 10% = 48.00V, 0% = 40.00V

# Discharge protection (empty)
VBAT_FLOOR = 46.00      # V - block discharge at/ below 48V (10% - Recharge Now)
VBAT_FLOOR_RECOVER = 51.20  # V - release block-discharge at/above 51.2V (20% - Low Battery)

# Charge protection (full)
VBAT_CEIL = 58.40       # V - block charge at/above 58.4V (100% - Full)
VBAT_CEIL_RECOVER = 54.40   # V - release block-charge at/below 54.4V (90% - Resting Full)

# Legacy SOC/Cell thresholds (deprecated, kept for backward compat but unused)
SOC_FLOOR = 0
SOC_FLOOR_RECOVER = 0
SOC_CEIL = 100
SOC_CEIL_RECOVER = 0
CELL_V_FLOOR = 0
CELL_V_FLOOR_RECOVER = 0
CELL_V_CEIL = 0
CELL_V_CEIL_RECOVER = 0

BMS_STALE_AFTER = 300.0   # s - BMS data older than this = stale
RIDEN_STALE_AFTER = 60.0  # s - Riden v_bat older than this = stale

BROKER = "192.168.2.42"
PORT = 1883
TOPIC_STATUS = "bms_jk/status"

# override modes returned by mode()
MODE_NORMAL = "normal"
MODE_BLOCK_DISCHARGE = "block_discharge"  # battery empty: solar-only policy
MODE_BLOCK_CHARGE = "block_charge"        # battery full: no charging


class BatteryGuard:
    def __init__(self, broker=BROKER, port=PORT):
        self._lock = threading.Lock()
        self._bms = {}          # last payload from bms_jk/status
        self._bms_time = 0.0    # monotonic time of arrival
        self._riden_vbat = None # fallback: Riden v_bat (set by main loop)
        self._riden_vbat_time = 0.0
        self._connected = False
        # Latched guard state: makes engage/release thresholds a true
        # hysteresis band instead of a single chattering boundary.
        self._latched_mode = MODE_NORMAL

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        try:
            self.client.connect(broker, port, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"BatteryGuard: MQTT connect failed ({e}); "
                  f"will rely on Riden fallback only")

    # ---------------- MQTT plumbing ----------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(TOPIC_STATUS)
            with self._lock:
                self._connected = True
        else:
            print(f"BatteryGuard: MQTT connect failed code {reason_code}")

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        with self._lock:
            self._connected = False

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return
        if not isinstance(payload, dict) or "battery_voltage_V" not in payload:
            # outage reports carry no battery data -> nothing to extract
            return
        with self._lock:
            self._bms = payload
            self._bms_time = time.monotonic()

    # ---------------- main-loop API ----------------
    def set_riden_vbat(self, v):
        """Feed the Riden pack-voltage fallback (call every control cycle)."""
        with self._lock:
            if v is not None and v > 0:
                self._riden_vbat = v
                self._riden_vbat_time = time.monotonic()

    def status(self):
        """Latest BMS snapshot dict (may be empty)."""
        with self._lock:
            return dict(self._bms) if self._bms else {}

    def _bms_fresh(self):
        with self._lock:
            return (self._bms_time > 0
                    and time.monotonic() - self._bms_time <= BMS_STALE_AFTER)

    def _riden_fresh(self):
        with self._lock:
            return (self._riden_vbat is not None
                    and time.monotonic() - self._riden_vbat_time
                    <= RIDEN_STALE_AFTER)

    def mode(self):
        """Current override mode with latched hysteresis - VOLTAGE ONLY.

        Engage (from normal):   empty -> BLOCK_DISCHARGE, full -> BLOCK_CHARGE
        Release (from latched): BLOCK_DISCHARGE at VBAT_FLOOR_RECOVER,
                                BLOCK_CHARGE at VBAT_CEIL_RECOVER.
        With no fresh signal at all, the latched mode persists (an empty
        battery stays discharge-blocked even if telemetry drops out).
        """
        # --- 1. BMS data path (preferred) - voltage only ---
        if self._bms_fresh():
            with self._lock:
                vbat = self._bms.get("battery_voltage_V")
            empty = vbat is not None and vbat <= VBAT_FLOOR
            recover_empty = vbat is not None and vbat >= VBAT_FLOOR_RECOVER
            full = vbat is not None and vbat >= VBAT_CEIL
            recover_full = vbat is not None and vbat <= VBAT_CEIL_RECOVER

        # --- 2. Riden v_bat fallback ---
        elif self._riden_fresh():
            with self._lock:
                v = self._riden_vbat
            empty = v <= VBAT_FLOOR
            recover_empty = v >= VBAT_FLOOR_RECOVER
            full = v >= VBAT_CEIL
            recover_full = v <= VBAT_CEIL_RECOVER

        # --- 3. no visibility: keep the latched state ---
        else:
            with self._lock:
                return self._latched_mode

        # --- latched state machine (true hysteresis, single-pass) ---
        with self._lock:
            new_mode = self._latched_mode
            if new_mode == MODE_BLOCK_DISCHARGE:
                if recover_empty:
                    new_mode = MODE_NORMAL
            elif new_mode == MODE_BLOCK_CHARGE:
                if recover_full:
                    new_mode = MODE_NORMAL
            else:  # MODE_NORMAL
                new_mode = MODE_NORMAL

            # After a release, evaluate engagement within the SAME pass so
            # the mode is settled deterministically (no one-cycle flap).
            if new_mode == MODE_NORMAL:
                if empty:
                    new_mode = MODE_BLOCK_DISCHARGE
                elif full:
                    new_mode = MODE_BLOCK_CHARGE

            self._latched_mode = new_mode
            return new_mode

    def confidence(self):
        """'bms' | 'riden' | 'none' - which signal the mode() used."""
        if self._bms_fresh():
            return "bms"
        if self._riden_fresh():
            return "riden"
        return "none"

    def soc(self):
        """Latest SOC % (None if unknown)."""
        with self._lock:
            return self._bms.get("soc") if self._bms else None

    def battery_voltage(self):
        """Latest BMS pack voltage in V (None if unknown)."""
        with self._lock:
            return self._bms.get("battery_voltage_V") if self._bms else None

    def cell_low(self):
        """Latest lowest cell voltage in V (None if unknown).

        Prefers the minimum of the active per-cell voltages; falls back
        to the reported cell_low_V field.
        """
        with self._lock:
            if not self._bms:
                return None
            cells = self._bms.get("cells") or []
            if cells:
                active = [c for c in cells if c]
                if active:
                    return min(active)
            return self._bms.get("cell_low_V")

    def close(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass
