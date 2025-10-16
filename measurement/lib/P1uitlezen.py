# DSMR P1 reading
# (c) 10-2012 - GJ - free to copy and paste
version = "1.0"
import sys
import serial
import pandas as pd
import re
import time   # <--- Add this
from queue import Queue, Empty

class Meter:

    def __init__(self, port="/dev/ttyUSB0", baudrate=115200, timeout=2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.last_good_data = []
        self.telegram_end = b'!'  # DSMR telegram ends with '!'

    def connect(self):
        if self.ser and self.ser.is_open:
            return
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=self.timeout,
                xonxoff=0,
                rtscts=0
            )
            print(f"Connected to DSMR P1 meter on {self.port}")
        except Exception as e:
            sys.exit(f"Error opening {self.port}: {e}")

    def read_telegram(self):
        """Read until end of telegram (!) or timeout"""
        if not self.ser or not self.ser.is_open:
            self.connect()
        lines = []
        start_time = time.time()
        while True:
            try:
                raw = self.ser.readline()
                if not raw:
                    if time.time() - start_time > self.timeout:
                        break
                    continue
                lines.append(raw)
                if self.telegram_end in raw:
                    break
            except Exception as e:
                print(f"Serial read error: {e}")
                break

        parsed_data = [line for line in (self.parse_line(r) for r in lines) if line]
        if parsed_data:
            self.last_good_data = parsed_data
        return parsed_data or self.last_good_data  # fallback if read fails
    
    def parse_line(self, raw):
        try:
            line = raw.decode('utf-8').strip()
        except Exception:
            line = str(raw).strip()
        match = re.match(
            r'(?P<obis>[0-9\-:]+):?(?P<subcode>[0-9\.]*)\((?P<value>[^\)*]+)(?:\*(?P<unit>[^\)]+))?\)', line
        )
        if match:
            obis = match.group('obis')
            subcode = match.group('subcode')
            value = match.group('value')
            unit = match.group('unit')
            key = obis if not subcode else f"{obis}:{subcode}"

             # Special case: gas meter may include timestamp, extract numeric part
            if obis.startswith('0-1:24:2.1'):
                # extract last numeric value (m³) from the whole line
                numbers = re.findall(r'\d+\.\d+', line)
                if numbers:
                    value = numbers[-1]  # last number is actual gas reading
                    unit = 'm3'

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
                        '0-1:24:.1.0': 'Gas meter equipment identifier (serial number)',
                        '0-1:96:.1.0': 'Gas DSMR version / profile identifier',
                        '0-1:24:.2.1': 'Gas meter reading in m³',
                        '0-0:96:.13.0': 'Text message from utility',
                        '0-0:96:.3.10': 'Switch position of load management device',
                    }
        return descriptions.get(obis_code, '')
    
    def to_dataframe(self, parsed_data):
        df = pd.DataFrame(parsed_data)
        if not df.empty:
            df['Description'] = df['OBIS'].apply(self.obis_description)
        return df
    
    def close(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                print(f"Serial port {self.port} closed.")
            except Exception as e:
                print(f"Could not close {self.port}: {e}")

def main():
    print("DSMR P1 reading", version)
    print("Control-C to stop")
    print("If needed, adjust the value of ser.port in the python script")
    meter = Meter()

    try:
        meter.connect()  # connect once
        parsed_data = meter.read_telegram()  # read full telegram
        df = meter.to_dataframe(parsed_data)
        print("\nDataFrame from P1 reading:")
        print(df)

        #return df
    except Exception as e:
        print(f"Error reading DSMR meter: {e}")
        return pd.DataFrame()  # fallback empty
    


if __name__ == "__main__":
    main()