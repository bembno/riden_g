# DSMR P1 reading
# (c) 10-2012 - GJ - free to copy and paste
version = "1.0"
import sys
import serial
import pandas as pd
import re
import time   # <--- Add this
import threading
from queue import Queue, Empty

class Meter:

    def __init__(self, port="/dev/ttyUSB0", baudrate=115200, timeout=2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        self.last_good_data = []
        self.telegram_end = b'!'  # DSMR telegram ends with '!'

        # Caching helper (avoid reading more than once per second)
        self._last_read_time = 0.0
        self._last_df = pd.DataFrame()

        # Thread-safe periodic read variables
        self._read_lock = threading.Lock()  # Protects shared data access
        self._recent_p1_data = []  # Shared storage for most recent AC values
        self._periodic_read_running = False  # Control flag for periodic reading thread
        self._periodic_thread = None  # Reference to the periodic read thread

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
    
    def get_all_P1_to_df(self):
        try:
            now = time.time()
            if now - self._last_read_time < 1:  # DSMR sends once per second
                return self._last_df     # reuse last telegram

            self._last_read_time = now
            self.connect()  # connect once
            parsed_data = self.read_telegram()  # read full telegram
            df = self.to_dataframe(parsed_data)
            #print (df)
            self._last_df = df
            return df
        except Exception as e:
            print(f"Error reading DSMR meter: {e}")
            self._last_df = pd.DataFrame()  # fallback empty
            return self._last_df

    def get_listed_obis_values(self, df, obis_list):
        if df is None or df.empty or "OBIS" not in df.columns:
            return [0.0] * len(obis_list)  # always numeric

        values = []
        for obis in obis_list:
            row = df[df['OBIS'] == obis]
            if not row.empty:
                try:
                    val = float(row.iloc[0]['Value'])
                    values.append(val)
                except Exception:
                    values.append(0.0)
            else:
                values.append(0.0)

        # Safe subtraction
        if len(values) == 8:
            values[2] = (values[2] or 0.0) - (values[5] or 0.0)  # L1 import - export
            values[3] = (values[3] or 0.0) - (values[6] or 0.0)  # L2 import - export
            values[4] = (values[4] or 0.0) - (values[7] or 0.0)  # L3

        return values

    def get_AC_instantenious(self, obis_codes=None):
    
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
        df = self.get_all_P1_to_df()
        AC_values = self.get_listed_obis_values(df, obis_codes)

        return AC_values

    def periodic_read(self):
        """Background thread: reads DSMR telegram continuously."""
        while self._periodic_read_running:
            try:
                parsed_data = self.read_telegram()
                df = self.to_dataframe(parsed_data)

                values = self.get_listed_obis_values(df, [
                    '1-0:1:.7.0',
                    '1-0:2:.7.0',
                    '1-0:21:.7.0',
                    '1-0:41:.7.0',
                    '1-0:61:.7.0',
                    '1-0:22:.7.0',
                    '1-0:42:.7.0',
                    '1-0:62:.7.0'
                ])

                with self._read_lock:
                    self._recent_p1_data = values

            except Exception as e:
                print(f"Error in periodic_read: {e}")

    def start_periodic_read(self):
        """Start the background periodic read thread."""
        if self._periodic_read_running:
            print("Periodic read already running")
            return

        self._periodic_read_running = True
        self._periodic_thread = threading.Thread(target=self.periodic_read, daemon=True)
        self._periodic_thread.start()
        print("Periodic P1 read thread started")

    def stop_periodic_read(self):
        """Stop the background periodic read thread."""
        if not self._periodic_read_running:
            print("Periodic read not running")
            return

        self._periodic_read_running = False

        if self._periodic_thread:
            self._periodic_thread.join(timeout=5.0)

            if self._periodic_thread.is_alive():
                print("Warning: periodic read thread did not stop in time")
            else:
                print("Periodic P1 read thread stopped")

    def get_recentP1(self):
        """
        Return the most recent P1 data in a thread-safe way.

        Returns:
            list[float]: Values in the same format as get_AC_instantenious():
                        [import, export, L1, L2, L3, -L1, -L2, -L3]
                        If no data is available yet, returns a list of zeros.
        """
        with self._read_lock:
            if self._recent_p1_data is None:
                return [0.0] * 8

            return self._recent_p1_data.copy()
    
    def close(self):
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
                print(f"Serial port {self.port} closed.")
            except Exception as e:
                print(f"Could not close {self.port}: {e}")

def main():
    try:
        meter = Meter()
        meter.start_periodic_read()  # Start background thread
        for x in range(10):  # Run for 10 seconds as a demo
        
            data = meter.get_recentP1()  # Get latest data anytime (non-blocking)
            print(x,data)
            time.sleep(1.0)  # Main loop can do other work or just wait
        meter.stop_periodic_read()   # Stop when done
        


    except Exception as e:
        print(f"Error reading DSMR meter: {e}")
        return pd.DataFrame()  # fallback empty
    


if __name__ == "__main__":
    main()