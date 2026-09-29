import re
with open('riden_inverter_server.py') as f:
    c = f.read()

old = '''                # --- Inverter: retry connection while missing ---
                with self._inverter_lock:
                    inverter_missing = self.inverter is None
                if inverter_missing:
                    print("Inverter not connected, attempting reconnect...")
                    # Try primary port, then fallback (same logic as connect_inverter)
                    temp_inverter = self._try_connect(
                        "inverter", lambda: self._init_inverter("/dev/ttyUSB1"))
                    if temp_inverter is None:
                        temp_inverter = self._try_connect(
                            "inverter", lambda: self._init_inverter("/dev/ttyUSB0"))
                    if temp_inverter is not None:
                        with self._inverter_lock:
                            self.inverter = temp_inverter
                        print("Inverter reconnected successfully.")'''

new = '''                # --- Inverter: retry connection while missing OR unresponsive ---
                with self._inverter_lock:
                    inverter_missing = self.inverter is None
                    inverter_unresponsive = False
                    if not inverter_missing:
                        try:
                            current = self.inverter.GetCurrentPower()
                            self.inverter.ModifyPower(current)
                        except Exception as e:
                            inverter_unresponsive = True
                            print(f"Inverter health probe failed: {e}")

                if inverter_missing or inverter_unresponsive:
                    if inverter_unresponsive:
                        print("Inverter unresponsive -> forcing reconnect")
                        try:
                            old_inv = self.inverter
                            if old_inv is not None:
                                old_inv.Stop()
                        except Exception:
                            pass
                        with self._inverter_lock:
                            self.inverter = None
                    
                    print("Inverter not connected, attempting reconnect...")
                    temp_inverter = self._try_connect(
                        "inverter", lambda: self._init_inverter("/dev/ttyUSB1"))
                    if temp_inverter is None:
                        temp_inverter = self._try_connect(
                            "inverter", lambda: self._init_inverter("/dev/ttyUSB0"))
                    if temp_inverter is not None:
                        with self._inverter_lock:
                            self.inverter = temp_inverter
                        print("Inverter reconnected successfully.")'''

c = c.replace(old, new)
with open('riden_inverter_server.py', 'w') as f:
    f.write(c)
print('server fixed')