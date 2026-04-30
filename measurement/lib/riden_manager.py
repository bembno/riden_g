import threading
import time


class RidenManager:
    def __init__(self, batclant, v_max_bat=57.5, check_interval=10.0):
        self.batclant = batclant
        self.Vmax_bat = v_max_bat
        self.check_interval = check_interval

        self.available = False
        self.last_error = None
        self.last_error_time = None
        self.error_count = 0
        self.status = {}

        self.monitor_alive = False
        self._monitor_thread = None

    def check_health(self):
        """Check whether Riden responds to a simple command."""
        try:
            result = self.batclant.get_value("riden", "is_output")
            if result is not None:
                self.available = True
                self.error_count = 0
                return True
            raise Exception("Riden returned None")
        except Exception as e:
            self.available = False
            self.error_count += 1
            self.last_error = str(e)
            self.last_error_time = time.time()
            return False

    def _monitor_health(self):
        print(f"[RidenHealthMonitor] Started - checking every {self.check_interval}s")
        while self.monitor_alive:
            try:
                self.check_health()
            except Exception as e:
                print(f"[RidenHealthMonitor] Unexpected error: {e}")

            for _ in range(int(self.check_interval * 10)):
                if not self.monitor_alive:
                    break
                time.sleep(0.1)

    def start_monitor(self):
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self.monitor_alive = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_health,
            daemon=True,
            name="RidenHealthMonitor",
        )
        self._monitor_thread.start()

    def stop_monitor(self):
        self.monitor_alive = False
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=0.5)

    def set_output(self, output_on=True):
        if not self.available:
            return None

        try:
            current_state = self.batclant.get_value("riden", "is_output")
            if current_state != output_on:
                self.batclant.set_value("riden", "set_output", output_on)
                time.sleep(0.01)
                new_state = self.batclant.get_value("riden", "is_output")
                print("Updated output status:", new_state)
                return new_state
            return current_state
        except Exception as e:
            self.available = False
            self.last_error = str(e)
            self.last_error_time = time.time()
            return None

    def get_full_status(self):
        if not self.available:
            return None

        try:
            return {
                "v_out": self.batclant.get_value("riden", "get_v_out"),
                "i_out": self.batclant.get_value("riden", "get_i_out"),
                "p_out": self.batclant.get_value("riden", "get_p_out"),
                "v_in": self.batclant.get_value("riden", "get_v_in"),
                "temp_int": self.batclant.get_value("riden", "get_int_c"),
                "temp_ext": self.batclant.get_value("riden", "get_ext_c"),
                "mode": self.batclant.get_value("riden", "get_cv_cc"),
                "fault": self.batclant.get_value("riden", "get_ovp_ocp"),
                "output": self.batclant.get_value("riden", "is_output"),
                "ah": self.batclant.get_value("riden", "get_ah"),
                "wh": self.batclant.get_value("riden", "get_wh"),
            }
        except Exception as e:
            self.available = False
            self.last_error = str(e)
            self.last_error_time = time.time()
            return None

    def update_status(self):
        status = self.get_full_status()
        if status is None:
            self.status = {}
            return False
        self.status = status
        return True

    def initialize(self):
        if not self.check_health():
            return False

        try:
            self.set_output(True)
            self.batclant.set_value("riden", "set_v_set", self.Vmax_bat)
            self.update_status()
            print("V_SET:", self.batclant.get_value("riden", "get_v_set"))
            print("V_OUT:", self.status.get("v_out"))
            print("I_OUT:", self.status.get("i_out"))
            print("P_OUT:", self.status.get("p_out"))
            return True
        except Exception as e:
            self.available = False
            self.last_error = str(e)
            self.last_error_time = time.time()
            return False
