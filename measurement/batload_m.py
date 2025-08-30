import time
from riden_remote import RidenRemote
from P1uitlezen import Meter
from datetime import datetime

class BatLoader:
    def __init__(self, battery_voltage=25.2, port=None):
        self.battery_voltage = battery_voltage
        self.port = port
        self.meter = Meter(port=port) if port else Meter()

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

    def current_to_battery(self, power_diff):
        return power_diff * 1000 / self.battery_voltage

    def run(self):
        df = self.get_all_riden_to_df()
        obis_codes = ['1-0:1:.7.0', '1-0:2:.7.0']
        import_p, export_p = self.get_obis_values(df, obis_codes)
        power_diff = export_p - import_p if import_p is not None and export_p is not None else None
        print(import_p, export_p)
        if power_diff is not None:
            required_current = self.current_to_battery(power_diff)
            print(required_current)
        else:
            print("Could not calculate required current due to missing OBIS values.")

if __name__ == "__main__":
    BatLoader(battery_voltage=25.2).run()