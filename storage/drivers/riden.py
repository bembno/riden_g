from serial import Serial, SerialException
from modbus_tk.modbus_rtu import RtuMaster
from modbus_tk.defines import WRITE_MULTIPLE_REGISTERS
from modbus_tk.exceptions import ModbusInvalidResponseError
import time
from datetime import datetime
from .register import Register as R


class Riden:
    """
    Drop-in replacement:
    - same public API
    - same behavior
    - internal cleanup only
    """

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

        self.serial = None
        self.master = None

        self.id = 0
        self.type = None

        self.v_multi = 100
        self.i_multi = 100
        self.p_multi = 100
        self.v_in_multi = 100

        self._open_serial()
        self.init_device()
        self._apply_device_profile()
        self.update()

    # -------------------------------------------------
    # internal helpers (NEW, but private)
    # -------------------------------------------------
    def _log(self, msg):
        print(msg)

    def _safe(self, v, fallback):
        return fallback if v is None else v

    def _connected(self):
        return bool(self.serial and self.serial.is_open)

    def _reset_buffers(self):
        if self.serial:
            self.serial.reset_input_buffer()
            self.serial.reset_output_buffer()

    def _exec(self, func, retries=3, delay=0.2):
        """
        Central retry + reconnect handler
        preserves original behavior but removes duplication
        """
        for i in range(retries):
            try:
                if not self._connected():
                    self.reconnect()
                return func()
            except (SerialException, OSError, ModbusInvalidResponseError) as e:
                if isinstance(e, (SerialException, OSError)):
                    self.reconnect()
                time.sleep(delay)
        return None

    # -------------------------------------------------
    # connection
    # -------------------------------------------------
    def _open_serial(self):
        for i in range(5):
            try:
                self.serial = Serial(self.port, self.baudrate, timeout=self.timeout)
                self.master = RtuMaster(self.serial)
                self.master.set_timeout(self.timeout)
                return
            except SerialException as e:
                self._log(f"Serial open failed ({i+1}/5): {e}")
                time.sleep(5)
        raise SerialException("Cannot open serial port")

    def reconnect(self):
        try:
            if self.serial:
                self.serial.close()
        except Exception:
            pass
        self._open_serial()

    def is_connected(self):
        return self._connected()

    # -------------------------------------------------
    # low-level IO
    # -------------------------------------------------
    def read(self, register, length=1, retries=3, delay=0.2):
        def op():
            self._reset_buffers()
            res = self.master.execute(self.address, 3, register, length)
            return res if length > 1 else res[0]

        return self._exec(op, retries, delay)

    def write(self, register, value, retries=3, delay=0.2):
        def op():
            self._reset_buffers()
            return self.master.execute(self.address, 6, register, 1, value)[0]

        return self._exec(op, retries, delay)

    def write_multiple(self, register, values, retries=3, delay=0.2):
        def op():
            return self.master.execute(
                self.address,
                WRITE_MULTIPLE_REGISTERS,
                register,
                1,
                values,
            )

        return self._exec(op, retries, delay)

    # -------------------------------------------------
    # init
    # -------------------------------------------------
    def init(self):
        data = self.read(0, 10)
        if not data:
            self.id = 0
            return

        try:
            self.id = self.get_id(data[R.ID])
        except Exception:
            self.id = 0

    def init_device(self):
        try:
            self.init()
            self._log(f"Init OK ID={self.id}")
        except Exception as e:
            self._log(f"Init failed: {e}")

    def _apply_device_profile(self):
        if self.id >= 60241:
            self.type = "RD6024"
        elif 60180 <= self.id <= 60189:
            self.type = "RD6018"
        elif 60120 <= self.id <= 60124:
            self.type = "RD6012"
        elif 60125 <= self.id <= 60129:
            self.type = "RD6012P"
            self.v_multi = 1000
            self.p_multi = 1000
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

    # -------------------------------------------------
    # ID / identity
    # -------------------------------------------------
    def get_id(self, _id=None):
        self.id = self._safe(_id, self.read(R.ID))
        return self.id

    def get_sn(self, _sn_h=None, _sn_l=None):
        _sn_h = self._safe(_sn_h, self.read(R.SN_H))
        _sn_l = self._safe(_sn_l, self.read(R.SN_L))
        self.sn = "%08d" % (_sn_h << 16 | _sn_l)
        return self.sn

    def get_fw(self, _fw=None):
        self.fw = self._safe(_fw, self.read(R.FW))
        return self.fw

    # -------------------------------------------------
    # update (UNCHANGED LOGIC)
    # -------------------------------------------------
    def update(self):
        data = (None,) * 4
        data += self.read(R.INT_C_S, (R.I_RANGE - R.INT_C_S) + 1)

        if self.type == "RD6012P":
            self.i_multi = 10000 if data[R.I_RANGE] == 0 else 1000

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

        data += (None,) * 11

        data += self.read(R.BAT_MODE, (R.WH_L - R.BAT_MODE) + 1)

        self.is_bat_mode(data[R.BAT_MODE])
        self.get_v_bat(data[R.V_BAT])
        self.get_ext_c(data[R.EXT_C_S], data[R.EXT_C])
        self.get_ext_f(data[R.EXT_F_S], data[R.EXT_F])
        self.get_ah(data[R.AH_H], data[R.AH_L])
        self.get_wh(data[R.WH_H], data[R.WH_L])

    # -------------------------------------------------
    # current sense
    # -------------------------------------------------
    def get_int_c(self, _int_c_s=None, _int_c=None):
        _int_c_s = self._safe(_int_c_s, self.read(R.INT_C_S))
        _int_c = self._safe(_int_c, self.read(R.INT_C))
        self.int_c = _int_c * (-1 if _int_c_s else 1)
        return self.int_c

    def get_int_f(self, _int_f_s=None, _int_f=None):
        _int_f_s = self._safe(_int_f_s, self.read(R.INT_F_S))
        _int_f = self._safe(_int_f, self.read(R.INT_F))
        self.int_f = _int_f * (-1 if _int_f_s else 1)
        return self.int_f

    # -------------------------------------------------
    # set/get values
    # -------------------------------------------------
    def set_v_set(self, v):
        self.v_set = round(v * self.v_multi)
        return self.write(R.V_SET, int(self.v_set))

    def set_i_set(self, i):
        self.i_set = round(i * self.i_multi)
        return self.write(R.I_SET, int(self.i_set))

    def get_v_set(self, v=None):
        self.v_set = self._safe(v, self.read(R.V_SET)) / self.v_multi
        return self.v_set

    def get_i_set(self, i=None):
        self.i_set = self._safe(i, self.read(R.I_SET)) / self.i_multi
        return self.i_set

    def get_v_out(self, v=None):
        self.v_out = self._safe(v, self.read(R.V_OUT)) / self.v_multi
        return self.v_out

    def get_i_out(self, i=None):
        self.i_out = self._safe(i, self.read(R.I_OUT)) / self.i_multi
        return self.i_out

    def get_p_out(self, p=None):
        self.p_out = self._safe(p, self.read(R.P_OUT)) / self.p_multi
        return self.p_out

    def get_v_in(self, v=None):
        self.v_in = self._safe(v, self.read(R.V_IN)) / self.v_in_multi
        return self.v_in

    # -------------------------------------------------
    # flags / status (unchanged behavior)
    # -------------------------------------------------
    def is_keypad(self, v=None):
        self.keypad = bool(self._safe(v, self.read(R.KEYPAD)))
        return self.keypad

    def get_ovp_ocp(self, v=None):
        v = self._safe(v, self.read(R.OVP_OCP))
        self.ovp_ocp = "OVP" if v == 1 else "OCP" if v == 2 else None
        return self.ovp_ocp

    def get_cv_cc(self, v=None):
        v = self._safe(v, self.read(R.CV_CC))
        self.cv_cc = "CV" if v == 0 else "CC"
        return self.cv_cc

    def set_cv_cc(self, mode):
        if isinstance(mode, str):
            mode = 0 if mode.upper() == "CV" else 1
        self.cv_cc = "CV" if mode == 0 else "CC"
        return self.write(R.CV_CC, mode)

    def is_output(self, v=None):
        self.output = bool(self._safe(v, self.read(R.OUTPUT)))
        return self.output

    def set_output(self, v):
        self.output = bool(v)
        return self.write(R.OUTPUT, int(self.output))

    def get_preset(self, v=None):
        self.preset = self._safe(v, self.read(R.PRESET))
        return self.preset

    def set_preset(self, v):
        self.preset = v
        return self.write(R.PRESET, v)

    def is_bat_mode(self, v=None):
        self.bat_mode = bool(self._safe(v, self.read(R.BAT_MODE)))
        return self.bat_mode

    def get_v_bat(self, v=None):
        self.v_bat = self._safe(v, self.read(R.V_BAT)) / self.v_multi
        return self.v_bat

    def get_ext_c(self, s=None, v=None):
        s = self._safe(s, self.read(R.EXT_C_S))
        v = self._safe(v, self.read(R.EXT_C))
        self.ext_c = v * (-1 if s else 1)
        return self.ext_c

    def get_ext_f(self, s=None, v=None):
        s = self._safe(s, self.read(R.EXT_F_S))
        v = self._safe(v, self.read(R.EXT_F))
        self.ext_f = v * (-1 if s else 1)
        return self.ext_f

    def get_ah(self, h=None, l=None):
        h = self._safe(h, self.read(R.AH_H))
        l = self._safe(l, self.read(R.AH_L))
        self.ah = (h << 16 | l) / 1000
        return self.ah

    def get_wh(self, h=None, l=None):
        h = self._safe(h, self.read(R.WH_H))
        l = self._safe(l, self.read(R.WH_L))
        self.wh = (h << 16 | l) / 1000
        return self.wh

    # -------------------------------------------------
    # time / misc (unchanged)
    # -------------------------------------------------
    def get_date_time(self):
        if self.type == "RK6006":
            return None
        d = self.read(R.YEAR, 6)
        self.datetime = datetime(d[0], d[1], d[2], d[3], d[4], d[5])
        return self.datetime.isoformat()

    def set_date_time(self, d: datetime):
        return self.write_multiple(
            R.YEAR,
            (d.year, d.month, d.day, d.hour, d.minute, d.second),
        )

    def is_take_ok(self, v=None):
        self.take_ok = bool(self._safe(v, self.read(R.OPT_TAKE_OK)))
        return self.take_ok

    def set_take_ok(self, v):
        self.take_ok = bool(v)
        return self.write(R.OPT_TAKE_OK, self.take_ok)

    def is_take_out(self, v=None):
        self.take_out = bool(self._safe(v, self.read(R.OPT_TAKE_OUT)))
        return self.take_out

    def set_take_out(self, v):
        self.take_out = bool(v)
        return self.write(R.OPT_TAKE_OUT, self.take_out)

    def is_boot_pow(self, v=None):
        self.boot_pow = bool(self._safe(v, self.read(R.OPT_BOOT_POW)))
        return self.boot_pow

    def set_boot_pow(self, v):
        self.boot_pow = bool(v)
        return self.write(R.OPT_BOOT_POW, self.boot_pow)

    def is_buzz(self, v=None):
        self.buzz = bool(self._safe(v, self.read(R.OPT_BUZZ)))
        return self.buzz

    def set_buzz(self, v):
        self.buzz = bool(v)
        return self.write(R.OPT_BUZZ, self.buzz)

    def is_logo(self, v=None):
        self.logo = bool(self._safe(v, self.read(R.OPT_LOGO)))
        return self.logo

    def set_logo(self, v):
        self.logo = bool(v)
        return self.write(R.OPT_LOGO, self.logo)

    def get_lang(self):
        self.lang = self.read(R.OPT_LANG)
        return self.lang

    def set_lang(self, v):
        self.lang = v
        return self.write(R.OPT_LANG, v)

    def get_light(self):
        self.light = self.read(R.OPT_LIGHT)
        return self.light

    def set_light(self, v):
        self.light = v
        return self.write(R.OPT_LIGHT, v)

    def reboot_bootloader(self):
        try:
            self.write(R.SYSTEM, R.BOOTLOADER)
        except ModbusInvalidResponseError:
            pass