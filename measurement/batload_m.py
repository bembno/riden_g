import time
from riden_remote import RidenRemote
from P1uitlezen import Meter
from datetime import datetime



class PIDController:
    def __init__(self, kp=1.0, ki=0.0, kd=0.0, setpoint=0.0, output_limits=(0, None)):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint = setpoint
        self.integral = 0.0
        self.last_error = 0.0
        self.last_time = None
        self.output_limits = output_limits  # (min, max)

    def update(self, measured_value):
        error = measured_value-self.setpoint   # Note: setpoint - measured_value for standard PID
        now = time.time()
        
        # Handle first call
        if self.last_time is None:
            self.last_time = now
            self.last_error = error
            return 0.0
        
        dt = now - self.last_time
        if dt <= 0:
            return 0.0
        
        # Proportional term
        p_term = self.kp * error
        
        # Integral term with anti-windup
        self.integral += error * dt
        i_term = self.ki * self.integral
        
        # Derivative term
        derivative = (error - self.last_error) / dt
        d_term = self.kd * derivative
        
        # Calculate output
        output = p_term + i_term + d_term
        
        # Apply output limits with anti-windup
        if self.output_limits[0] is not None and output < self.output_limits[0]:
            output = self.output_limits[0]
            # Anti-windup: don't accumulate integral if output is limited
            self.integral -= error * dt
        
        if self.output_limits[1] is not None and output > self.output_limits[1]:
            output = self.output_limits[1]
            # Anti-windup
            self.integral -= error * dt
        
        self.last_error = error
        self.last_time = now
        
        print(f"PID Debug -> Error: {error:.2f}, P: {p_term:.2f}, I: {i_term:.2f}, D: {d_term:.2f}, Output: {output:.2f}")
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
         # Increase kp and kd for faster response, reduce ki to avoid windup
        self.pid = PIDController(kp=1.0, ki=0.5, kd=0.5, setpoint=0.0)
    
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
        try:
            df = self.get_all_riden_to_df()
            if df is None or df.empty:
                print("No data received from meter")
                return 0.0
                
            obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0']
            import_p, export_p = self.get_obis_values(df, obis_codes)
            
            if import_p is None or export_p is None:
                print("Missing OBIS values")
                return 0.0
            export_p=0.4
            power_diff = export_p - import_p
            pid_output = self.pid.update(power_diff)
            
            # Clamp output to safe range
            safe_current = max(0.0, min(self.max_current, pid_output))
            print(
                    f"received (-P):{BatLoader.BLUE}{import_p:.2f}{BatLoader.RESET}[kW], "
                    f"delivered (+P): {BatLoader.GREEN}{export_p:.2f}{BatLoader.RESET}[kW], "
                    f"power_diff:{BatLoader.MAGENTA} {power_diff:.2f} {BatLoader.RESET}[kW], "
                    f"cal current: {BatLoader.YELLOW}{safe_current:.2f}{BatLoader.RESET} [A] "
                )  
            # print(f"Import: {import_p:.2f}kW, Export: {export_p:.2f}kW, "
            #     f"Diff: {power_diff:.2f}kW, Current: {safe_current:.2f}A")
            
            return safe_current
            
        except Exception as e:
            print(f"Error in required_current_pid: {e}")
            return 0.0
            
            
    def riden_drv(self):
            try:
                required_current = self.required_current_pid()
                    
                    # Set voltage and current
                self.riden.set_v_set(self.battery_voltage)
                self.riden.send_command('set_i_set', args=[required_current])
                self.riden.set_output(True)
                    
                    # Read back actual values for verification
                v_out = self.riden.send_command('get_v_out').get('result', 'N/A')
                i_out = self.riden.send_command('get_i_out').get('result', 'N/A')
                    
                print(f"Riden Status - Voltage: {v_out}V, Current: {i_out}A")
                    
            except Exception as e:
                print(f"Error in riden_drv: {e}")
                    # Consider turning output off on error
                try:
                    self.riden.set_output(False)
                except:
                    pass




            # #required_current=self.required_current()
            # #self.riden.set_output(False)   # Turn output Off  
            # required_current=self.required_current_pid()
            # required_current_min = max(0, required_current)
            # required_current = min(self.max_current, required_current_min)  # Limit to max current
            # self.riden.set_v_set(self.battery_voltage)

            # self.riden.send_command('set_i_set', args=[required_current])

    
            # #print(f"Set voltage to {self.battery_voltage:.2f}V")
            # #print(f"Set current to {required_current:.2f}A: ")
            # v_out = self.riden.send_command('get_v_out').get('result', None)
            # i_out = self.riden.send_command('get_i_out').get('result', None)
            # print(f"Riden Output - Voltage: {v_out} V, Current: {i_out} A")
        
            # # Set output ON or OFF
            # self.riden.set_output(True)   # Turn output ON
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
    def log_message(self, message):
        with open(self.LOG_FILE, 'a') as f:
            f.write(f"{datetime.now().isoformat()}: {message}\n")
        print(message)

        
if __name__ == "__main__":
    bat_loader = BatLoader(battery_voltage=50.4, max_current=5)
    
    # Add graceful shutdown handling
    try:
        while True:
            print(f"\n--- {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
            bat_loader.riden_drv()
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        # Turn off output on shutdown
        try:
            bat_loader.riden.set_output(False)
            print("Output turned off")
        except:
            pass
    except Exception as e:
        print(f"Unexpected error: {e}")


