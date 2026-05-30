from lib.P1uitlezen import Meter
from lib.batclant import Batclant
import time
from lib.PIDController import PIDController
from lib.P1Storage import P1Storage
from lib.riden_manager import RidenManager
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
        self.Vmax_bat=57.5
        self.vmin_bat=46.0
        
        self.pid = PIDController(kp=2.5, ki=0.05, kd=0.05,Vmin=self.vmin_bat, Vmax=self.Vmax_bat, setpoint=0.0, max_change_ratio=1.0)
        
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

        self.db_host = "192.168.2.33"
        self.db_user = "admin"
        self.db_password = "aaa"
        self.db_database = "energy"
        self.db_reconnect_cooldown = 5.0
        self._last_db_connect_attempt = 0.0
        self._db_connection_warned = False

        self.riden = RidenManager(self.batclant, v_max_bat=self.Vmax_bat, check_interval=10.0)

        # sw watchdog to ensure script restarts if it hangs for some reason (e.g. meter thread issues)
        self.sw_watchdog = SoftwareWatchdog(timeout=60)
        threading.Thread(target=self.sw_watchdog.run, daemon=True,name="SoftwareWatchdog").start()

        # Riden health monitoring (non-blocking background thread)
        self.riden.start_monitor()

        self._try_connect_storage(force=True)

    def initialize_values(self):
        # Check Riden health first
        print("Checking Riden availability...")
        if self.riden.initialize():
            print(f"{GREEN}Riden is available{RESET}")
        else:
            print(f"{YELLOW}Riden is NOT available - will operate inverter independently{RESET}")

        # Set inverter power (always try)
        try:
            self.batclant.set_value("inverter", "set_power", 0)
            print("Inverter power:", self.batclant.get_value("inverter", "get_power"))
        except Exception as e:
            print(f"Error initializing inverter: {e}")


    def _try_connect_storage(self, force=False):
        now = time.time()
        if not force and now - self._last_db_connect_attempt < self.db_reconnect_cooldown:
            return
        self._last_db_connect_attempt = now

        try:
            storage = P1Storage(
                host=self.db_host,
                user=self.db_user,
                password=self.db_password,
                database=self.db_database
            )
            if storage.connection is not None and storage.cursor is not None:
                self.storage = storage
                self._db_connection_warned = False
                print("Database connection established")
            else:
                storage.close()
                if not self._db_connection_warned:
                    print(f"{YELLOW}WARNING: Database not available{RESET}")
                    self._db_connection_warned = True
        except Exception as e:
            if not self._db_connection_warned:
                print(f"{YELLOW}WARNING: Failed to initialize database: {e}{RESET}")
                self._db_connection_warned = True


    def print_status_line(self, 
            import_p=0.0, export_p=0.0, power_diff=0.0, pid_power=0.0,
            L1=0.0, L2=0.0, L3=0.0,
            war_power=0.0, rid_P_out=0.0, current=0.0, v_out=0.0,taper_factor=1.0
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
            vout_color    = BRIGHT_WHITE if v_out == self.Vmax_bat else RESET
            # Base values
            add("i", import_p, BLUE)
            add("e", export_p, export_color)
            add("di", power_diff, diff_color)
            add("pid", pid_power, CYAN)

            # Phases
            #add("L1", L1)
           # add("L2", L2)
           # add("L3", L3)

            # Inverter power (integer watts)
            if war_power:
                parts.append(f"inv:{inv_color}{int(war_power)}{RESET}")

            # Riden data
            add("rid", rid_P_out, rid_color)
            add("I", current, curr_color, fmt="{:.1f}")

            if taper_factor < 1.0:
                add("tap", taper_factor, YELLOW, fmt="{:.2f}")
            
            add("V", v_out,vout_color, fmt="{:.1f}")
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
            else:
                self._try_connect_storage()
            


    def main_loop(self):
        taper_factor = 1.0  # default to no tapering
        try:
            #get data from metter P1
            import_p, export_p, L1, L2, L3 = (self.meter.get_power() + [0.0] * 8)[:5]
            # get data from riden
            if self.riden.available:
                try:
                    self.riden.get_full_status()
                    if self.riden.v_set != self.Vmax_bat:
                        self.riden.initialize()  # re-apply settings if we detect a change (e.g. after reset)
                   
                    self.temp_int_c = self.riden.temp_int
                    self.temp_ext_c = self.riden.temp_ext
                    self.v_out      = self.riden.v_out
                    
                    self.rid_P_out  = (self.riden.p_out or 0.0) / 1000.0
                    
                    if not self.riden.output:
                            self.riden.set_output(True)

                except Exception as e:
                    print(f"{YELLOW}Warning: Failed to read Riden status: {e}{RESET}")
                    self.riden.available = False
                    self.temp_ext_c = 0.0
                    self.temp_int_c = 0.0
                    self.v_out = self.Vmax_bat
            else:
                self.temp_ext_c = 0.0
                self.temp_int_c = 0.0
                self.v_out = self.Vmax_bat

            
            # Adjust max current and min output based on riden temperature
            if self.temp_ext_c>self.temp_max_allowed:
                print(f"{YELLOW}Warning: Riden external temperature high: {self.temp_ext_c}C{RESET}")
                max_current_T=30.0
                self.min_output=-1.500
            else:
                max_current_T=self.max_current
                self.min_output=-1.8


                # ---------------------
                # PID calculation
                # ---------------------

            # Check if battery is stuck at max voltage and reset PID if needed
            self.pid.check_and_reset_if_stuck_at_max_v(self.riden.v_out)  


            power_diff = import_p - export_p-0.02 - P_adding
            if abs(power_diff) < 0.02:
                power_diff = 0.0

            pid_power = self.pid.adjustPower(power_diff, min_output=self.min_output, max_output=self.max_output) or 0.0
            inv_power = max(0, round(pid_power * 1000))

            #execute changes to inverter and Riden based on PID output
            if pid_power >= 0:
                    # Discharge via 2 inverters
                double_inv_power = inv_power / 2
                if self.v_out is not None and self.v_out != 0:
                    self.current= inv_power/self.v_out
                    
                try:
                    self.batclant.set_value("inverter", "set_power", double_inv_power)
                except Exception as e:
                    print(f"{YELLOW}Warning: Failed to set inverter power: {e}{RESET}")
                
                # Only control Riden if available
                if self.riden.available:
                    try:
                        self.batclant.set_value("riden", "set_i_set", 0.0)

                    except Exception as e:
                        print(f"{YELLOW}Warning: Failed to control Riden: {e}{RESET}")
                        self.riden.available = False
                    
            else:
                    # Charge via Riden (if available) or standby (if not)
                try:
                    self.batclant.set_value("inverter", "set_power", 0)
                except Exception as e:
                    print(f"{YELLOW}Warning: Failed to set inverter power to 0: {e}{RESET}")
                
                if self.riden.available:
                    try:
                        if not self.riden.output:
                            self.riden.set_output(True)

                        self.v_out = self.riden.v_out or self.Vmax_bat

                        v_for_calc = self.v_out if self.v_out not in (None, 0) else self.Vmax_bat

                        self.current = self.pid.PtoI(pid_power, v_for_calc, max_current=max_current_T)


                        # Apply tapering based on battery voltage
                        self.current, taper_factor = self.pid.limit_current_with_taper(
                            self.current,
                            self.v_out,
                            self.max_current
                        )

                        #if taper_factor < 1.0:
                        #    print(f"Taper factor: {taper_factor:.2f} | Current: {self.current:.2f} A | V: {self.v_out:.2f} V")


                        #self.rid_P_out = (self.riden.p_out or 0.0) / 1000.0
                        self.batclant.set_value("riden", "set_i_set", self.current)

                    

                        

                    except Exception as e:
                        print(f"{YELLOW}Warning: Failed to control Riden: {e}{RESET}")
                        self.riden.available = False
                        self.rid_P_out = 0.0
                        self.current = 0.0
                else:
                    # Riden unavailable - use fallback values
                    self.v_out = self.Vmax_bat
                    self.rid_P_out = 0.0
                    #self.current = 0.0
                    if self.riden.error_count <= 1:
                        print(f"{YELLOW}Riden unavailable - standby mode (error: {self.riden.last_error}){RESET}")
            
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
                v_out=self.v_out,
                taper_factor=taper_factor)
            
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
                    self.v_out,\
                    taper_factor


            
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
            self.riden.stop_monitor()
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
