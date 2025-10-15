from lib.P1uitlezen import Meter
from lib.batclant import Batclant
import time
from lib.PIDController import PIDController
import os
import csv
import pandas as pd

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


file_name="/home/pi/Desktop/prog/riden/data_log.csv"
set_v_set_initial=57.0

kp = 0.5
ki = 0.05
kd = 0.01

setpoint=0.0  
meter = Meter()
storage = Batclant()
pid = PIDController( kp=kp, ki=ki, kd=kd, setpoint=setpoint)



# Ensure CSV file has headers
if not os.path.exists(file_name):
    with open(file_name, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp",
            "import_kW",
            "export_kW",
            "power_diff_kW",
            "pid_power_kW",
            "L1_kW",
            "L2_kW",
            "L3_kW"
        ])
def get_all_riden_to_df():
    try:
        meter.connect()  # connect once
        parsed_data = meter.read_telegram()  # read full telegram
        df = meter.to_dataframe(parsed_data)
        return df
    except Exception as e:
        print(f"Error reading DSMR meter: {e}")
        return pd.DataFrame()  # fallback empty


# def get_all_riden_to_df():
#     meter.connect()
#     parsed_data = meter.read_lines(count=35)
#     meter.close()
#     df = meter.to_dataframe(parsed_data)
#     return df

def get_listed_obis_values( df, obis_list):
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

def get_AC_instantenious(obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0','1-0:21:.7.0', '1-0:41:.7.0', '1-0:41:.7.0']):
    df = get_all_riden_to_df()
    #obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0','1-0:21:.7.0', '1-0:41:.7.0', '1-0:41:.7.0']
    AC_values = get_listed_obis_values(df, obis_codes)
    return AC_values

# import_p, export_p= get_AC_instantenious()[:2]
# print(import_p, export_p)
def initialize_values():
    # Set Riden values

    storage.set_value("riden", "set_v_set", set_v_set_initial)
    # Get Riden values
    output_ON=storage.get_value("riden", "is_output")
    print("Output status:",output_ON )
    if not output_ON:
        storage.set_value("riden", "set_output", True)
        print("Riden output turned ON")

        

    print("V_SET:", storage.get_value("riden", "get_v_set"))
    print("V_OUT:", storage.get_value("riden", "get_v_out"))
    print("I_OUT:", storage.get_value("riden", "get_i_out"))
    print("P_OUT:", storage.get_value("riden", "get_p_out"))
    # Set and get inverter power
    storage.set_value("inverter", "set_power", 0)
    print("Inverter power:", storage.get_value("inverter", "get_power"))

def PtoI(power_kwatts, voltage=set_v_set_initial, max_current=30.0):
    if voltage==0:
        voltage=set_v_set_initial
        
    current = abs( power_kwatts * 1000 / voltage)
    safe_current = round(min(current, max_current),3)
    return safe_current



def main_loop():
    deadband=0.02  # kW
    initialize_values()
    while True:
        try:
            import_p, export_p,L1,L2,L3= get_AC_instantenious()[:5]
            #export_p=export_p+0.2
            if None in [import_p, export_p]:
                print(f"{RED}Invalid P1 data, retrying...{RESET}")
                time.sleep(0.5)
                continue
            #calcualte power difference
            power_diff = import_p-export_p  if import_p is not None and export_p is not None else 0.0
            print(f"Import: {import_p:.3f} kW, Export: {export_p:.3f} kW P_dif: {MAGENTA} {power_diff:.3f} {RESET} kW, L1:{L1:.3f}, L2:{L2:.3f}, L3:{L3:.3f}")
            
            #pid control
            pid_power = pid.adjustPower(power_diff)
            print(f"PID output (power setpoint): {CYAN}{pid_power:.3f}{RESET} kW")
           
            #when stable do not change power setpoints
            if -deadband <= power_diff <= deadband:
                invert_P=storage.get_value("inverter", "get_power")/1000
                rid_P_out=storage.get_value("riden", "get_p_out")/1000
                print(f"Low P_dif ±{deadband:.3f} invert_P: {YELLOW}{invert_P:.3f}{RESET}, rid_P_out:{BRIGHT_GREEN} {rid_P_out:.3f}{RESET} kW ")
                time.sleep(0.5)
                continue
            #set power to inverter
            if  pid_power >= 0:
                war_power=round(pid_power*1000)
                storage.set_value("riden", "set_i_set", 0.0)
                storage.set_value("inverter", "set_power", war_power)
                print(f"Setting inverter power to: {YELLOW}{war_power:.2f}{RESET} W")
            #set current to riden
            elif pid_power < 0:
                storage.set_value("inverter", "set_power", 0)
                v_out = storage.get_value("riden", "get_v_out")
                current=PtoI(pid_power,v_out )
                storage.set_value("riden", "set_i_set", current)
                print(f"Setting current to: {BRIGHT_GREEN}{current:.2f}{RESET} get_V_out:  {v_out:.2f} V")

            print("-----")
            #log data to file
            with open(file_name, "a") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{import_p:.3f},{export_p:.3f},{power_diff:.3f},{pid_power:.3f},{L1:.3f},{L2:.3f},{L3:.3f}\n")

            time.sleep(0.5)

        except Exception as e:
            print(f"{RED} Error in main loop: {e}, activating safety mode...{RESET}")
            try:
                # SAFETY: reset devices
                storage.set_value("inverter", "set_power", 0)
                storage.set_value("riden", "set_i_set", 0.0)
            except Exception as e2:
                print(f"{RED}Error setting safe values: {e2}{RESET}")

try:
    main_loop()
except KeyboardInterrupt:
    print("Program interrupted by user, sending safe values...")
finally:
    # SAFETY: always reset devices
    try:
        storage.set_value("inverter", "set_power", 0)
        storage.set_value("riden", "set_i_set", 0.0)
    except Exception as e:
        print(f"Error setting safe values: {e}")
    storage.close()