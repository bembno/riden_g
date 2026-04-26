from lib.P1uitlezen import Meter
from lib.batclant import Batclant
import time
from lib.PIDController import PIDController
from lib.P1Storage import P1Storage
import threading
import os, sys
import subprocess

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

P_adding=0.0
# Allow override from command line
if len(sys.argv) > 1:
    try:
        P_adding = float(sys.argv[1])
        print(f"Using P_adding from CLI: {P_adding}")
    except ValueError:
        print(f"Invalid P_adding value '{sys.argv[1]}', using default {P_adding}")

class SoftwareWatchdog:
    def __init__(self, timeout=60):
        self.timeout = timeout
        self.counter = 0
        self.lock = threading.Lock()
        self.alive = True

    def reset(self):
        with self.lock:
            self.counter = 0

    def run(self):
        while self.alive:
            time.sleep(1)

            with self.lock:
                self.counter += 1
                if self.counter >= self.timeout:
                    print("WATCHDOG → REBOOTING SYSTEM")
                    self.alive = False  # stop loop
                    subprocess.run(["sudo", "reboot"])
class SMainBat:

    def __init__(self):
        self.meter = Meter().start()  # Start the meter thread immediately
        self.batclant = Batclant()
        self.set_v_set_initial=58.0
        self.pid = PIDController(kp=2.5, ki=0.05, kd=0.05, setpoint=0.0, max_change_ratio=1.0)
        
        if not self.meter.wait_until_ready(timeout=1):
                    print("Warning: meter did not become ready within 5 seconds")
        # Initialize database storage (optional)
        self.storage = None
        
        self.rid_P_out=0.0
        self.current=0.0
        self.v_out=0.0
        self.temp_int_c = 0.0
        self.temp_ext_c = 0.0
        self.max_current=30.0
        self.min_output=-1.8
        self.max_output=1.8
        self.temp_max_allowed=35.0
        
        # Riden health tracking
        self.riden_available = False
        self.riden_last_error = None
        self.riden_last_error_time = None
        self.riden_error_count = 0
        self.riden_check_interval = 10.0  # Background thread checks every 2 seconds

        #sw watchdog to ensure script restarts if it hangs for some reason (e.g. meter thread issues)
        self.sw_watchdog = SoftwareWatchdog(timeout=60)
        threading.Thread(target=self.sw_watchdog.run, daemon=True,name="SoftwareWatchdog").start()

        # Riden health monitoring (non-blocking background thread)
        self.riden_monitor_alive = True
        threading.Thread(target=self._monitor_riden_health, daemon=True, name="RidenHealthMonitor").start()


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
            
    def check_riden_health(self):
        """Check if Riden is responding. Returns True if healthy, False otherwise."""
        try:
            # Try a simple read to test connectivity
            result = self.batclant.get_value("riden", "get_v_out")
            if result is not None:
                self.riden_available = True
                self.riden_error_count = 0
                return True
            else:
                raise Exception("Riden returned None")
        except Exception as e:
            self.riden_available = False
            self.riden_error_count += 1
            self.riden_last_error = str(e)
            self.riden_last_error_time = time.time()
            return False

    def _monitor_riden_health(self):
        """Background thread: Continuously monitor Riden health without blocking main loop."""
        print(f"{CYAN}[RidenHealthMonitor] Started - checking every {self.riden_check_interval}s{RESET}")
        while self.riden_monitor_alive:
            try:
                self.check_riden_health()
            except Exception as e:
                print(f"{YELLOW}[RidenHealthMonitor] Unexpected error: {e}{RESET}")
            
            # Sleep in small increments to allow graceful shutdown
            for _ in range(int(self.riden_check_interval * 10)):
                if not self.riden_monitor_alive:
                    break
                time.sleep(0.1)

    def set_riden_out(self, output_ON=True):
        # read current state first
        if not self.riden_available:
            return None
            
        try:
            ride_out_state = self.batclant.get_value("riden", "is_output")

            # only write if state change is needed
            if ride_out_state != output_ON:
                self.batclant.set_value("riden", "set_output", output_ON)

                # optional small delay for hardware to apply change
                time.sleep(0.01)

                # verify after change
                new_state = self.batclant.get_value("riden", "is_output")
                print("Updated output status:", new_state)

                return new_state

            return ride_out_state
        except Exception as e:
            self.riden_available = False
            self.riden_last_error = str(e)
            self.riden_last_error_time = time.time()
            return None

    def initialize_values(self):
        # Check Riden health first
        print("Checking Riden availability...")
        if self.check_riden_health():
            print(f"{GREEN}Riden is available{RESET}")
            # Set Riden values
            try:
                self.set_riden_out(output_ON= True)
                self.batclant.set_value("riden", "set_v_set", self.set_v_set_initial)
                print("V_SET:", self.batclant.get_value("riden", "get_v_set"))
                print("V_OUT:", self.batclant.get_value("riden", "get_v_out"))
                print("I_OUT:", self.batclant.get_value("riden", "get_i_out"))
                print("P_OUT:", self.batclant.get_value("riden", "get_p_out"))
            except Exception as e:
                print(f"{YELLOW}Error initializing Riden values: {e}{RESET}")
                self.riden_available = False
        else:
            print(f"{YELLOW}Riden is NOT available - will operate inverter independently{RESET}")
        
        # Set inverter power (always try)
        try:
            self.batclant.set_value("inverter", "set_power", 0)
            print("Inverter power:", self.batclant.get_value("inverter", "get_power"))
        except Exception as e:
            print(f"Error initializing inverter: {e}")


    def print_status_line(self, 
            import_p=0.0, export_p=0.0, power_diff=0.0, pid_power=0.0,
            L1=0.0, L2=0.0, L3=0.0,
            war_power=0.0, rid_P_out=0.0, current=0.0, v_out=0.0
        ):
            """Prints a color-coded status line of system parameters (skips zeros)."""

            parts = [f"t:{time.strftime('%H:%M:%S')}"]

            def add(label, value, color=RESET, fmt="{:.3f}"):
                if value != 0.0 and value is not None:
                    parts.append(f"{label}:{color}{fmt.format(value)}{RESET}")

            # Color logic
            export_color = BRIGHT_MAGENTA if export_p > 0.01 else RESET
            diff_color   = MAGENTA if power_diff > 0.01 else BRIGHT_CYAN if power_diff < -0.01 else RESET
            inv_color    = YELLOW if war_power > 0.01 else RESET
            rid_color    = BRIGHT_GREEN if rid_P_out > 0.01 else RESET
            curr_color   = BRIGHT_GREEN if current > 0.01 else RESET
            curr_color   = YELLOW if war_power > 0.01 else RESET
            # Base values
            add("i", import_p, BLUE)
            add("e", export_p, export_color)
            add("di", power_diff, diff_color)
            add("pid", pid_power, CYAN)

            # Phases
            add("L1", L1)
            add("L2", L2)
            add("L3", L3)

            # Inverter power (integer watts)
            if war_power:
                parts.append(f"inv:{inv_color}{int(war_power)}{RESET}")

            # Riden data
            add("rid", rid_P_out, rid_color)
            add("I", current, curr_color, fmt="{:.1f}")
            add("V", v_out, fmt="{:.1f}")
            add("Te", self.temp_ext_c, fmt="{:.0f}")
            add("Ti", self.temp_int_c, fmt="{:.0f}")
            print(" ".join(parts))

            # Log to database only if connection is available
            if self.storage is not None:
                try:
                    self.storage.log_store(
                        import_p=import_p,
                        export_p=export_p,
                        power_diff=power_diff,
                        pid_power=pid_power,
                        L1=L1,
                        L2=L2,
                        L3=L3,
                        war_power=war_power,
                        rid_P_out=rid_P_out,
                        current=current,
                        v_out=v_out,
                        temp_ext_c=self.temp_ext_c,
                        temp_int_c=self.temp_int_c
                    )

                    parsed =self.meter.get_recent_parsed()
                    if parsed:
                        self.storage.store(parsed)
                        #print("Parsed meter data:", parsed)
                except Exception:
                    # Silently fail - connection state is logged in P1Storage
                    pass


    def main_loop(self):

        try:
            import_p, export_p, L1, L2, L3 = (self.meter.get_power() + [0.0] * 8)[:5]
                # ---------------------
                # PID calculation
                # ---------------------
            power_diff = import_p - export_p-0.02 - P_adding
            if abs(power_diff) < 0.02:
                power_diff = 0.0


            pid_power = self.pid.adjustPower(power_diff,min_output=self.min_output, max_output=self.max_output) or 0.0
            inv_power = max(0, round(pid_power * 1000))

            self.print_status_line(
                import_p=import_p,
                export_p=export_p,
                power_diff=power_diff,
                pid_power=pid_power,
                L1=L1,
                L2=L2,
                L3=L3,
                war_power=inv_power,
                rid_P_out=self.rid_P_out,
                current=self.current,
                v_out=self.v_out    )
                # ---------------------
                # Device control
                # ---------------------
                        
            if self.riden_available:
                try:
                    self.temp_int_c = self.batclant.get_value("riden", "get_int_c")
                    self.temp_ext_c = self.batclant.get_value("riden", "get_ext_c")
                    self.v_out = self.batclant.get_value("riden", "get_v_out")
                    #self.set_riden_out(output_ON=True)  # Ensure Riden output is ON if available
                    #print(f"Riden temperatures: int={self.temp_int_c}C, ext={self.temp_ext_c}C, V_out={self.v_out}V")
                    
                except Exception as e:
                    print(f"{YELLOW}Warning: Failed to read temperatures: {e}{RESET}")
                    self.riden_available = False
                    self.temp_ext_c = 0.0
                    self.temp_int_c = 0.0
                    self.v_out= self.set_v_set_initial
            else:
                self.temp_ext_c = 0.0
                self.temp_int_c = 0.0
                self.v_out= self.set_v_set_initial
            
            if self.temp_ext_c>self.temp_max_allowed:
                print(f"{YELLOW}Warning: Riden external temperature high: {self.temp_ext_c}C{RESET}")
                max_current_T=30.0
                self.min_output=-1.500
            else:
                max_current_T=self.max_current
                self.min_output=-1.8


            if pid_power >= 0:
                    # Discharge via 2 inverters
                double_inv_power = inv_power / 2
                if self.v_out is not None and self.v_out != 0:
                    self.current= double_inv_power/self.v_out
                    
                try:
                    self.batclant.set_value("inverter", "set_power", double_inv_power)
                except Exception as e:
                    print(f"{YELLOW}Warning: Failed to set inverter power: {e}{RESET}")
                
                # Only control Riden if available
                if self.riden_available:
                    try:
                        self.batclant.set_value("riden", "set_i_set", 0.0)
                        # dont chek keep olways on
                        #status_on=self.batclant.get_value("riden", "is_output")
                        #if status_on:
                        #    self.set_riden_out(output_ON=False)
                    except Exception as e:
                        print(f"{YELLOW}Warning: Failed to control Riden: {e}{RESET}")
                        self.riden_available = False
                    
            else:
                    # Charge via Riden (if available) or standby (if not)
                try:
                    self.batclant.set_value("inverter", "set_power", 0)
                except Exception as e:
                    print(f"{YELLOW}Warning: Failed to set inverter power to 0: {e}{RESET}")
                
                if self.riden_available:
                    try:
                        self.batclant.set_value("riden", "set_output", True)
                        v_out_val = self.batclant.get_value("riden", "get_v_out")
                        self.v_out = v_out_val if v_out_val not in (None, "") else self.set_v_set_initial
                        v_for_calc = self.v_out if self.v_out not in (None, 0) else self.set_v_set_initial

                        self.current = self.pid.PtoI(pid_power, v_for_calc, max_current=max_current_T)
                        p = self.batclant.get_value("riden", "get_p_out")
                        self.rid_P_out = (p or 0.0) / 1000.0
                        
                        self.set_riden_out(output_ON=True)
                        self.batclant.set_value("riden", "set_i_set", self.current)
                    except Exception as e:
                        print(f"{YELLOW}Warning: Failed to control Riden: {e}{RESET}")
                        self.riden_available = False
                        self.rid_P_out = 0.0
                        self.current = 0.0
                else:
                    # Riden unavailable - use fallback values
                    self.v_out = self.set_v_set_initial
                    self.rid_P_out = 0.0
                    #self.current = 0.0
                    if self.riden_error_count <= 1:
                        print(f"{YELLOW}Riden unavailable - standby mode (error: {self.riden_last_error}){RESET}")

            
            return import_p,\
                    export_p,\
                    power_diff,\
                    pid_power,\
                    L1,\
                    L2,\
                    L3,\
                    inv_power,\
                    self.rid_P_out,\
                    self.current,\
                    self.v_out           


            
        except Exception as e:
            print(f"{RED}Error in main loop: {e}{RESET}")
            time.sleep(0.001)


    def run(self):

        self.initialize_values()
      
        while True:
            try:
                values=self.main_loop()
                # RESET WATCHDOG HERE (critical line)
                self.sw_watchdog.reset()
                
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("Interrupted by user")
                break


    def cleanup(self):
        """Clean up resources"""
        try:
            # Stop background threads
            self.riden_monitor_alive = False
            self.sw_watchdog.alive = False
            
            # Wait a bit for threads to finish
            time.sleep(0.2)
            
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
