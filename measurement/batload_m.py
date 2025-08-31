import time
from riden_remote import RidenRemote
from P1uitlezen import Meter
from datetime import datetime



class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = None

    def update(self, measured_value):
        error = self.setpoint - measured_value
        now = time.time()
        dt = 1.0
        if self.last_time is not None:
            dt = now - self.last_time
        self.integral += error * dt
        derivative = (error - self.last_error) / dt if dt > 0 else 0.0
        output = self.kp * error + self.ki * self.integral + self.kd * derivative
        self.last_error = error
        self.last_time = now
        return output

class BatLoader:
    GREEN = "\033[32m"
    BLUE = "\033[34m"
    YELLOW = "\033[33m"
    LOG_FILE = "log.txt"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"

    def __init__(self, battery_voltage=25.2,max_current=1, riden_ip="192.168.2.29" ):
        self.battery_voltage = battery_voltage
        self.max_current=max_current
        self.meter = Meter()
        self.riden = RidenRemote(ip=riden_ip, port=6030)  # Set your Riden's IP and port
        self.pid = PIDController(kp=2.0, ki=0.1, kd=0.05, setpoint=0.0)  # Tune as needed

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

    # def current_to_battery(self, power_diff):
        
    #     current=(power_diff * 1000) / self.battery_voltage
        
    #     return current

    # def required_current(self):
    #     df = self.get_all_riden_to_df()
    #     obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0']
    #     import_p, export_p = self.get_obis_values(df, obis_codes)
    #     power_diff = export_p - import_p if import_p is not None and export_p is not None else None
                
    #     if power_diff is not None:
    #         required_current = self.current_to_battery(power_diff)
    #         print(f"received (-P):{BatLoader.BLUE}{import_p}{BatLoader.RESET}[kW],delivered (+P): {BatLoader.GREEN}{export_p}{BatLoader.RESET}[kW], power_diff: {power_diff:.2} [kW], cal current: {BatLoader.YELLOW}{required_current:.2f}{BatLoader.RESET} [A]")
    #         return required_current
    #     else:
    #         print("Could not calculate required current due to missing OBIS values.")
    #         return 0.0
        

    def required_current_pid(self):
        df = self.get_all_riden_to_df()
        obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0']
        import_p, export_p = self.get_obis_values(df, obis_codes)
        power_diff = export_p - import_p if import_p is not None and export_p is not None else None
        if power_diff is not None:
            # PID output is the adjustment to current to drive power_diff to zero
            pid_output = self.pid.update(power_diff)
            #print(f"PID: power_diff={power_diff:.3f} [kW], pid_output={pid_output:.3f} [A]")
            print(f"received (-P):{BatLoader.BLUE}{import_p}{BatLoader.RESET}[kW],delivered (+P): {BatLoader.GREEN}{export_p}{BatLoader.RESET}[kW], power_diff: {power_diff:.2} [kW], cal current: {BatLoader.YELLOW}{pid_output:.2f}{BatLoader.RESET} [A]")
            return max(0.0, pid_output)
        else:
            print("Could not calculate required current due to missing OBIS values.")
            return 0.0
    def riden_drv(self):
        #required_current=self.required_current()
        required_current=self.required_current_pid()
        required_current_min = max(0, required_current)
        required_current = min(self.max_current, required_current_min)  # Limit to max current
        self.riden.set_v_set(self.battery_voltage)

        self.riden.send_command('set_i_set', args=[required_current])
        
        print(f"Set voltage to {self.battery_voltage:.2f}V")
        print(f"Set current to {required_current:.2f}A: ")
        v_out = self.riden.send_command('get_v_out').get('result', None)
        i_out = self.riden.send_command('get_i_out').get('result', None)
        print(f"Riden Output - Voltage: {v_out} V, Current: {i_out} A")
    
        # Set output ON or OFF
        self.riden.set_output(True)   # Turn output ON
        # riden.set_output(False)  # Turn output OFF

        # # Set voltage (in Volts)
        # riden.set_v_set(12.5)    # Set output voltage to 12.5V

        # # Set current (in Amps)
        # riden.send_command('set_i_set', args=[2.0])  # Set output current to 2.0A

        # # Set power (in Watts) - if supported by your model/firmware
        # riden.send_command('set_p_set', args=[30.0])  # Set output power to 30W

        # # You can also read back values:
        # v_out = riden.send_command('get_v_out').get('result')
        # i_out = riden.send_command('get_i_out').get('result')"



        
if __name__ == "__main__":
    bat_loader=BatLoader(battery_voltage=25.2,max_current=5)
    while True:
        print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
        bat_loader.riden_drv()
        time.sleep(1)  # Wait for 60 seconds before next adjustment


