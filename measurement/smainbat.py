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
        self.pid = PIDController(kp=0.4, ki=0.08, kd=0.005, setpoint=0.0, max_change_ratio=2.0)
        
        if not self.meter.wait_until_ready(timeout=5):
                    print("Warning: meter did not become ready within 5 seconds")
        # Initialize database storage (optional)
        self.storage = None
        self.set_v_set_initial=57.2

        self.rid_P_out=0.0
        self.current=0.0
        self.v_out=0.0

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
            
    def set_riden_out(self, output_ON=True):
        # read current state first
        ride_out_state = self.batclant.get_value("riden", "is_output")

        # only write if state change is needed
        if ride_out_state != output_ON:
            self.batclant.set_value("riden", "set_output", output_ON)

            # optional small delay for hardware to apply change
            time.sleep(0.1)

            # verify after change
            new_state = self.batclant.get_value("riden", "is_output")
            print("Updated output status:", new_state)

            return new_state

        return ride_out_state

    def initialize_values(self):
        # Set Riden values
        try:
            self.set_riden_out(output_ON= True)
            self.batclant.set_value("riden", "set_v_set", self.set_v_set_initial)
            print("V_SET:", self.batclant.get_value("riden", "get_v_set"))
            print("V_OUT:", self.batclant.get_value("riden", "get_v_out"))
            print("I_OUT:", self.batclant.get_value("riden", "get_i_out"))
            print("P_OUT:", self.batclant.get_value("riden", "get_p_out"))
            # # Set and get inverter power
            self.batclant.set_value("inverter", "set_power", 0)
            print("Inverter power:", self.batclant.get_value("inverter", "get_power"))
        except Exception as e:
            print(f"Error initializing Riden and inverter values: {e}")


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
                        v_out=v_out
                    )
                except Exception:
                    # Silently fail - connection state is logged in P1Storage
                    pass


    def main_loop(self):

        try:
            import_p, export_p, L1, L2, L3 = (self.meter.get_power() + [0.0] * 8)[:5]
                # ---------------------
                # PID calculation
                # ---------------------
            power_diff = import_p - export_p
            pid_power = self.pid.adjustPower(power_diff) or 0.0
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
                v_out=self.v_out
                                    )
                # ---------------------
                # Device control
                # ---------------------
            if pid_power >= 0:
                    # Discharge via inverter
                self.batclant.set_value( "inverter", "set_power", inv_power)
                self.batclant.set_value( "riden","set_i_set", 0.0)
                status_on=self.batclant.get_value("riden", "is_output")
                if status_on:
                    self.set_riden_out(output_ON= False)
                    
            else:
                    # Charge via Riden
                self.batclant.set_value( "inverter", "set_power", 0)
                self.batclant.set_value( "riden", "set_output", True)

                v_out_val = self.batclant.get_value("riden", "get_v_out")
                self.v_out = v_out_val if v_out_val not in (None, "") else v_out
                v_for_calc = self.v_out if self.v_out not in (None, 0) else self.set_v_set_initial

                self.current = self.pid.PtoI( pid_power, v_for_calc)
                p = self.batclant.get_value( "riden", "get_p_out")
                self.rid_P_out = (p or 0.0) / 1000.0
                    
                self.set_riden_out(output_ON= True)
                self.batclant.set_value( "riden","set_i_set", self.current)


            
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
            time.sleep(2.0)


    def run(self):

        self.initialize_values()
      
        while True:
            try:
                values=self.main_loop()
                #print(*values)
                
               # self.print_status_line(*values)
                time.sleep(0.5)
            except KeyboardInterrupt:
                print("Interrupted by user")
                break


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
