import threading
import time


class RidenManager:
    def __init__(self, batclant, v_max_bat=57.5, check_interval=10.0):
        self.batclant = batclant
        self.Vmax_bat = v_max_bat
        self.check_interval = check_interval

        # Health / state
        self.available = False
        self.last_error = None
        self.last_error_time = None
        self.error_count = 0

        # Runtime values (FULL STATUS as class variables)
        self.v_out = None
        self.i_out = None
        self.p_out = None
        self.v_in = None
        self.temp_int = None
        self.temp_ext = None
        self.mode = None
        self.fault = None
        self.output = None
        self.ah = None
        self.wh = None
        self.v_set = None

        # Optional dict snapshot (for compatibility/logging)
        self.status = {}

        # Threading
        self.monitor_alive = False
        self._monitor_thread = None

    # ---------------------------
    # HEALTH
    # ---------------------------
    def check_health(self):
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
        if self._monitor_thread:
            self._monitor_thread.join(timeout=0.5)

    # ---------------------------
    # CONTROL
    # ---------------------------
    def set_output(self, output_on=True):
        if not self.available:
            return None

        try:
            current_state = self.batclant.get_value("riden", "is_output")

            if current_state != output_on:
                self.batclant.set_value("riden", "set_output", output_on)
                time.sleep(0.01)

                self.output = self.batclant.get_value("riden", "is_output")
                print("Updated output status:", self.output)
                return self.output

            self.output = current_state
            return current_state

        except Exception as e:
            self.available = False
            self.last_error = str(e)
            self.last_error_time = time.time()
            return None

    # ---------------------------
    # STATUS
    # ---------------------------


    def get_full_status(self):
        """Update all internal state variables."""
        if not self.available:
            return False

        try:
            self.v_set = self.batclant.get_value("riden", "get_v_set")
            self.v_out = self.batclant.get_value("riden", "get_v_out")
            self.i_out = self.batclant.get_value("riden", "get_i_out")
            self.p_out = self.batclant.get_value("riden", "get_p_out")
            self.v_in = self.batclant.get_value("riden", "get_v_in")
            self.temp_int = self.batclant.get_value("riden", "get_int_c")
            self.temp_ext = self.batclant.get_value("riden", "get_ext_c")
            self.mode = self.batclant.get_value("riden", "get_cv_cc")
            self.fault = self.batclant.get_value("riden", "get_ovp_ocp")
            self.output = self.batclant.get_value("riden", "is_output")
            self.ah = self.batclant.get_value("riden", "get_ah")
            self.wh = self.batclant.get_value("riden", "get_wh")

            # Optional snapshot
            self.status = {
                "v_set": self.v_set,
                "v_out": self.v_out,
                "i_out": self.i_out,
                "p_out": self.p_out,
                "v_in": self.v_in,
                "temp_int": self.temp_int,
                "temp_ext": self.temp_ext,
                "mode": self.mode,
                "fault": self.fault,
                "output": self.output,
                "ah": self.ah,
                "wh": self.wh,
            }
            

            return True

        except Exception as e:
            self.available = False
            self.last_error = str(e)
            self.last_error_time = time.time()
            return False


    # ---------------------------
    # INIT
    # ---------------------------
    def initialize(self):
        if not self.check_health():
            return False

        try:
            if not self.output:
                self.set_output(True)
           
            self.batclant.set_value("riden", "set_v_set", self.Vmax_bat)
            #cv -0 cc -1
            self.batclant.set_value("riden", "set_cv_cc", 0)

            self.get_full_status()
            print("Updated Riden status:", self.status)

            return True

        except Exception as e:
            self.available = False
            self.last_error = str(e)
            self.last_error_time = time.time()
            return False