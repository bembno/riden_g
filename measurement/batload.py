import time
from riden_remote import RidenRemote
from P1uitlezen import Meter
from datetime import datetime

class BatLoadLogger:
    LOG_FILE = "log.txt"
    MAGENTA = "\033[35m"
    RESET = "\033[0m"

    @staticmethod
    def log_error(msg):
        with open(BatLoadLogger.LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")

    @staticmethod
    def print_magenta(msg):
        print(f"{BatLoadLogger.MAGENTA}{msg}{BatLoadLogger.RESET}")

class BatLoad:
    def __init__(self, max_voltage=14.9, max_charging_current=2.0):
        self.meter = Meter()
        self.riden = RidenRemote()
        self.last_error_log = 0
        self.missing_count = 0
        self.max_voltage = max_voltage
        self.max_charging_current = max_charging_current
        self.prev_consumptions = []  # Store previous required_current values for prediction

    def calculate_required_consumption(self, df):
        """
        Calculate the required battery current (A) for a battery with self.max_voltage to keep exported power to grid near zero.
        Uses additional P1 parameters for smarter energy management, including the sum of consumed and produced energy.
        Returns a float: current in Amperes (A) to set on the battery charger (Riden).
        """
        # Exported power (to grid, -P) in kW
        export_kw = 0.0
        for obis in ['1-0:2:.7.0', '1-0:2:.7.0:L2', '1-0:2:.7.0:L3']:
            row = df[df['OBIS'] == obis]
            try:
                export_kw += float(row.iloc[0]['Value']) if not row.empty else 0.0
            except Exception:
                pass

        # Total consumption from all phases (+P)
        consumption_kw = 0.0
        for obis in ['1-0:1:.7.0', '1-0:1:.7.0:L2', '1-0:1:.7.0:L3']:
            row = df[df['OBIS'] == obis]
            try:
                consumption_kw += float(row.iloc[0]['Value']) if not row.empty else 0.0
            except Exception:
                pass

        # Energy delivered to grid (produced) and consumed from grid (imported)
        # OBIS: 1-0:1.8.0 (imported, kWh), 1-0:2.8.0 (exported, kWh) or variants
        imported_kwh = 0.0
        exported_kwh = 0.0
        for obis in ['1-0:1:.8.1', '1-0:1:.8.2']:
            row = df[df['OBIS'] == obis]
            try:
                imported_kwh += float(row.iloc[0]['Value']) if not row.empty else 0.0
            except Exception:
                pass
        for obis in ['1-0:2:.8.1', '1-0:2:.8.2']:
            row = df[df['OBIS'] == obis]
            try:
                exported_kwh += float(row.iloc[0]['Value']) if not row.empty else 0.0
            except Exception:
                pass

        # Phase voltages (for diagnostics or advanced logic)
        voltages = {}
        for phase, obis in zip(['L1', 'L2', 'L3'], ['1-0:32:.7.0', '1-0:52:.7.0', '1-0:72:.7.0']):
            row = df[df['OBIS'] == obis]
            try:
                voltages[phase] = float(row.iloc[0]['Value']) if not row.empty else None
            except Exception:
                voltages[phase] = None

        # Phase currents (for diagnostics or advanced logic)
        currents = {}
        for phase, obis in zip(['L1', 'L2', 'L3'], ['1-0:31:.7.0', '1-0:51:.7.0', '1-0:71:.7.0']):
            row = df[df['OBIS'] == obis]
            try:
                currents[phase] = float(row.iloc[0]['Value']) if not row.empty else None
            except Exception:
                currents[phase] = None

        # Tariff indicator (could be used to prefer charging during low tariff)
        tariff = None
        tariff_row = df[df['OBIS'] == '0-0:96:.14.0']
        if not tariff_row.empty:
            try:
                tariff = int(tariff_row.iloc[0]['Value'])
            except Exception:
                tariff = None

        # Print for diagnostics
        print(f"Exported power (all phases): {export_kw:.3f} kW, Consumption (all phases): {consumption_kw:.3f} kW")
        print(f"Imported energy: {imported_kwh:.3f} kWh, Exported energy: {exported_kwh:.3f} kWh")
        print(f"Phase voltages: {voltages}, Phase currents: {currents}, Tariff: {tariff}")

        # Adjust battery charging to minimize return to grid, considering net energy
        # If exported_kwh > imported_kwh, we are net exporter, so increase load
        # If imported_kwh > exported_kwh, we are net importer, so do not charge
        net_kwh = exported_kwh - imported_kwh
        if net_kwh > 0 or export_kw > 0:
            min_voltage = min([v for v in voltages.values() if v is not None], default=self.max_voltage)
            if min_voltage < 210:  # Example threshold for low voltage
                print("Warning: Low grid voltage detected, reducing charging current.")
                voltage_v = self.max_voltage
                required_current = ((export_kw * 1000) / voltage_v) * 0.5  # Reduce by 50%
            else:
                voltage_v = self.max_voltage
                # Use both net_kwh and export_kw to determine charging current
                # If net_kwh is large, be more aggressive
                # Scale net_kwh to kW for current calculation (approximate, as interval is not known)
                net_kw = net_kwh * 0.2  # Assume 0.2h (12 min) interval for smoothing
                total_export_kw = max(export_kw, net_kw)
                required_current = (total_export_kw * 1000) / voltage_v if voltage_v > 0 else 0.0
        else:
            required_current = 0.0

        # Store for prediction
        self.prev_consumptions.append(required_current)
        if len(self.prev_consumptions) > 10:
            self.prev_consumptions.pop(0)

        # Predict next required current (simple moving average)
        if len(self.prev_consumptions) >= 3:
            predicted_next = sum(self.prev_consumptions[-3:]) / 3
            print(f"Predicted next required battery current: {predicted_next:.2f} A (moving average)")
        else:
            predicted_next = required_current

        return required_current

    def run(self):
        self.meter.connect()
        last_riden_error = None
        required_obis = [
            '1-3:0:.2.8', '0-0:1:.0.0', '0-0:96:.1.1', '1-0:1:.8.1', '1-0:1:.8.2',
            '1-0:2:.8.1', '1-0:2:.8.2', '0-0:96:.14.0', '1-0:1:.7.0', '1-0:2:.7.0',
            '0-0:96:.7.21', '0-0:96:.7.9', '1-0:99:.97.0', '1-0:32:.32.0', '1-0:52:.32.0',
            '1-0:72:.32.0', '1-0:32:.36.0', '1-0:52:.36.0', '1-0:72:.36.0', '1-0:32:.7.0',
            '1-0:52:.7.0', '1-0:72:.7.0', '1-0:31:.7.0', '1-0:51:.7.0', '1-0:71:.7.0', '1-0:21:.7.0'
        ]
        try:
            while True:
                # Actively read lines until all required OBIS codes are received
                parsed_data = []
                obis_found = set()
                while True:
                    raw = self.meter.ser.readline()
                    line = self.meter.parse_line(raw)
                    if line and line['OBIS'] not in obis_found:
                        parsed_data.append(line)
                        obis_found.add(line['OBIS'])
                    if all(obis in obis_found for obis in required_obis):
                        break
                df = self.meter.to_dataframe(parsed_data)
                # Read and print actual output voltage and current from Riden
                v_out = self.riden.send_command('get_v_out').get('result', None)
                i_out = self.riden.send_command('get_i_out').get('result', None)
                print(f"Riden actual output: {v_out} V, {i_out} A")
                error_msg = None
                value_row = df[df['OBIS'] == '1-0:2:.7.0']
                if not value_row.empty:
                    self.missing_count = 0
                    value = value_row.iloc[0]['Value']
                    unit = value_row.iloc[0]['Unit']
                    print(f"Actual exported power (to grid, -P): {value} {unit}")
                    try:
                        required_current = self.calculate_required_consumption(df)
                        required_current = required_current / 10
                        # Enforce max charging current
                        if required_current > self.max_charging_current:
                            required_current = self.max_charging_current
                        print(f"Calculated required battery current (capped): {required_current:.2f} A")
                        # Enable output before setting voltage/current
                        self.riden.set_output(True)
                        v_set_result = self.riden.set_v_set(self.max_voltage)
                        i_set_result = self.riden.send_command('set_i_set', args=[required_current])
                        # Only print errors or results if they are new or have changed
                        riden_error = None
                        if (isinstance(v_set_result, dict) and v_set_result.get("error")) or (isinstance(i_set_result, dict) and i_set_result.get("error")):
                            riden_error = f"Riden error: voltage: {v_set_result}, current: {i_set_result}"
                        if riden_error:
                            if riden_error != last_riden_error:
                                BatLoadLogger.print_magenta(riden_error)
                                last_riden_error = riden_error
                        else:
                            print(f"Set Riden voltage to {self.max_voltage}V: {v_set_result}")
                            print(f"Set Riden current to {required_current:.2f}A: {i_set_result}")
                            last_riden_error = None
                    except Exception as e:
                        error_msg = f"Could not set Riden voltage/current: {e}"
                        if error_msg != last_riden_error:
                            BatLoadLogger.print_magenta(error_msg)
                            last_riden_error = error_msg
                else:
                    # Optionally disable output if not charging
                    self.riden.set_output(False)
                    self.missing_count += 1
                    if self.missing_count >= 5:
                        error_msg = "No value for 1-0:2.7.0 found in this read for 5 consecutive times."
                        BatLoadLogger.print_magenta(error_msg)
                # Log error every 5 seconds
                if error_msg:
                    now = time.time()
                    if now - self.last_error_log > 5:
                        BatLoadLogger.log_error(error_msg)
                        self.last_error_log = now
                time.sleep(1)
        finally:
            self.meter.close()

if __name__ == "__main__":
    # Example: BatLoad(max_voltage=12.6, max_charging_current=2.0) for 3S Li-ion, BatLoad(max_voltage=16.8, max_charging_current=2.0) for 4S Li-ion, etc.
    BatLoad(max_voltage=25.2, max_charging_current=2.0).run()
