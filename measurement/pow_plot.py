import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks

# --- Load CSV ---
csv_file = "data_log.csv"  # your CSV file
df = pd.read_csv(csv_file, parse_dates=['timestamp'])

# --- Print the first few rows ---
print("Loaded data:")
print(df.head(10))  # print first 10 rows

# --- Compute error signal ---
df['error'] = df['power_diff_kW'] - df['pid_power_kW']

# --- Plot signals ---
plt.figure(figsize=(12,6))
plt.plot(df['timestamp'], df['power_diff_kW'], label='Power diff (setpoint)')
plt.plot(df['timestamp'], df['pid_power_kW'], label='PID output')
plt.plot(df['timestamp'], df['error'], label='Error', linestyle='--')
plt.xlabel('Time')
plt.ylabel('kW')
plt.title('PID Control Analysis')
plt.legend()
plt.show()

# --- Compute error signal: difference between power_diff_kW and pid_power_kW ---
df['error'] = df['power_diff_kW'] - df['pid_power_kW']

# --- Detect peaks in error to estimate oscillation ---
peaks, _ = find_peaks(df['error'])
peak_times = df['timestamp'].iloc[peaks]
peak_values = df['error'].iloc[peaks]

if len(peaks) < 2:
    print("Not enough oscillations to estimate PID parameters")
else:
    # --- Oscillation period ---
    Tu = (peak_times.iloc[1] - peak_times.iloc[0]).total_seconds()
    print(f"Estimated oscillation period Tu = {Tu:.2f} s")

    # --- Ultimate gain estimation ---
    A = (peak_values.max() - peak_values.min()) / 2
    if A == 0:
        print("Oscillation amplitude too small for Ku estimation")
    else:
        Ku = 4 / (np.pi * A)
        print(f"Estimated ultimate gain Ku = {Ku:.3f}")

        # --- Ziegler-Nichols PID suggestion ---
        suggested_kp = 0.6 * Ku
        suggested_ki = 2 * suggested_kp / Tu
        suggested_kd = suggested_kp * Tu / 8

        print("\nSuggested PID parameters for your PIDController class:")
        print(f"kp = {suggested_kp:.3f}")
        print(f"ki = {suggested_ki:.3f}")
        print(f"kd = {suggested_kd:.3f}")
