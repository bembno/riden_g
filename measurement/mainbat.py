from lib.P1uitlezen import Meter
from lib.batclant import Batclant
import time
from lib.PIDController import PIDController
from lib.P1Storage import P1Storage
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

p1 = P1Storage(
    host="localhost",
    user="admin",
    password="aaa",
    database="energy"
)

file_name="/home/pi/Desktop/prog/riden/data_log.csv"
set_v_set_initial=57.0

kp = 0.5
ki = 0.09
kd = 0.01

setpoint=0.0  
meter = Meter()
storage = Batclant()
pid = PIDController( kp=kp, ki=ki, kd=kd, setpoint=setpoint)

last_riden_set = 0
MIN_RIDEN_INTERVAL = 0.15  # 150ms
last_p1 = 0
last_df = pd.DataFrame()

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
def get_all_P1_to_df():
    try:
        global last_p1, last_df

        now = time.time()
        if now - last_p1 < 1:  # DSMR sends once per second
            return last_df     # reuse last telegram
        
        last_p1 = now
        meter.connect()  # connect once
        parsed_data = meter.read_telegram()  # read full telegram
        df = meter.to_dataframe(parsed_data)
        #print (df)
        last_df = df
        return df
    except Exception as e:
        print(f"Error reading DSMR meter: {e}")
        last_df = pd.DataFrame()  # fallback empty
        return last_df

def get_listed_obis_values( df, obis_list):
    if df is None or df.empty or "OBIS" not in df.columns:
        return [None] * len(obis_list)
    
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
    if len(values) == 8:
        values[2] = values[2] - values[5]  # L1 import - export
        values[3] = values[3] - values[6]  # L2 import - export
        values[4] = values[4] - values[7]  # L3
    
    return values

def get_AC_instantenious(obis_codes=None):
    
    if obis_codes is None:
        obis_codes = [
            '1-0:1:.7.0',   # total import (or phase-independent)
            '1-0:2:.7.0',   # total export (or phase-independent)
            '1-0:21:.7.0',  # L1
            '1-0:41:.7.0',  # L2  
            '1-0:61:.7.0',  # L3
            '1-0:22:.7.0',  # -L1
            '1-0:42:.7.0',  # -L2  
            '1-0:62:.7.0'   # -L3
        ]
    df = get_all_P1_to_df()
    AC_values = get_listed_obis_values(df, obis_codes)

    # Store to MariaDB
    p1.store(df)
    #p1.close()
    return AC_values


def set_riden_out(output_ON= True):
    # Get Riden values
    storage.safe_set_value("riden", "set_output", output_ON)
    time.sleep(0.1)
    status_on=storage.safe_get_value("riden", "is_output")
    print("Output start status:",status_on )

def initialize_values():
    # Set Riden values
    try:
        storage.safe_set_value("pindriver", "connect", None)
        set_riden_out(output_ON= True)
        storage.safe_set_value("riden", "set_v_set", set_v_set_initial)
        print("V_SET:", storage.safe_get_value("riden", "get_v_set"))
        print("V_OUT:", storage.safe_get_value("riden", "get_v_out"))
        print("I_OUT:", storage.safe_get_value("riden", "get_i_out"))
        print("P_OUT:", storage.safe_get_value("riden", "get_p_out"))
        # Set and get inverter power
        storage.safe_set_value("inverter", "set_power", 0)
        print("Inverter power:", storage.safe_get_value("inverter", "get_power"))
    except Exception as e:
        print(f"Error initializing Riden and inverter values: {e}")

def throttled_set_riden(param, value):
    global last_riden_set
    now = time.time()
    if now - last_riden_set < MIN_RIDEN_INTERVAL:
        time.sleep(MIN_RIDEN_INTERVAL - (now - last_riden_set))
    last_riden_set = time.time()
    return storage.safe_set_value("riden", param, value)

def PtoI(power_kwatts, voltage=set_v_set_initial, max_current=30.0):
    if voltage==0:
        voltage=set_v_set_initial
        
    current = abs( power_kwatts * 1000 / voltage)
    safe_current = round(min(current, max_current),3)
    return safe_current

