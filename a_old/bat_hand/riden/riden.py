
# Built-in modules
from datetime import datetime

# Third-party modules (commented out for stub)
# from modbus_tk import hooks
# from modbus_tk.defines import (
#     READ_HOLDING_REGISTERS,
#     WRITE_MULTIPLE_REGISTERS,
#     WRITE_SINGLE_REGISTER,
# )
# from modbus_tk.exceptions import ModbusInvalidResponseError
# from modbus_tk.modbus_rtu import RtuMaster
from serial import Serial

# Local modules (commented out for stub)
# from .register import Register as R

class Riden:
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200, address: int = 1, serial=None, master=None, close_after_call: bool = False, timeout: float = 0.5):
        self.address = address
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.serial = Serial(port=self.port, baudrate=self.baudrate, timeout=self.timeout)
        self.master = master
        self.close_after_call = close_after_call
        self.id = 60060
        self.type = "RD6006"
        self.v_multi = 100
        self.i_multi = 100
        self.p_multi = 100
        self.v_in_multi = 100
        self.sn = "00000000"
        self.fw = 1
        self.datetime = datetime.now()
        self.int_c = 0
        self.int_f = 0
        self.v_set = 0.0
        self.i_set = 0.0
        self.v_out = 0.0
        self.i_out = 0.0
        self.p_out = 0.0
        self.v_in = 0.0
        self.keypad = False
        self.ovp_ocp = None
        self.cv_cc = None
        self.output = False
        self.preset = 0
        self.bat_mode = False
        self.v_bat = 0.0
        self.ext_c = 0
        self.ext_f = 0
        self.ah = 0.0
        self.wh = 0.0
        self.take_ok = False
        self.take_out = False
        self.boot_pow = False
        self.buzz = False
        self.logo = False
        self.lang = 0
        self.light = 0
        #self.inverterserial = Serial(port="/dev/ttyUSB1", baudrate=4800, timeout=0.5)
    
    def set_inverter_init(self, i_set: float) -> float:
        #self.i_set = i_set
        print(f"Pawel Sendvalue set_inverter_init {i_set}")
        return i_set

    def read(self, register: int, length: int = 1):
        return 0 if length == 1 else tuple([0]*length)
    def write(self, register: int, value: int) -> int:
        return 1
    def write_multiple(self, register: int, values):
        return tuple(values)
    def init(self) -> None:
        pass
    def get_id(self, _id: int = None) -> int:
        return self.id
    def get_sn(self, _sn_h: int = None, _sn_l: int = None) -> str:
        return self.sn
    def get_fw(self, _fw: int = None) -> int:
        return self.fw
    def update(self) -> None:
        pass
    def get_int_c(self, _int_c_s: int = None, _int_c: int = None) -> int:
        return self.int_c
    def get_int_f(self, _int_f_s: int = None, _int_f: int = None) -> int:
        return self.int_f
    def get_v_set(self, _v_set: int = None) -> float:
        return self.v_set
    def set_v_set(self, v_set: float) -> float:
        self.v_set = v_set
        return self.v_set
    def get_i_set(self, _i_set: int = None) -> float:
        return self.i_set
    def set_i_set(self, i_set: float) -> float:
        self.i_set = i_set
        return self.i_set
    def get_v_out(self, _v_out: int = None) -> float:
        return self.v_out
    def get_i_out(self, _i_out: int = None) -> float:
        return self.i_out
    def get_p_out(self, _p_out: int = None) -> float:
        return self.p_out
    def get_v_in(self, _v_in: int = None) -> float:
        return self.v_in
    def is_keypad(self, _keypad: int = None) -> bool:
        return self.keypad
    def get_ovp_ocp(self, _ovp_ocp: int = None) -> str:
        return self.ovp_ocp
    def get_cv_cc(self, _cv_cc: int = None) -> str:
        return self.cv_cc
    def is_output(self, _output: int = None) -> bool:
        return self.output
    def set_output(self, output: bool) -> None:
        self.output = output
    def get_preset(self, _preset: int = None) -> int:
        return self.preset
    def set_preset(self, preset: int) -> int:
        self.preset = preset
        return self.preset
    def is_bat_mode(self, _bat_mode: int = None) -> bool:
        return self.bat_mode
    def get_v_bat(self, _v_bat: int = None) -> float:
        return self.v_bat
    def get_ext_c(self, _ext_c_s: int = None, _ext_c: int = None) -> int:
        return self.ext_c
    def get_ext_f(self, _ext_f_s: int = None, _ext_f: int = None) -> int:
        return self.ext_f
    def get_ah(self, _ah_h: int = None, _ah_l: int = None) -> float:
        return self.ah
    def get_wh(self, _wh_h: int = None, _wh_l: int = None) -> float:
        return self.wh
    def get_date_time(self) -> datetime:
        return self.datetime
    def set_date_time(self, d: datetime) -> int:
        self.datetime = d
        return 1
    def is_take_ok(self, _take_ok: int = None) -> bool:
        return self.take_ok
    def set_take_ok(self, take_ok: bool) -> bool:
        self.take_ok = take_ok
        return self.take_ok
    def is_take_out(self, _take_out: int = None) -> bool:
        return self.take_out
    def set_take_out(self, take_out: bool) -> bool:
        self.take_out = take_out
        return self.take_out
    def is_boot_pow(self, _boot_pow: int = None) -> bool:
        return self.boot_pow
    def set_boot_pow(self, boot_pow: bool) -> bool:
        self.boot_pow = boot_pow
        return self.boot_pow
    def is_buzz(self, _buzz: int = None) -> bool:
        return self.buzz
    def set_buzz(self, buzz: bool) -> bool:
        self.buzz = buzz
        return self.buzz
    def is_logo(self, _logo: int = None) -> bool:
        return self.logo
    def set_logo(self, logo: bool) -> bool:
        self.logo = logo
        return self.logo
    def get_lang(self) -> int:
        return self.lang
    def set_lang(self, lang: int) -> int:
        self.lang = lang
        return self.lang
    def get_light(self) -> int:
        return self.light
    def set_light(self, light: int) -> int:
        self.light = light
        return self.light
    def reboot_bootloader(self) -> None:
        pass
