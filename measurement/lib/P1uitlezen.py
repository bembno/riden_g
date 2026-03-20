# DSMR P1 reading
version = "1.0"
import sys
import serial
import re
import time   # <--- Add this
import threading

class Meter:

    # Pre-compile regex for performance
    OBIS_RE = re.compile(
        r'(?P<obis>[0-9\-:]+):?(?P<subcode>[0-9\.]*)\((?P<value>[^\)*]+)(?:\*(?P<unit>[^\)]+))?\)'
    )

    def __init__(self, port="/dev/ttyUSB0", baudrate=115200, timeout=2):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        self.ser = None
        self.telegram_end = b'!'

        self._recent_parsed_data = []
        self._read_lock = threading.Lock()
        self._serial_lock = threading.Lock()  # Protects serial port access
        self._recent_p1_data = []
        self._ready = False
        self._stop_event = threading.Event()
        self._periodic_thread = None
        self._import_history = []
        # NOTE: Thread is NOT started here. Call .start() explicitly.

    def connect(self):
        with self._serial_lock:  # Protect serial initialization
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
                self._ready = False  # Reset ready flag on connection failure
                sys.exit(f"Error opening {self.port}: {e}")

    def read_telegram(self):
        """Read until end of telegram (!) or timeout"""
        lines = []
        start_time = time.time()
        
        while not self._stop_event.is_set():  # Check stop before blocking operations
            try:
                # Only acquire lock for the actual readline() call
                # serial.Serial is thread-safe for single consumer usage
                with self._serial_lock:
                    if not self.ser or not self.ser.is_open:
                        self.connect()
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
        return parsed_data  # Return empty list if no data, no fallback
    
    def parse_line(self, raw):
        try:
            line = raw.decode('utf-8').strip()
        except Exception:
            line = str(raw).strip()
        match = self.OBIS_RE.match(line)
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
    
    def get_listed_obis_values(self, parsed_data, obis_list):
        """Extract a list of numeric values for the requested OBIS codes."""
        if not parsed_data:
            return [0.0] * len(obis_list)  # always numeric

        # Create O(1) lookup map instead of O(n) search per code
        data_map = {r.get('OBIS'): r for r in parsed_data}
        
        values = []
        for obis in obis_list:
            record = data_map.get(obis)
            if record is not None:
                try:
                    values.append(float(record.get('Value', 0)))
                except Exception:
                    values.append(0.0)
            else:
                values.append(0.0)

        # Safe subtraction (import - export)
        if len(values) == 8:
            values[2] = (values[2] or 0.0) - (values[5] or 0.0)  # L1 import - export
            values[3] = (values[3] or 0.0) - (values[6] or 0.0)  # L2 import - export
            values[4] = (values[4] or 0.0) - (values[7] or 0.0)  # L3

        return values

    def get_recent_parsed(self):
        """Return the most recent parsed telegram (list of dicts)."""
        with self._read_lock:
            return list(self._recent_parsed_data) if self._recent_parsed_data else []

    def get_power(self):
        """Return the latest power meter values (thread-safe)."""

        with self._read_lock:
            if not self._recent_p1_data:
                return [0.0] * 8

            data = self._recent_p1_data.copy()

            # --- Moving average for import (configurable window) ---
            import_val = data[0]

            self._import_history.append(import_val)

            # keep only last N samples
            window = 1  #self.import_ma_window
            if len(self._import_history) > window:
                self._import_history = self._import_history[-window:]

            avg_import = sum(self._import_history) / len(self._import_history)

            data[0] = avg_import

            return data

    def periodic_read(self):
        """Background thread: reads DSMR telegram continuously."""
        while not self._stop_event.is_set():
            try:
                parsed_data = self.read_telegram()

                values = self.get_listed_obis_values(parsed_data, [
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
                    self._recent_parsed_data = parsed_data
                    self._ready = True  # Data is now available

            except Exception as e:
                print(f"Error in periodic_read: {e}")
                self._ready = False  # Reset ready flag on error
                time.sleep(1)  # Backoff before retry
                try:
                    self.connect()  # Try to reconnect
                except Exception:
                    pass  # Connection errors already logged in connect()

    def start_periodic_read(self):
        """Start the background periodic read thread."""
        if self._periodic_thread and self._periodic_thread.is_alive():
            print("Periodic read already running")
            return

        self._stop_event.clear()  # Reset stop signal
        self._periodic_thread = threading.Thread(target=self.periodic_read, daemon=True)
        self._periodic_thread.start()
        print("Periodic P1 read thread started")

    def stop_periodic_read(self):
        """Stop the background periodic read thread."""
        if not (self._periodic_thread and self._periodic_thread.is_alive()):
            print("Periodic read not running")
            return

        self._stop_event.set()  # Signal thread to stop

        if self._periodic_thread:
            self._periodic_thread.join(timeout=5.0)

            if self._periodic_thread.is_alive():
                print("Warning: periodic read thread did not stop in time")
            else:
                print("Periodic P1 read thread stopped")

    def start(self):
        """Start the meter (establish connection and begin reading thread).
        
        Explicit lifecycle control: not called automatically in __init__.
        
        Returns:
            self: For method chaining.
        """
        self.connect()  # Establish serial connection
        self.start_periodic_read()  # Start background thread
        return self

    def is_ready(self):
        """Check if the meter has successfully read data at least once.

        Returns:
            bool: True if first telegram has been received, False otherwise.
        """
        return self._ready

    def wait_until_ready(self, timeout=10):
        """Block until the meter has received at least one telegram.

        Args:
            timeout (int): Maximum seconds to wait (default 10).

        Returns:
            bool: True if ready before timeout, False if timeout exceeded.
        """
        start = time.time()
        while time.time() - start < timeout:
            if self._ready:
                return True
            time.sleep(0.05)
        return False

    def get_recentP1(self):
        """Deprecated alias for :meth:`get_power`.

        Kept for backwards compatibility.
        """
        return self.get_power()

    def close(self):
        self.stop_periodic_read() 

        # Only acquire lock for the actual serial close operation
        with self._serial_lock:
            if self.ser and self.ser.is_open:
                try:
                    self.ser.close()
                    print(f"Serial port {self.port} closed.")
                except Exception as e:
                    print(f"Could not close {self.port}: {e}")

def main():
    try:
        # Initialize meter with explicit lifecycle control
        meter = Meter().start()  # Method chaining: create and start
        
        # Wait until first telegram is received
        if not meter.wait_until_ready(timeout=5):
            print("Warning: meter did not become ready within 5 seconds")
        
        for x in range(10):  # Run for 10 seconds as a demo
            data = meter.get_power()  # Get latest data anytime (non-blocking)
            print(f"{x} {data}")
            time.sleep(1.0)  # Main loop can do other work or just wait
        
        meter.close()  # Stop thread and close serial connection

    except Exception as e:
        print(f"Error reading DSMR meter: {e}")
        return []  # fallback empty
    


if __name__ == "__main__":
    main()