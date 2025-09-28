import time
from riden_remote import RidenRemote
from P1uitlezen import Meter
from datetime import datetime
import csv
import os


class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = None

    def update(self, measured_value, max_output=None):
        error = measured_value- self.setpoint
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
            elif output < 0:
                self.integral -= error * dt
                output = 0.0
        self.last_error = error
        self.last_time = now
        print(f"PID Debug -> P: {self.kp * error:.2f}, I: {self.ki * self.integral:.2f}, D: {self.kd * derivative:.2f}, Output: {output:.2f}")
        return output

class BatLoader:
    BRIGHT_PINK = "\033[95m"  # bright magenta / pink
    RESET       = "\033[0m"
    BLACK       = "\033[30m"
    RED         = "\033[31m"
    GREEN       = "\033[32m"
    YELLOW      = "\033[33m"
    BLUE        = "\033[34m"
    MAGENTA     = "\033[35m"
    CYAN        = "\033[36m"
    WHITE       = "\033[37m"
    BRIGHT_RED  = "\033[91m"
    BRIGHT_GREEN= "\033[92m"
    BRIGHT_YELLOW="\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA="\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE= "\033[97m"
    
    LOG_FILE = "log.csv"
    def __init__(self, battery_voltage=25.2,max_current=1, riden_ip="192.168.2.38" ):
        self.battery_voltage = battery_voltage
        self.max_current=max_current
        self.meter = Meter()
        self.riden = RidenRemote(ip=riden_ip, port=6030)  # Set your Riden's IP and port
         # Increase kp and kd for faster response, reduce ki to avoid windup
        #self.pid = PIDController(kp=1.0, ki=0.5, kd=0.5, setpoint=0.0)
        self.pid = PIDController(kp=2.0, ki=0.5, kd=1.0, setpoint=0.0)
    def log_to_csv(self, filename=LOG_FILE, **kwargs):
        """
        Log named values into a CSV file with timestamp.
        Example: log_to_csv(current=1.23, v_out=50.1, i_out=0.95)
        """
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
                # Write header if file didn’t exist
                if not file_exists:
                    writer.writeheader()
                writer.writerow(row)

            #print(f"{self.GREEN}✔ Logged to {filename}:{self.RESET} {row}")

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

        

    def required_current_pid(self):
        df = self.get_all_riden_to_df()
        obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0']
        import_p, export_p = self.get_obis_values(df, obis_codes)

        # if export_p is not None:
        #     export_p += 0.4
        # else:
        #     export_p = 0.4  # or set to 0.0, or handle as needed
         
        power_diff = export_p - import_p if import_p is not None and export_p is not None else None
        self.log_to_csv(  import_p=import_p ,export_p =export_p, power_diff=power_diff)
       
        
        if power_diff is not None:
            pid_output = self.pid.update(power_diff, max_output=self.max_current)
            safe_current = max(0.0, min(self.max_current, pid_output))
            print(
                    f"received (-P):{BatLoader.BLUE}{import_p:.2f}{BatLoader.RESET}[kW], "
                    f"delivered (+P): {BatLoader.GREEN}{export_p:.2f}{BatLoader.RESET}[kW], "
                    f"power_diff:{BatLoader.MAGENTA} {power_diff:.2f} {BatLoader.RESET}[kW], "
                    f"cal current: {BatLoader.YELLOW}{safe_current:.2f}{BatLoader.RESET} [A] "
                )            
            return safe_current
        else:
            print("Could not calculate required current due to missing OBIS values.")
            return 0.0
        
        
    def riden_drv(self):
        required_current=self.required_current_pid()
        required_current_min = max(0, required_current)
        required_current = min(self.max_current, required_current_min)  # Limit to max current
        try:
            self.riden.set_v_set(self.battery_voltage)
            self.riden.send_command('set_i_set', args=[required_current])

            v_out = self.riden.send_command('get_v_out').get('result', None)
            i_out = self.riden.send_command('get_i_out').get('result', None)
            Pow=v_out*i_out *0.001 if v_out is not None and i_out is not None else None

            v_out = v_out if v_out is not None else 0.0
            i_out = i_out if i_out is not None else 0.0
            Pow = Pow if Pow is not None else 0.0
            print(f"Riden Output - Voltage: {v_out} V, , Current: {i_out} A, Power: {BatLoader.BRIGHT_GREEN} {Pow:.3f} {BatLoader.RESET}  kW")

            # Set output ON or OFF
            self.riden.set_output(True)   # Turn output ON
            # riden.set_output(False)  # Turn output OFF
        except OSError as e:
            print(f"{BatLoader.BRIGHT_PINK} Network error: {e}{BatLoader.RESET}")
            


        
if __name__ == "__main__":
    bat_loader=BatLoader(battery_voltage=57,max_current=30)
    while True:
        print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        bat_loader.riden_drv()
        time.sleep(1)  # Wait for 60 seconds before next adjustment


