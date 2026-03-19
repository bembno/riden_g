from lib.P1uitlezen import Meter
from lib.batclant import Batclant
import time
from lib.PIDController import PIDController
from lib.P1Storage import P1Storage

BRIGHT_PINK = "\033[95m"
RESET = "\033[0m"
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

class SMainBat:
    def __init__(self):
        self.meter = Meter()
        self.batclant = Batclant()
        self.pid = PIDController(kp=0.5, ki=0.1, kd=0.05, setpoint=0.0, max_change_ratio=2.0)
        
        # Initialize database storage (optional)
        self.storage = None
        try:
            self.storage = P1Storage(
                host="192.168.2.33",
                user="admin", 
                password="aaa",
                database="energy"
            )
            if self.storage.connection is not None and self.storage.cursor is not None:
                print("Database connection established")
            else:
                print(f"{YELLOW}WARNING: Database not available{RESET}")
                self.storage = None
        except Exception as e:
            print(f"{YELLOW}WARNING: Failed to initialize database: {e}{RESET}")
            self.storage = None

    def run(self):
        while True:
            try:
                data = self.meter.read_telegram()
                print(f"Raw data: {data}")

                if not data:
                    print(f"{YELLOW}No data read from meter, using last good data.{RESET}")
                    continue

                # Extract instantaneous import/export power values
                values = self.meter.get_listed_obis_values(data, ['1-0:1:.7.0', '1-0:2:.7.0'])
                import_power, export_power = (values + [None, None])[:2]

                if import_power is None or export_power is None:
                    print(f"{YELLOW}Warning: Could not find required power values in data.{RESET}")
                    continue

                # --- Store raw data ---
                if self.storage is not None:
                    self.storage.store(data)

                # --- Calculate power difference ---
                power_diff = import_power - export_power

                # --- PID control ---
                power_adjustment = self.pid.adjustPower(measured_value=power_diff)

                # --- Send command to battery system ---
                # For charging/discharging, we use the inverter for discharge and riden for charge
                if power_adjustment >= 0:
                    # Discharge via inverter
                    self.batclant.safe_set_value("inverter", "set_power", int(power_adjustment * 1000))
                    self.batclant.safe_set_value("riden", "set_i_set", 0.0)
                else:
                    # Charge via Riden
                    self.batclant.safe_set_value("inverter", "set_power", 0)
                    self.batclant.safe_set_value("riden", "set_i_set", abs(power_adjustment))

                print(f"Import: {import_power:.3f} kW, Export: {export_power:.3f} kW | Diff: {power_diff:.3f} kW | Adjustment: {power_adjustment:.3f}")

                time.sleep(1.0)  # Read every second

            except KeyboardInterrupt:
                print("Interrupted by user")
                break
            except Exception as e:
                print(f"{RED}Error in main loop: {e}{RESET}")
                time.sleep(2.0)

    def cleanup(self):
        """Clean up resources"""
        try:
            self.batclant.close()
            if self.storage is not None:
                self.storage.close()
            print("Cleanup completed")
        except Exception as e:
            print(f"Error during cleanup: {e}")


if __name__ == "__main__":
    print("Starting Simple Main Battery Controller (SMainBat)")
    print("Press Ctrl+C to stop")

    # Initialize and run
    controller = SMainBat()

    try:
        controller.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.cleanup()