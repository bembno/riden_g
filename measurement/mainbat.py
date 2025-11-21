import asyncio
from lib.P1uitlezen import Meter
from lib.batclant import Batclant
from lib.PIDController import PIDController
import os
import csv
import pandas as pd
import time

# --- Colors ---
BRIGHT_PINK = "\033[95m"; RESET = "\033[0m"; BLACK = "\033[30m"; RED = "\033[31m"
GREEN = "\033[32m"; YELLOW = "\033[33m"; BLUE = "\033[34m"; MAGENTA = "\033[35m"; CYAN = "\033[36m"
BRIGHT_RED = "\033[91m"; BRIGHT_GREEN = "\033[92m"; BRIGHT_YELLOW = "\033[93m"; BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"; BRIGHT_CYAN = "\033[96m"; BRIGHT_WHITE = "\033[97m"

file_name = "/home/pi/Desktop/prog/riden/data_log.csv"
set_v_set_initial = 57.0

kp = 0.5; ki = 0.09; kd = 0.01
setpoint = 0.0

meter = Meter()
storage = Batclant()
pid = PIDController(kp=kp, ki=ki, kd=kd, setpoint=setpoint)

last_riden_set = 0
MIN_RIDEN_INTERVAL = 0.15  # 150ms
last_p1 = 0
last_df = pd.DataFrame()

# --- Ensure CSV headers ---
if not os.path.exists(file_name):
    with open(file_name, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp", "import_kW", "export_kW", "power_diff_kW",
            "pid_power_kW", "L1_kW", "L2_kW", "L3_kW"
        ])

# --- Async helper functions ---
async def async_sleep(seconds):
    await asyncio.sleep(seconds)

async def get_all_riden_to_df():
    global last_p1, last_df
    try:
        now = time.time()
        if now - last_p1 < 1:  # DSMR sends once per second
            return last_df
        last_p1 = now
        meter.connect()
        parsed_data = meter.read_telegram()
        df = meter.to_dataframe(parsed_data)
        last_df = df
        return df
    except Exception as e:
        print(f"Error reading DSMR meter: {e}")
        last_df = pd.DataFrame()
        return last_df

def get_listed_obis_values(df, obis_list):
    if df is None or df.empty or "OBIS" not in df.columns:
        return [None] * len(obis_list)
    values = []
    for obis in obis_list:
        row = df[df['OBIS'] == obis]
        if not row.empty:
            try: values.append(float(row.iloc[0]['Value']))
            except Exception: values.append(None)
        else: values.append(None)
    return values

async def get_AC_instantenious(obis_codes=None):
    if obis_codes is None:
        obis_codes = [
            '1-0:1:.7.0', '1-0:2:.7.0', '1-0:21:.7.0', '1-0:41:.7.0', '1-0:61:.7.0'
        ]
    df = await get_all_riden_to_df()
    return get_listed_obis_values(df, obis_codes)

async def set_riden_out(output_ON=True):
    storage.safe_set_value("riden", "set_output", output_ON)
    await async_sleep(0.1)
    status_on = storage.safe_get_value("riden", "is_output")
    print("Output start status:", status_on)

async def initialize_values():
    try:
        storage.safe_set_value("pindriver", "connect", None)
        await set_riden_out(True)
        storage.safe_set_value("riden", "set_v_set", set_v_set_initial)
        print("V_SET:", storage.safe_get_value("riden", "get_v_set"))
        print("V_OUT:", storage.safe_get_value("riden", "get_v_out"))
        print("I_OUT:", storage.safe_get_value("riden", "get_i_out"))
        print("P_OUT:", storage.safe_get_value("riden", "get_p_out"))
        storage.safe_set_value("inverter", "set_power", 0)
        print("Inverter power:", storage.safe_get_value("inverter", "get_power"))
    except Exception as e:
        print(f"Error initializing Riden and inverter values: {e}")

async def throttled_set_riden(param, value):
    global last_riden_set
    now = time.time()
    if now - last_riden_set < MIN_RIDEN_INTERVAL:
        await async_sleep(MIN_RIDEN_INTERVAL - (now - last_riden_set))
    last_riden_set = time.time()
    return storage.safe_set_value("riden", param, value)

def PtoI(power_kwatts, voltage=set_v_set_initial, max_current=30.0):
    if voltage == 0: voltage = set_v_set_initial
    current = abs(power_kwatts * 1000 / voltage)
    return round(min(current, max_current), 3)

def print_status_line(import_p=0.0, export_p=0.0, power_diff=0.0, pid_power=0.0,
                      L1=0.0, L2=0.0, L3=0.0, war_power=0.0, rid_P_out=0.0,
                      current=0.0, v_out=0.0):
    parts = [f"t:{time.strftime('%H:%M:%S')}"]

    def add(label, value, color=RESET, fmt="{:.3f}"):
        if value != 0.0 and value is not None:
            parts.append(f"{label}:{color}{fmt.format(value)}{RESET}")

    # Colors
    export_color = BRIGHT_MAGENTA if export_p > 0.01 else RESET
    diff_color   = MAGENTA if power_diff > 0.01 else BRIGHT_CYAN if power_diff < -0.01 else RESET
    inv_color    = YELLOW if war_power > 0.01 else RESET
    rid_color    = BRIGHT_GREEN if rid_P_out > 0.01 else RESET
    curr_color   = BRIGHT_GREEN if current > 0.01 else RESET

    add("i", import_p, BLUE)
    add("e", export_p, export_color)
    add("di", power_diff, diff_color)
    add("pid", pid_power, CYAN)
    add("L1", L1); add("L2", L2); add("L3", L3)
    if war_power: parts.append(f"inv:{inv_color}{int(war_power)}{RESET}")
    add("rid", rid_P_out, rid_color); add("I", current, curr_color, "{:.1f}"); add("V", v_out, fmt="{:.1f}")
    print(" ".join(parts))

# --- Async main loop ---
async def main_loop():
    deadband = 0.02
    rid_P_out = current = v_out = 0.0
    await initialize_values()

    while True:
        try:
            vals = await get_AC_instantenious()
            import_p, export_p, L1, L2, L3 = (vals + [None]*5)[:5]

            if None in [import_p, export_p]:
                print(f"{RED}Invalid P1 data, retrying...{RESET}")
                await async_sleep(1.0)
                continue

            power_diff = (import_p or 0.0) - (export_p or 0.0)
            pid_power = pid.adjustPower(power_diff)
            inv_power = max(round(pid_power*1000), 0)

            if -deadband <= power_diff <= deadband:
                print_status_line(import_p=import_p, export_p=export_p, power_diff=power_diff,
                                  pid_power=pid_power, L1=L1, L2=L2, L3=L3, war_power=inv_power)
                await async_sleep(0.5)

            if pid_power >= 0:
                storage.safe_set_value("inverter", "set_power", inv_power)
                await throttled_set_riden("set_i_set", 0.0)
                storage.safe_set_value("pindriver", "disconnect", None)
                print_status_line(import_p=import_p, export_p=export_p, power_diff=power_diff,
                                  pid_power=pid_power, L1=L1, L2=L2, L3=L3, war_power=inv_power)
            else:
                inv_power = 0
                storage.safe_set_value("pindriver", "connect", None)
                storage.safe_set_value("inverter", "set_power", inv_power)
                storage.safe_set_value("riden", "set_output", True)
                v_out = storage.safe_get_value("riden", "get_v_out")
                current = PtoI(pid_power, v_out)
                p = storage.safe_get_value("riden", "get_p_out")
                rid_P_out = p/1000 if p not in (None, "") else 0.0
                await throttled_set_riden("set_i_set", current)
                print_status_line(import_p=import_p, export_p=export_p, power_diff=power_diff,
                                  pid_power=pid_power, L1=L1, L2=L2, L3=L3,
                                  rid_P_out=rid_P_out, current=current, v_out=v_out)

            await async_sleep(0.5)

        except Exception as e:
            print(f"{RED}Error in main loop: {e}{RESET}")
            await async_sleep(3.0)

# --- Run async loop ---
async def main():
    try:
        await main_loop()
    except KeyboardInterrupt:
        print("Program interrupted by user, sending safe values...")
    finally:
        try:
            storage.safe_set_value("inverter", "set_power", 0)
            await throttled_set_riden("set_i_set", 0.0)
            storage.safe_set_value("pindriver", "disconnect", None)
        except Exception as e:
            print(f"Error setting safe values: {e}")
        storage.close()

if __name__ == "__main__":
    asyncio.run(main())
