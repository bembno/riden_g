from lib.batclant import Batclant
import time


class Onlyrid:
    """Wrapper class exposing all Riden charger functionality via MQTT remote calls."""
    
    def __init__(self, batclant: Batclant):
        """Initialize with a Batclant MQTT client."""
        self.batclant = batclant
        self.device = "riden"
        
    # ========== GETTERS ==========
    
    def get_id(self):
        """Get device ID."""
        return self.batclant.get_value(self.device, "get_id")
    
    def get_sn(self):
        """Get serial number."""
        return self.batclant.get_value(self.device, "get_sn")
    
    def get_fw(self):
        """Get firmware version."""
        return self.batclant.get_value(self.device, "get_fw")
    
    def get_v_set(self):
        """Get voltage setpoint."""
        return self.batclant.get_value(self.device, "get_v_set")
    
    def get_i_set(self):
        """Get current setpoint."""
        return self.batclant.get_value(self.device, "get_i_set")
    
    def get_v_out(self):
        """Get output voltage."""
        return self.batclant.get_value(self.device, "get_v_out")
    
    def get_i_out(self):
        """Get output current."""
        return self.batclant.get_value(self.device, "get_i_out")
    
    def get_p_out(self):
        """Get output power."""
        return self.batclant.get_value(self.device, "get_p_out")
    
    def get_v_in(self):
        """Get input voltage."""
        return self.batclant.get_value(self.device, "get_v_in")
    
    def get_int_c(self):
        """Get internal temperature (C)."""
        return self.batclant.get_value(self.device, "get_int_c")
    
    def get_int_f(self):
        """Get internal temperature (F)."""
        return self.batclant.get_value(self.device, "get_int_f")
    
    def get_ext_c(self):
        """Get external temperature (C)."""
        return self.batclant.get_value(self.device, "get_ext_c")
    
    def get_ext_f(self):
        """Get external temperature (F)."""
        return self.batclant.get_value(self.device, "get_ext_f")
    
    def get_keypad(self):
        """Get keypad state."""
        return self.batclant.get_value(self.device, "is_keypad")
    
    def get_ovp_ocp(self):
        """Get OVP/OCP state."""
        return self.batclant.get_value(self.device, "get_ovp_ocp")
    
    def get_cv_cc(self):
        """Get CV/CC mode (CV=0, CC=1)."""
        return self.batclant.get_value(self.device, "get_cv_cc")
    
    def get_output(self):
        """Get output state."""
        return self.batclant.get_value(self.device, "is_output")
    
    def get_preset(self):
        """Get preset number."""
        return self.batclant.get_value(self.device, "get_preset")
    
    def get_bat_mode(self):
        """Get battery mode."""
        return self.batclant.get_value(self.device, "is_bat_mode")
    
    def get_v_bat(self):
        """Get battery voltage."""
        return self.batclant.get_value(self.device, "get_v_bat")
    
    def get_ah(self):
        """Get amp-hours."""
        return self.batclant.get_value(self.device, "get_ah")
    
    def get_wh(self):
        """Get watt-hours."""
        return self.batclant.get_value(self.device, "get_wh")
    
    def get_date_time(self):
        """Get date/time."""
        return self.batclant.get_value(self.device, "get_date_time")
    
    def get_take_ok(self):
        """Get take OK setting."""
        return self.batclant.get_value(self.device, "is_take_ok")
    
    def get_take_out(self):
        """Get take OUT setting."""
        return self.batclant.get_value(self.device, "is_take_out")
    
    def get_boot_pow(self):
        """Get boot power setting."""
        return self.batclant.get_value(self.device, "is_boot_pow")
    
    def get_buzz(self):
        """Get buzzer setting."""
        return self.batclant.get_value(self.device, "is_buzz")
    
    def get_logo(self):
        """Get logo setting."""
        return self.batclant.get_value(self.device, "is_logo")
    
    def get_lang(self):
        """Get language setting."""
        return self.batclant.get_value(self.device, "get_lang")
    
    def get_light(self):
        """Get brightness setting."""
        return self.batclant.get_value(self.device, "get_light")
    
    # ========== SETTERS ==========
    
    def set_v_set(self, voltage: float):
        """Set voltage setpoint."""
        return self.batclant.set_value(self.device, "set_v_set", voltage)
    
    def set_i_set(self, current: float):
        """Set current setpoint."""
        return self.batclant.set_value(self.device, "set_i_set", current)
    
    def set_cv_cc(self, mode):
        """Set CV/CC mode (0/CV or 1/CC)."""
        return self.batclant.set_value(self.device, "set_cv_cc", mode)
    
    def set_output(self, state: bool):
        """Enable/disable output."""
        return self.batclant.set_value(self.device, "set_output", state)
    
    def set_preset(self, preset: int):
        """Set preset."""
        return self.batclant.set_value(self.device, "set_preset", preset)
    
    def set_date_time(self, date_time):
        """Set date/time."""
        return self.batclant.set_value(self.device, "set_date_time", date_time)
    
    def set_take_ok(self, state: bool):
        """Set take OK option."""
        return self.batclant.set_value(self.device, "set_take_ok", state)
    
    def set_take_out(self, state: bool):
        """Set take OUT option."""
        return self.batclant.set_value(self.device, "set_take_out", state)
    
    def set_boot_pow(self, state: bool):
        """Set boot power option."""
        return self.batclant.set_value(self.device, "set_boot_pow", state)
    
    def set_buzz(self, state: bool):
        """Set buzzer option."""
        return self.batclant.set_value(self.device, "set_buzz", state)
    
    def set_logo(self, state: bool):
        """Set logo option."""
        return self.batclant.set_value(self.device, "set_logo", state)
    
    def set_lang(self, lang: int):
        """Set language."""
        return self.batclant.set_value(self.device, "set_lang", lang)
    
    def set_light(self, brightness: int):
        """Set brightness."""
        return self.batclant.set_value(self.device, "set_light", brightness)
    
    # ========== ACTIONS ==========
    
    def update(self):
        """Trigger remote update of all Riden values."""
        return self.batclant.get_value(self.device, "update")
    
    def reconnect(self):
        """Trigger remote reconnect."""
        return self.batclant.get_value(self.device, "reconnect")
    
    # ========== HELPER ==========
    
    def get_full_status(self):
        """Get complete device status."""
        status = {
            "id": self.get_id(),
            "sn": self.get_sn(),
            "fw": self.get_fw(),
            "v_set": self.get_v_set(),
            "i_set": self.get_i_set(),
            "v_out": self.get_v_out(),
            "i_out": self.get_i_out(),
            "p_out": self.get_p_out(),
            "v_in": self.get_v_in(),
            "temp_int_c": self.get_int_c(),
            "temp_ext_c": self.get_ext_c(),
            "cv_cc": self.get_cv_cc(),
            "output": self.get_output(),
            "ovp_ocp": self.get_ovp_ocp(),
            "ah": self.get_ah(),
            "wh": self.get_wh(),
            "bat_mode": self.get_bat_mode(),
            "v_bat": self.get_v_bat(),
        }
        return status


