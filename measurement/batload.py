import time
from riden_remote import RidenRemote
from P1uitlezen import Meter
from datetime import datetime

class BatLoadLogger:
    LOG_FILE = "log.txt"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"

    @staticmethod
    def log_error(msg):
        with open(BatLoadLogger.LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")

    @staticmethod
    def print_magenta(msg):
        print(f"{BatLoadLogger.MAGENTA}{msg}{BatLoadLogger.RESET}")

class BatLoad:
    def __init__(self):
        self.meter = Meter()
        self.riden = RidenRemote()
        self.last_error_log = 0
        self.missing_count = 0

    def calculate_required_consumption(self, df):
        """
        Calculate the required instantaneous energy consumption (in kW) to keep export near zero.
        Returns a float (positive: increase load, negative: decrease load).
        """
        # Use exported power (to grid, -P)
        value_row = df[df['OBIS'] == '1-0:2:.7.0']
        if not value_row.empty:
            try:
                export_kw = float(value_row.iloc[0]['Value'])
                # To keep export near zero, consume this much more locally
                return export_kw
            except Exception:
                return 0.0
        return 0.0

    def run(self):
        self.meter.connect()
        try:
            while True:
                parsed_data = self.meter.read_lines(20)
                df = self.meter.to_dataframe(parsed_data)
                error_msg = None
                value_row = df[df['OBIS'] == '1-0:2:.7.0']
                if not value_row.empty:
                    self.missing_count = 0
                    value = value_row.iloc[0]['Value']
                    unit = value_row.iloc[0]['Unit']
                    print(f"Actual exported power (to grid, -P): {value} {unit}")
                    try:
                        required_kw = self.calculate_required_consumption(df)
                        set_result = self.riden.set_v_set(required_kw * 10)  # Example scaling
                        if isinstance(set_result, dict) and set_result.get("error"):
                            error_msg = f"Riden error: {set_result['error']}"
                            BatLoadLogger.print_magenta(f"Set Riden voltage to {required_kw}: {set_result}")
                        else:
                            print(f"Set Riden voltage to {required_kw}: {set_result}")
                    except Exception as e:
                        error_msg = f"Could not set Riden voltage: {e}"
                        BatLoadLogger.print_magenta(error_msg)
                else:
                    self.missing_count += 1
                    if self.missing_count >= 5:
                        error_msg = "No value for 1-0:2.7.0 found in this read for 5 consecutive times."
                        BatLoadLogger.print_magenta(error_msg)
                # Log error every 5 seconds
                if error_msg:
                    now = time.time()
                    if now - self.last_error_log > 5:
                        BatLoadLogger.log_error(error_msg)
                        self.last_error_log = now
                time.sleep(1)
        finally:
            self.meter.close()

if __name__ == "__main__":
    BatLoad().run()
