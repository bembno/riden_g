import json
import time


class BmsStorage:
    """Stores JK BMS readings (bms_jk/status MQTT payload) into MariaDB.

    Table schema lives in sql/bms_jk.sql. Values are parameterized; the
    column set is a fixed map (same pattern as P1Storage).
    """

    # fixed payload-key -> DB column map
    FIELD_MAP = {
        "timestamp": "bms_timestamp",
        "battery_voltage_V": "battery_voltage_V",
        "current_A": "current_A",
        "power_W": "power_W",
        "soc": "soc",
        "capacity_remaining_Ah": "capacity_remaining_Ah",
        "nominal_capacity_Ah": "nominal_capacity_Ah",
        "soh": "soh",
        "cycles": "cycles",
        "cells_active": "cells_active",
        "cell_high_V": "cell_high_V",
        "cell_low_V": "cell_low_V",
        "cell_delta_mV": "cell_delta_mV",
        "cell_avg_mV": "cell_avg_mV",
        "mos_temp_C": "mos_temp_C",
        "t1_C": "t1_C",
        "t2_C": "t2_C",
        "balance_current_A": "balance_current_A",
        "balancing": "balancing",
        "charge_mosfet": "charge_mosfet",
        "discharge_mosfet": "discharge_mosfet",
    }

    MAX_CELLS = 16

    def __init__(self, host, user, password, database, table="bms_jk"):
        self.table = table
        self.host = host
        self.user = user
        self.password = password
        self.database = database
        self.connection = None
        self.cursor = None
        self.last_reconnect_attempt = 0
        self.reconnect_cooldown = 5  # seconds between reconnect attempts
        self.connection_failed_logged = False
        self._connect()

    def _connect(self):
        """Establish connection to MySQL server."""
        try:
            import mysql.connector
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                autocommit=True,
                connection_timeout=1,
                auth_plugin='mysql_native_password'
            )
            self.cursor = self.connection.cursor()
            return True
        except Exception as e:
            print(f"Failed to connect to MySQL: {e}")
            self.connection = None
            self.cursor = None
            return False

    def _ensure_connected(self):
        """Check if connection is alive, reconnect if needed (with cooldown)."""
        if self.connection is None or self.cursor is None:
            now = time.time()
            if now - self.last_reconnect_attempt > self.reconnect_cooldown:
                self.last_reconnect_attempt = now
                return self._connect()
            return False

        try:
            self.connection.ping(reconnect=False)
            self.connection_failed_logged = False
            return True
        except Exception as e:
            if not self.connection_failed_logged:
                print(f"Connection lost: {e}")
                self.connection_failed_logged = True

            try:
                if self.connection is not None:
                    self.connection.close()
            except Exception:
                pass
            self.connection = None
            self.cursor = None

            now = time.time()
            if now - self.last_reconnect_attempt > self.reconnect_cooldown:
                self.last_reconnect_attempt = now
                self._connect()

            return False

    def store(self, payload: dict):
        """Insert one BMS reading (the bms_jk/status MQTT payload dict)."""
        if not isinstance(payload, dict):
            return False

        # error payloads (e.g. BLE outage) carry no data -> nothing to store
        if "battery_voltage_V" not in payload:
            return False

        if not self._ensure_connected():
            return False

        row = {}
        for key, col in self.FIELD_MAP.items():
            v = payload.get(key)
            if v is not None:
                row[col] = v

        # errors list -> comma-joined string (empty list -> NULL keeps rows lean)
        errors = payload.get("errors")
        if errors:
            row["errors"] = ",".join(str(e) for e in errors)

        # per-cell voltages -> cellNN columns
        for i, v in enumerate((payload.get("cells") or [])[:self.MAX_CELLS], start=1):
            if v not in (None, 0):
                row[f"cell{i:02d}"] = v

        if not row:
            return True  # nothing to insert

        columns = ", ".join(row.keys())
        placeholders = ", ".join(["%s"] * len(row))
        sql = f"INSERT INTO {self.table} ({columns}) VALUES ({placeholders})"

        try:
            self.cursor.execute(sql, list(row.values()))
        except Exception as e:
            # connection errors are re-checked silently (errno 2013/2006)
            if not (hasattr(e, "errno") and e.errno in (2013, 2006)):
                print(f"DB Insert ERROR (bms_jk): {e}")
            self._ensure_connected()
            return False

        return True

    def close(self):
        """Close database connection gracefully."""
        try:
            if self.cursor is not None:
                self.cursor.close()
            if self.connection is not None:
                self.connection.close()
        except Exception as e:
            print(f"Error closing database connection: {e}")