def print_status_line(
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

    p1.log_store(
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



def main_loop():
    deadband=0.02  # kW
    rid_P_out=0.0
    current=0.0
    v_out=0.0
    #storage.safe_set_value("pindriver", "connect", None)
    #storage.safe_set_value("pindriver", "disconnect", None)
    initialize_values()
    while True:
        try:
            vals = get_AC_instantenious()
            import_p, export_p, L1, L2, L3 = (vals + [None]*5)[:5]

            #export_p=export_p+1.0
            if None in [import_p, export_p]:
                print(f"{RED}Invalid P1 data, retrying...{RESET}")
                time.sleep(1.0)
                continue
            #calcualte power difference
            power_diff = (import_p or 0.0) - (export_p or 0.0)
            #pid control
            pid_power = pid.adjustPower(power_diff)

            #set inverter power in watts
            inv_power=round(pid_power*1000)
            if inv_power < 0:
                    inv_power=0

            #when stable do not change power setpoints
            if -deadband <= power_diff <= deadband:
                print_status_line(import_p=import_p, export_p=export_p, power_diff=power_diff, pid_power=pid_power, L1=L1, L2=L2, L3=L3,war_power=inv_power)
                time.sleep(0.5)
                
            #set power to inverter
            if  pid_power >= 0:
                storage.safe_set_value("inverter", "set_power", inv_power)
                print_status_line(import_p=import_p, export_p=export_p, power_diff=power_diff, pid_power=pid_power, L1=L1, L2=L2, L3=L3,
                                  war_power=inv_power)
                current=0.0
                throttled_set_riden("set_i_set", current)
                #storage.safe_set_value("pindriver", "connect", None)
                storage.safe_set_value("pindriver", "disconnect", None)
            elif pid_power < 0:
                inv_power=0
                storage.safe_set_value("pindriver", "connect", None)
                storage.safe_set_value("inverter", "set_power", inv_power)
                storage.safe_set_value("riden", "set_output", True)

                v_out = storage.safe_get_value("riden", "get_v_out")
                current=PtoI(pid_power,v_out )

                #rid_P_out=storage.safe_get_value("riden", "get_p_out")/1000
                p = storage.safe_get_value("riden", "get_p_out")
                rid_P_out = p/1000 if p not in (None, "") else 0.0   

                #storage.safe_set_value("riden", "set_i_set", current)
                throttled_set_riden("set_i_set", current)
                #print(f"Setting current to: {BRIGHT_GREEN}{current:.2f}{RESET} get_V_out:  {v_out:.2f} V")
                print_status_line(import_p=import_p, export_p=export_p, power_diff=power_diff, pid_power=pid_power, L1=L1, L2=L2, L3=L3,
                       rid_P_out=rid_P_out, current=current, v_out=v_out)
                

            #log data to file
            # with open(file_name, "a") as f:
            #     f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{import_p:.3f},{export_p:.3f},{power_diff:.3f},{pid_power:.3f},{L1:.3f},{L2:.3f},{L3:.3f}\n")

            time.sleep(0.5)

        except Exception as e:
            print(f"{RED}Error in main loop: {e}{RESET}")
            # try:
            #     storage.safe_set_value("inverter", "set_power", 0)
            #     storage.safe_set_value("riden", "set_i_set", 0.0)
            # except Exception as e2:
            #     print(f"{RED}Safety mode failed: {e2}{RESET}")
            #     storage._restart_mqtt()
            time.sleep(3)  # cooldown before retry
            #continue

try:
    main_loop()
except KeyboardInterrupt:
    print("Program interrupted by user, sending safe values...")
finally:
    # SAFETY: always reset devices
    try:
        storage.safe_set_value("inverter", "set_power", 0)
        throttled_set_riden("set_i_set",  0.0)
        #storage.safe_set_value("riden", "set_i_set", 0.0)
        storage.safe_set_value("pindriver", "disconnect", None)

    except Exception as e:
        print(f"Error setting safe values: {e}")
    storage.close()