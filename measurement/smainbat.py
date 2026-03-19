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
        self.meter = Meter().start()  # Start the meter thread immediately
        self.batclant = Batclant()
        self.pid = PIDController(kp=0.5, ki=0.1, kd=0.05, setpoint=0.0, max_change_ratio=2.0)
        
        if not self.meter.wait_until_ready(timeout=5):
                    print("Warning: meter did not become ready within 5 seconds")
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
                # Wait until first telegram is received
                
                
                data = self.meter.get_power()  # Get latest data anytime (non-blocking)
                print(f" {data}")




                time.sleep(0.5)  # Main loop delay
                               


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
    # Initialize and run
    controller = SMainBat()

    try:
        controller.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        controller.cleanup()