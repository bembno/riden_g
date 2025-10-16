from serial import Serial, SerialException
from modbus_tk.modbus_rtu import RtuMaster
from modbus_tk.exceptions import ModbusInvalidResponseError
import time
from datetime import datetime
from .register import Register as R

class Riden:
    def __init__(
        self,
        port="/dev/ttyUSB0",
        baudrate=115200,
        address=1,
        serial=None,
        master=None,
        close_after_call=False,
        timeout=0.5,
    ):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout
        self.id = 0
        self.serial = None
        self.master = None

        self._open_serial()   # 🔹 Use helper instead of direct init
        self.init_device()
    # def __init__(
    #     self,
    #     port: str = "/dev/ttyUSB0",
    #     baudrate: int = 115200,
    #     address: int = 1,
    #     serial: Serial = None,
    #     master: RtuMaster = None,
    #     close_after_call: bool = False,
    #     timeout: float = 0.5,
    # ):
    #     self.id = 0
    #     self.address = address
    #     self.serial = serial or Serial(port, baudrate, timeout=0.3)
    #     self.master = master or RtuMaster(self.serial)

    #     # Fixes "Response length is invalid 0" error
    #     # If you experience this error, try changing your baudrate
    #     self.master.set_timeout(timeout)

    #     # Windows requires opening/closing the com port after each call
    #     # This is a workaround that will drasticly reduce performance
    #     if close_after_call:
    #         hooks.install_hook(
    #             "modbus_rtu.RtuMaster.before_send", lambda self: self._do_open()
    #         )
    #         hooks.install_hook(
    #             "modbus_rtu.RtuMaster.after_recv", lambda self: self._do_close()
    #         )

    #     self.init()

        self.v_multi = 100
        self.i_multi = 100
        self.p_multi = 100
        self.v_in_multi = 100

        if 60241 <= self.id:
            self.type = "RD6024"
        elif 60180 <= self.id <= 60189:
            self.type = "RD6018"
        elif 60120 <= self.id <= 60124:
            self.type = "RD6012"
        elif 60125 <= self.id <= 60129:
            self.type = "RD6012P"
            self.v_multi = 1000
            self.p_multi = 1000
            # i_multi is not constant!
        elif 60060 <= self.id <= 60064:
            self.type = "RD6006"
            self.i_multi = 1000
        elif self.id == 60065:
            self.type = "RD6006P"
            self.v_multi = 1000
            self.i_multi = 10000
            self.p_multi = 1000
        elif self.id == 60066:
            self.type = "RK6006"
            self.v_multi = 100
            self.i_multi = 1000
            self.p_multi = 100

        self.update()
    # --- NEW: safe serial open helper ---
    def _open_serial(self):
        """Try to (re)open serial connection."""
        while True:
            try:
                print(f"🔌 Opening Riden on {self.port} @ {self.baudrate}...")
                self.serial = Serial(self.port, self.baudrate, timeout=self.timeout)
                self.master = RtuMaster(self.serial)
                self.master.set_timeout(self.timeout)
                print("✅ Serial connection established.")
                return
            except SerialException as e:
                print(f"⚠️ Riden port open failed ({e}), retrying in 5s...")
                time.sleep(5)

    def reconnect(self):
        """Reopen serial port after error."""
        try:
            if self.serial:
                self.serial.close()
        except Exception:
            pass
        self._open_serial()
        try:
            self.init_device()
        except Exception as e:
            print(" Re-init failed after reconnect:", e)

    def is_connected(self):
        return self.serial and self.serial.is_open
    
    def read(self, register, length=1, retries=3, delay=0.2):
        for attempt in range(1, retries + 1):
            try:
                if not self.is_connected():
                    print("🔁 Riden serial not open, reconnecting...")
                    self.reconnect()

                if self.serial:
                    self.serial.reset_input_buffer()
                    self.serial.reset_output_buffer()

                response = self.master.execute(self.address, 3, register, length)
                return response if length > 1 else response[0]

            except (SerialException, OSError, ModbusInvalidResponseError) as e:
                print(f" Read failed ({attempt}/{retries}): {e}")
                if isinstance(e, (SerialException, OSError)):
                    self.reconnect()
                time.sleep(delay)

        print(f" Failed to read register {register} after {retries} retries.")
        return None           
    # def read(self, register: int, length: int = 1, retries: int = 3, delay: float = 0.2):
    #     for attempt in range(1, retries + 1):
    #         try:
    #             # Flush before sending to avoid stale bytes
    #             if self.serial:
    #                 self.serial.reset_input_buffer()
    #                 self.serial.reset_output_buffer()

    #             response = self.master.execute(
    #                 self.address, READ_HOLDING_REGISTERS, register, length
    #             )
    #             return response if length > 1 else response[0]

    #         except ModbusInvalidResponseError as e:
    #             print(f" Read failed (attempt {attempt}/{retries}): {e}")
    #             time.sleep(delay)

    #     print(f"Failed to read register {register} after {retries} retries.")
    #     return None
   
    def write(self, register, value, retries=3, delay=0.2):
        for attempt in range(1, retries + 1):
            try:
                if not self.is_connected():
                    print(" Riden serial not open, reconnecting...")
                    self.reconnect()

                if self.serial:
                    self.serial.reset_input_buffer()
                    self.serial.reset_output_buffer()

                result = self.master.execute(self.address, 6, register, 1, value)
                return result[0]
            except (SerialException, OSError, ModbusInvalidResponseError) as e:
                print(f"⚠️ Write failed ({attempt}/{retries}): {e}")
                if isinstance(e, (SerialException, OSError)):
                    self.reconnect()
                time.sleep(delay)

        print(f"Failed to write register {register} after {retries} retries.")
        return None


    # def write(self, register: int, value: int, retries: int = 3, delay: float = 0.2):
    #     for attempt in range(1, retries + 1):
    #         try:
    #             # Flush before sending
    #             if self.serial:
    #                 self.serial.reset_input_buffer()
    #                 self.serial.reset_output_buffer()

    #             return self.master.execute(
    #                 self.address, WRITE_SINGLE_REGISTER, register, 1, value
    #             )[0]

    #         except ModbusInvalidResponseError as e:
    #             print(f" Write failed (attempt {attempt}/{retries}): {e}")
    #             time.sleep(delay)

    #     print(f" Failed to write register {register} after {retries} retries.")
    #     return None


    # def write(self, register: int, value: int, retries: int = 3, delay: float = 0.2):
    #     for attempt in range(1, retries + 1):
    #         try:
    #             return self.master.execute(
    #                 self.address, WRITE_SINGLE_REGISTER, register, 1, value
    #             )[0]
    #         except ModbusInvalidResponseError as e:
    #             print(f" Write failed (attempt {attempt}/{retries}): {e}")
    #             time.sleep(delay)
    #     print(f" Failed to write register {register} after {retries} retries.")
    #     return None

    def write_multiple(self, register: int, values: tuple or list) -> tuple:
        try:
            return self.master.execute(
                self.address, WRITE_MULTIPLE_REGISTERS, register, 1, values
            )
        except ModbusInvalidResponseError:
            return self.write_multiple(register, values)
        
    def init(self):
        data = self.read(0, 10)  # example: read 10 registers starting at 0
        if data is None:
            print("Unable to initialize device — Modbus read failed.")
            self.id = 0
            
            return

        try:
            self.id = self.get_id(data[R.ID])
            #self.type = self.get_type(data[R.TYPE])
        except Exception as e:
            print(f"Error parsing init data: {e}")
            self.id = 0

    def init_device(self):
        try:
            self.init()
            print(f"Riden init successful, ID={self.id}")
        except Exception as e:
            print(f"⚠️ Riden init_device() failed: {e}")           


    # def init(self) -> None:
    #     data = self.read(R.ID, R.FW + 1)
    #     self.get_id(data[R.ID]),
    #     self.get_sn(data[R.SN_H], data[R.SN_L]),
    #     self.get_fw(data[R.FW]),

    def get_id(self, _id: int = None) -> int:
        self.id = _id or self.read(R.ID)
        return self.id

    def get_sn(self, _sn_h: int = None, _sn_l: int = None) -> str:
        _sn_h = _sn_h or self.read(R.SN_H)
        _sn_l = _sn_l or self.read(R.SN_L)
        self.sn = "%08d" % (_sn_h << 16 | _sn_l)
        return self.sn

    def get_fw(self, _fw: int = None) -> int:
        self.fw = _fw or self.read(R.FW)
        return self.fw

    def update(self) -> None:
        data = (None,) * 4  # Fix offset - Init registers
        data += self.read(R.INT_C_S, (R.I_RANGE - R.INT_C_S) + 1)
        if self.type == "RD6012P":
            if data[R.I_RANGE] == 0:
                self.i_multi = 10000
            else:
                self.i_multi = 1000
        self.get_int_c(data[R.INT_C_S], data[R.INT_C])
        self.get_int_f(data[R.INT_F_S], data[R.INT_F])
        self.get_v_set(data[R.V_SET])
        self.get_i_set(data[R.I_SET])
        self.get_v_out(data[R.V_OUT])
        self.get_i_out(data[R.I_OUT])
        self.get_p_out(data[R.P_OUT])
        self.get_v_in(data[R.V_IN])
        self.is_keypad(data[R.KEYPAD])
        self.get_ovp_ocp(data[R.OVP_OCP])
        self.get_cv_cc(data[R.CV_CC])
        self.is_output(data[R.OUTPUT])
        self.get_preset(data[R.PRESET])
        data += (None,) * 11  # Fix offset - Unused/Unknown registers
        data += self.read(R.BAT_MODE, (R.WH_L - R.BAT_MODE) + 1)
        self.is_bat_mode(data[R.BAT_MODE])
        self.get_v_bat(data[R.V_BAT])
        self.get_ext_c(data[R.EXT_C_S], data[R.EXT_C])
        self.get_ext_f(data[R.EXT_F_S], data[R.EXT_F])
        self.get_ah(data[R.AH_H], data[R.AH_L])
        self.get_wh(data[R.WH_H], data[R.WH_L])

    def get_int_c(self, _int_c_s: int = None, _int_c: int = None) -> int:
        _int_c_s = _int_c_s or self.read(R.INT_C_S)
        _int_c = _int_c or self.read(R.INT_C)
        sign = -1 if _int_c_s else +1
        self.int_c = _int_c * sign
        return self.int_c

    def get_int_f(self, _int_f_s: int = None, _int_f: int = None) -> int:
        _int_f_s = _int_f_s or self.read(R.INT_F_S)
        _int_f = _int_f or self.read(R.INT_F)
        sign = -1 if _int_f_s else +1
        self.int_f = _int_f * sign
        return self.int_f

    def get_v_set(self, _v_set: int = None) -> float:
        _v_set = _v_set or self.read(R.V_SET)
        self.v_set = _v_set / self.v_multi
        return self.v_set

    def set_v_set(self, v_set: float) -> float:
        self.v_set = round(v_set * self.v_multi)
        return self.write(R.V_SET, int(self.v_set))

    def get_i_set(self, _i_set: int = None) -> float:
        _i_set = _i_set or self.read(R.I_SET)
        self.i_set = _i_set / self.i_multi
        return self.i_set

    # def set_i_set(self, i_set: float) -> float:
    #     self.i_set = round(i_set * self.i_multi)
    #     return self.write(R.I_SET, int(self.i_set))
    
    def set_i_set(self, i_set: float) -> float:
        self.i_set = round(i_set * self.i_multi)
        print(f"[DEBUG] set_i_set({i_set}) → writing {self.i_set} raw")
        start = time.time()

        result = self.write(R.I_SET, int(self.i_set))

        duration = time.time() - start
        print(f"[DEBUG] set_i_set done in {duration:.3f}s, result={result}")
        return result


    def get_v_out(self, _v_out: int = None) -> float:
        _v_out = _v_out or self.read(R.V_OUT)
        self.v_out = _v_out / self.v_multi
        return self.v_out

    def get_i_out(self, _i_out: int = None) -> float:
        _i_out = _i_out or self.read(R.I_OUT)
        self.i_out = _i_out / self.i_multi
        return self.i_out

    def get_p_out(self, _p_out: int = None) -> float:
        _p_out = _p_out or self.read(R.P_OUT)
        self.p_out = _p_out / self.p_multi
        return self.p_out

    def get_v_in(self, _v_in: int = None) -> float:
        _v_in = _v_in or self.read(R.V_IN)
        self.v_in = _v_in / self.v_in_multi
        return self.v_in

    def is_keypad(self, _keypad: int = None) -> bool:
        self.keypad = bool(_keypad or self.read(R.KEYPAD))
        return self.keypad

    def get_ovp_ocp(self, _ovp_ocp: int = None) -> str:
        _ovp_ocp = _ovp_ocp or self.read(R.OVP_OCP)
        self.ovp_ocp = (
            "OVP" if _ovp_ocp == 1 else "OCP" if _ovp_ocp == 2 else None
        )
        return self.ovp_ocp

    def get_cv_cc(self, _cv_cc: int = None) -> str:
        _cv_cc = _cv_cc or self.read(R.CV_CC)
        self.cv_cc = "CV" if _cv_cc == 0 else "CC" if _cv_cc == 1 else None
        return self.cv_cc

    def is_output(self, _output: int = None) -> bool:
        self.output = bool(_output or self.read(R.OUTPUT))
        return self.output

    def set_output(self, output: bool) -> None:
        self.output = output
        return self.write(R.OUTPUT, int(self.output))

    def get_preset(self, _preset: int = None) -> int:
        "Always returns 0 on my device, setter works as expected"
        self.preset = _preset or self.read(R.PRESET)
        return self.preset

    def set_preset(self, preset: int) -> int:
        self.preset = preset
        return self.write(R.PRESET, self.preset)

    def is_bat_mode(self, _bat_mode: int = None) -> bool:
        self.bat_mode = bool(_bat_mode or self.read(R.BAT_MODE))
        return self.bat_mode

    def get_v_bat(self, _v_bat: int = None) -> float:
        _v_bat = _v_bat or self.read(R.V_BAT)
        self.v_bat = _v_bat / self.v_multi
        return self.v_bat

    def get_ext_c(self, _ext_c_s: int = None, _ext_c: int = None) -> int:
        _ext_c_s = _ext_c_s or self.read(R.EXT_C_S)
        _ext_c = _ext_c or self.read(R.EXT_C)
        sign = -1 if _ext_c_s else +1
        self.ext_c = _ext_c * sign
        return self.ext_c

    def get_ext_f(self, _ext_f_s: int = None, _ext_f: int = None) -> int:
        _ext_f_s = _ext_f_s or self.read(R.EXT_F_S)
        _ext_f = _ext_f or self.read(R.EXT_F)
        sign = -1 if _ext_f_s else +1
        self.ext_f = _ext_f * sign
        return self.ext_f

    def get_ah(self, _ah_h: int = None, _ah_l: int = None) -> float:
        _ah_h = _ah_h or self.read(R.AH_H)
        _ah_l = _ah_l or self.read(R.AH_L)
        self.ah = (_ah_h << 16 | _ah_l) / 1000
        return self.ah

    def get_wh(self, _wh_h: int = None, _wh_l: int = None) -> float:
        _wh_h = _wh_h or self.read(R.WH_H)
        _wh_l = _wh_l or self.read(R.WH_L)
        self.wh = (_wh_h << 16 | _wh_l) / 1000
        return self.wh

    def get_date_time(self) -> datetime:
        if self.type == "RK6006":
            return
        d = self.read(R.YEAR, 6)
        self.datetime = datetime(d[0], d[1], d[2], d[3], d[4], d[5])
        return self.datetime

    def set_date_time(self, d: datetime) -> int:
        return self.write_multiple(
            R.YEAR, (d.year, d.month, d.day, d.hour, d.minute, d.second)
        )

    def is_take_ok(self, _take_ok: int = None) -> bool:
        self.take_ok = bool(_take_ok or self.read(R.OPT_TAKE_OK))
        return self.take_ok

    def set_take_ok(self, take_ok: bool) -> bool:
        self.take_ok = take_ok
        return self.write(R.OPT_TAKE_OK, self.take_ok)

    def is_take_out(self, _take_out: int = None) -> bool:
        self.take_out = bool(_take_out or self.read(R.OPT_TAKE_OUT))
        return self.take_out

    def set_take_out(self, take_out: bool) -> bool:
        self.take_out = take_out
        return self.write(R.OPT_TAKE_OUT, self.take_out)

    def is_boot_pow(self, _boot_pow: int = None) -> bool:
        self.boot_pow = bool(_boot_pow or self.read(R.OPT_BOOT_POW))
        return self.boot_pow

    def set_boot_pow(self, boot_pow: bool) -> bool:
        self.boot_pow = boot_pow
        return self.write(R.OPT_BOOT_POW, self.boot_pow)

    def is_buzz(self, _buzz: int = None) -> bool:
        self.buzz = bool(_buzz or self.read(R.OPT_BUZZ))
        return self.buzz

    def set_buzz(self, buzz: bool) -> bool:
        self.buzz = buzz
        return self.write(R.OPT_BUZZ, self.buzz)

    def is_logo(self, _logo: int = None) -> bool:
        self.logo = bool(_logo or self.read(R.OPT_LOGO))
        return self.logo

    def set_logo(self, logo: bool) -> bool:
        self.logo = logo
        return self.write(R.OPT_LOGO, self.logo)

    def get_lang(self) -> int:
        self.lang = self.read(R.OPT_LANG)
        return self.lang

    def set_lang(self, lang: int) -> int:
        self.lang = lang
        return self.write(R.OPT_LANG, self.lang)

    def get_light(self) -> int:
        self.light = self.read(R.OPT_LIGHT)
        return self.light

    def set_light(self, light: int) -> int:
        self.light = light
        return self.write(R.OPT_LIGHT, self.light)

    def reboot_bootloader(self) -> None:
        try:
            self.write(R.SYSTEM, R.BOOTLOADER)
        except ModbusInvalidResponseError:
            pass