if __name__ == "__main__":
    # Test suite - uncomment to run tests
    print("🧪 Onlyrid Test Suite\n")
    
    try:
        # Initialize Batclant MQTT client
        print("📡 Initializing MQTT client...")
        batclant = Batclant()
        
        # Create Riden wrapper
        riden = Onlyrid(batclant)
        
        # Test all getter functions
        print("\n📊 Testing Getters:")
        print(f"  ID:              {riden.get_id()}")
        print(f"  Serial Number:   {riden.get_sn()}")
        print(f"  Firmware:        {riden.get_fw()}")
        print(f"  V Set:           {riden.get_v_set()} V")
        print(f"  I Set:           {riden.get_i_set()} A")
        print(f"  V Out:           {riden.get_v_out()} V")
        print(f"  I Out:           {riden.get_i_out()} A")
        print(f"  P Out:           {riden.get_p_out()} W")
        print(f"  V In:            {riden.get_v_in()} V")
        print(f"  Temp Int:        {riden.get_int_c()} °C")
        print(f"  Temp Ext:        {riden.get_ext_c()} °C")
        print(f"  Keypad:          {riden.get_keypad()}")
        print(f"  OVP/OCP:         {riden.get_ovp_ocp()}")
        print(f"  CV/CC:           {riden.get_cv_cc()}")
        print(f"  Output:          {riden.get_output()}")
        print(f"  Preset:          {riden.get_preset()}")
        print(f"  Bat Mode:        {riden.get_bat_mode()}")
        print(f"  V Bat:           {riden.get_v_bat()} V")
        print(f"  Ah:              {riden.get_ah()} Ah")
        print(f"  Wh:              {riden.get_wh()} Wh")
        print(f"  Date/Time:       {riden.get_date_time()}")
        print(f"  Take OK:         {riden.get_take_ok()}")
        print(f"  Take OUT:        {riden.get_take_out()}")
        print(f"  Boot Pow:        {riden.get_boot_pow()}")
        print(f"  Buzz:            {riden.get_buzz()}")
        print(f"  Logo:            {riden.get_logo()}")
        print(f"  Lang:            {riden.get_lang()}")
        print(f"  Light:           {riden.get_light()}")
        
        # Test setter functions (CAREFUL - changes device state!)
        print("\n⚙️  Testing Setters (non-destructive):")
        print(f"  Set V_set 50.0V: {riden.set_v_set(50.0)}")
        time.sleep(0.5)
        print(f"  Set I_set 5.0A:  {riden.set_i_set(5.0)}")
        time.sleep(0.5)
        print(f"  Set CV mode:     {riden.set_cv_cc('CV')}")
        time.sleep(0.5)
        
        # Test full status
        print("\n📋 Full Status:")
        status = riden.get_full_status()
        for key, value in status.items():
            print(f"  {key:20}: {value}")
        
        # Test actions
        print("\n🔄 Testing Actions:")
        print(f"  Update:          {riden.update()}")
        
        print("\n✅ All tests completed!")
        
    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

