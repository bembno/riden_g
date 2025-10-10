import time
try:
    # When run as a package
    from .riden_remote import RidenRemote
    from .P1uitlezen import Meter
except Exception:
    # When run as a script (no package), fall back to sibling imports
    from riden_remote import RidenRemote
    from P1uitlezen import Meter
from datetime import datetime
import csv
import os
import argparse


class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = None

    def update(self, measured_value, min_output=-0.9, max_output=1.8):
        error = measured_value - self.setpoint
        now = time.time()
        dt = 1.0
        if self.last_time is not None:
            dt = now - self.last_time
        self.integral += error * dt
        derivative = (error - self.last_error) / dt if dt > 0 else 0.0
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        # Anti-windup: clamp integral if output would exceed max_output
        if max_output is not None and self.ki != 0.0:
            if output > max_output:
                # Remove the last integration step
                self.integral -= error * dt
                output = max_output
            elif output < min_output:
                self.integral -= error * dt
                output = min_output
        self.last_error = error
        self.last_time = now
        return output


class BatLoaderS:
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

    LOG_FILE = "log.csv"

    def __init__(self, battery_voltage=25.2, max_current=1, riden_ip="192.168.2.38", use_power=False, inverter_port="/dev/ttyUSB1", inverter_baud=4800, inverter_max_power=900):
        self.battery_voltage = battery_voltage
        self.max_current = max_current
        self.meter = Meter()
        self.riden = RidenRemote(ip=riden_ip, port=6030)

        self.pid = PIDController(kp=.3, ki=0.05, kd=0.1, setpoint=-0.05)

        # If use_power True, send desired power (watts) to riden server via set_power command
        self.use_power = use_power
        self.inverter_port = inverter_port
        self.inverter_baud = inverter_baud
        self.inverter_max_power = inverter_max_power

    def log_to_csv(self, filename=LOG_FILE, **kwargs):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = {"timestamp": timestamp, **kwargs}
        try:
            file_exists = False
            try:
                with open(filename, "r"):
                    file_exists = True
            except FileNotFoundError:
                pass

            with open(filename, mode="a", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=row.keys())
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)
        except Exception as e:
            print(f"{self.BRIGHT_PINK} Error writing to CSV: {e}{self.RESET}")

    def get_all_riden_to_df(self):
        self.meter.connect()
        parsed_data = self.meter.read_lines(25)
        self.meter.close()
        df = self.meter.to_dataframe(parsed_data)
        return df

    def get_obis_values(self, df, obis_list):
        values = []
        for obis in obis_list:
            row = df[df['OBIS'] == obis]
            if not row.empty:
                try:
                    values.append(float(row.iloc[0]['Value']))
                except Exception:
                    values.append(None)
            else:
                values.append(None)
        return values

    def required_power_pid(self):
        df = self.get_all_riden_to_df()
        obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0']
        import_p, export_p = self.get_obis_values(df, obis_codes)

        power_diff = export_p - import_p if import_p is not None and export_p is not None else None
        self.log_to_csv(import_p=import_p, export_p=export_p, power_diff=power_diff)
        if power_diff is not None:
            pid_output = self.pid.update(power_diff, max_output=self.max_current)
            #safe_current = max(0.0, min(self.max_current, pid_output))
            print(
                f"received (-P):{BatLoaderS.BLUE}{import_p:.2f}{BatLoaderS.RESET}[kW], "
                f"delivered (+P): {BatLoaderS.GREEN}{export_p:.2f}{BatLoaderS.RESET}[kW], "
                f"power_diff:{BatLoaderS.MAGENTA} {power_diff:.2f} {BatLoaderS.RESET}[kW], "
                f"pid_output: {BatLoaderS.YELLOW}{pid_output:.2f}{BatLoaderS.RESET} [kW] "
            )
            return pid_output
        else:
            print("Could not calculate required current due to missing OBIS values.")
            return 0.0

    def send_set_power(self, power_watts: int, via_inverter: bool = True):
        """Send a set_power RPC to the Riden server. Returns the server response dict."""
        kwargs = {
            "power_watts": int(power_watts),
            "via_inverter": bool(via_inverter),
            "inverter_port": self.inverter_port,
            "baud": self.inverter_baud,
            "max_power": self.inverter_max_power,
        }
        try:
            resp = self.riden.send_command('set_power', kwargs=kwargs)
            return resp
        except Exception as e:
            return {"error": f"send_set_power failed: {e}"}

    def riden_drv(self):
        PID_power = self.required_power_pid()
        #required_current_min = max(0, required_current)
        #required_current = min(self.max_current, required_current_min)
        try:
            # keep setting v_set as before
            self.riden.set_v_set(self.battery_voltage)


            
            v_out = self.riden.send_command('get_v_out').get('result', None)
            required_current=PID_power*1000/self.battery_voltage
            #print(f"Calculated current from PID power: {required_current} A")
            # set current (amps) as before
            if required_current>0:
                self.riden.send_command('set_i_set', args=[required_current])
            else:
                self.riden.send_command('set_i_set', args=[0.0])
                desired_power_w=PID_power*-1000
                resp = self.send_set_power(desired_power_w, via_inverter=True)
                #print(f"server resp: {resp}")
                print(f" \t power_set: {BatLoaderS.YELLOW}{resp['result']['power_set'] }{BatLoaderS.RESET} [W] ")


            i_out = self.riden.send_command('get_i_out').get('result', None)
            Pow = v_out * i_out * 0.001 if v_out is not None and i_out is not None else None
            
         
            try:
                if v_out is None or i_out is None:
                    raise ValueError("No response from Riden device")
                print(f"Riden Output - Voltage: {v_out} V, Current: {i_out} A, Power: {BatLoaderS.BRIGHT_GREEN} {Pow:.3f} {BatLoaderS.RESET} kW")
            except Exception as e:
                print(f"Riden device not responding:{BatLoaderS.BRIGHT_PINK} {e}{BatLoaderS.RESET}")
                time.sleep(2)
                return

            self.riden.set_output(True)
        except OSError as e:
            print(f"{BatLoaderS.BRIGHT_PINK} Network error: {e}{BatLoaderS.RESET}")


def main():
    parser = argparse.ArgumentParser(description="BatLoaderS - Batloader with optional set_power forwarding")
    parser.add_argument('--voltage', '-v', type=float, default=57.0, help='Battery voltage')
    parser.add_argument('--max-current', '-m', type=float, default=30.0, help='Maximum current [A]')
    parser.add_argument('--riden-ip', type=str, default='192.168.2.38', help='Riden server IP')
    parser.add_argument('--use-power', action='store_true', help='Use set_power RPC instead of set_i_set')
    parser.add_argument('--inverter-port', type=str, default="/dev/ttyUSB1", help='Optional inverter serial port to forward to')
    parser.add_argument('--inverter-baud', type=int, default=4800, help='Inverter serial baud')
    args = parser.parse_args()

    bat_loader = BatLoaderS(battery_voltage=args.voltage, max_current=args.max_current, riden_ip=args.riden_ip, use_power=args.use_power, inverter_port=args.inverter_port, inverter_baud=args.inverter_baud)
    try:
        while True:
            print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
            bat_loader.riden_drv()
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("Interrupted by user - exiting")


if __name__ == "__main__":
    main()
