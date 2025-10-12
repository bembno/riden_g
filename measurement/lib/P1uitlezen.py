# DSMR P1 reading
# (c) 10-2012 - GJ - free to copy and paste
version = "1.0"
import sys
import serial
import pandas as pd
import re

class Meter:
    def __init__(self, port="/dev/ttyUSB0", baudrate=115200, timeout=20):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None

    def connect(self):
        self.ser = serial.Serial()
        self.ser.baudrate = self.baudrate
        self.ser.bytesize = serial.EIGHTBITS
        self.ser.parity = serial.PARITY_NONE
        self.ser.stopbits = serial.STOPBITS_ONE
        self.ser.xonxoff = 0
        self.ser.rtscts = 0
        self.ser.timeout = self.timeout
        self.ser.port = self.port
        try:
            self.ser.open()
            #print(f"Connected to {self.port}")
        except Exception as e:
            sys.exit(f"Error opening {self.port}: {e}")

    def read_lines(self, count=25):
        lines = []
        parsed_data = []
        for _ in range(count):
            try:
                raw = self.ser.readline()
            except Exception as e:
                self.close()
                sys.exit(f"Serial port {self.port} could not be read: {e}")
            line = self.parse_line(raw)
            if line:
                #print(line)
                parsed_data.append(line)
            lines.append(raw)
        return parsed_data

    def parse_line(self, raw):
        # Decode bytes to string and strip whitespace
        try:
            line = raw.decode('utf-8').strip()
        except Exception:
            line = str(raw).strip()
        # Regex to match OBIS code lines: code(value*unit)
        match = re.match(r'(?P<obis>[0-9\-:]+):?(?P<subcode>[0-9\.]*)\((?P<value>[^\)*]+)(?:\*(?P<unit>[^\)]+))?\)', line)
        if match:
            obis = match.group('obis')
            subcode = match.group('subcode')
            value = match.group('value')
            unit = match.group('unit')
            key = obis if not subcode else f"{obis}:{subcode}"
            return {'OBIS': key, 'Value': value, 'Unit': unit}
        return None

    def obis_description(self, obis_code):
        # Dictionary of OBIS code descriptions (no duplicates)
        descriptions = {
            '1-3:0:.2.8': 'DSMR version',
            '0-0:1:.0.0': 'Timestamp',
            '0-0:96:.1.1': 'Equipment identifier',
            '1-0:1:.8.1': 'Meter Reading electricity delivered to client (Tariff 1) in kWh',
            '1-0:1:.8.2': 'Meter Reading electricity delivered to client (Tariff 2) in kWh',
            '1-0:2:.8.1': 'Meter Reading electricity delivered by client (Tariff 1) in kWh',
            '1-0:2:.8.2': 'Meter Reading electricity delivered by client (Tariff 2) in kWh',
            '0-0:96:.14.0': 'Tariff indicator electricity',
            '1-0:1:.7.0': 'Actual electricity power delivered (+P) in kW',
            '1-0:2:.7.0': 'Actual electricity power received (-P) in kW',
            '0-0:96:.7.21': 'Number of power failures in any phase',
            '0-0:96:.7.9': 'Number of long power failures in any phase',
            '1-0:99:.97.0': 'Power Failure Event Log',
            '1-0:32:.32.0': 'Number of voltage sags in phase L1',
            '1-0:52:.32.0': 'Number of voltage sags in phase L2',
            '1-0:72:.32.0': 'Number of voltage sags in phase L3',
            '1-0:32:.36.0': 'Number of voltage swells in phase L1',
            '1-0:52:.36.0': 'Number of voltage swells in phase L2',
            '1-0:72:.36.0': 'Number of voltage swells in phase L3',
            '1-0:32:.7.0': 'Voltage in phase L1 (V)',
            '1-0:52:.7.0': 'Voltage in phase L2 (V)',
            '1-0:72:.7.0': 'Voltage in phase L3 (V)',
            '1-0:31:.7.0': 'Current in phase L1 (A)',
            '1-0:51:.7.0': 'Current in phase L2 (A)',
            '1-0:71:.7.0': 'Current in phase L3 (A)',
            '1-0:21:.7.0': 'Instantaneous active power L1 (+P) in kW',
            '1-0:41:.7.0': 'Instantaneous active power L2 (+P) in kW',
            '1-0:61:.7.0': 'Instantaneous active power L3 (+P) in kW',
            '1-0:22:.7.0': 'Instantaneous reactive power L1 (Q) in kVAr',
            '1-0:42:.7.0': 'Instantaneous reactive power L2 (Q) in kVAr',
            '1-0:62:.7.0': 'Instantaneous reactive power L3 (Q) in kVAr',
            '1-0:23:.7.0': 'Instantaneous apparent power L1 (S) in kVA',
            '1-0:43:.7.0': 'Instantaneous apparent power L2 (S) in kVA',
            '1-0:63:.7.0': 'Instantaneous apparent power L3 (S) in kVA',
            '1-0:1:.4.0': 'Electricity delivered to client (total) in kWh',
            '1-0:2:.4.0': 'Electricity delivered by client (total) in kWh',
            '0-1:24:.2.1': 'Gas meter reading in m³',
            '0-0:96:.13.0': 'Text message from utility',
            '0-0:96:.3.10': 'Switch position of load management device',
        }
        return descriptions.get(obis_code, '')

    def to_dataframe(self, parsed_data):
        df = pd.DataFrame(parsed_data)
        if not df.empty:
            df['Description'] = df['OBIS'].apply(lambda obis: self.obis_description(obis))
        return df


    def close(self):
        if self.ser:
            try:
                self.ser.close()
                #print(f"Serial port {self.port} closed.")
            except Exception as e:
                sys.exit(f"Oops {self.port}. Program aborted. Could not close the serial port: {e}")


def main():
    print("DSMR P1 reading", version)
    print("Control-C to stop")
    print("If needed, adjust the value of ser.port in the python script")
    meter = Meter()
    meter.connect()
    parsed_data = meter.read_lines(20)
    meter.close()
    df = meter.to_dataframe(parsed_data)
    print("\nDataFrame from P1 reading:")
    print(df)
    df_pwr = meter.power_in_out(parsed_data)
    print("\nPower and Energy DataFrame:")
    print(df_pwr)

if __name__ == "__main__":
    main()