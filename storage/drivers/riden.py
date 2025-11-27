from serial import Serial, SerialException
from modbus_tk.modbus_rtu import RtuMaster
from modbus_tk.defines import WRITE_MULTIPLE_REGISTERS
from modbus_tk.exceptions import ModbusInvalidResponseError
import time
from datetime import datetime
from .register import Register as R

class Riden:
    """
    Robust Riden Modbus client.
    - Keeps track of online/offline state
    - Exponential backoff on persistent failure
    - Defensive execute wrapper (handles slight differences in master.execute signatures)
    """

    def __init__(
        self,
        port="/dev/ttyUSB0",
        baudrate=115200,
        address=1,
        timeout=0.5,
        reconnect_backoff_max=60,
    ):
        self.port = port
        self.baudrate = baudrate
        self.address = address
        self.timeout = timeout

        self.serial = None
        self.master = None
        self.id = 0
        self.sn = None
        self.type = None

        # failure / backoff state
        self._fail_count = 0
        self._fail_since = None
        self.online = False
        self.reconnect_backoff_max = reconnect_backoff_max

        # multipliers (will be refined by init/update)
        self.v_multi = 100
        self.i_multi = 100
        self.p_multi = 100
        self.v_in_multi = 100

        # attempt to open and init device (blocking, with internal retries)
        self._open_serial()
        # init_device uses read(), which includes reconnect logic
        try:
            self.init_device()
        except Exception as e:
            print("Warning: init_device failed during startup:", e)

        # Final update of device params (non-fatal)
        try:
            self.update()
        except Exception:
            # update may fail if device is offline — that's OK
            pass

    # -------------------------
    # Serial open / reconnect
    # -------------------------
    def _open_serial(self):
        """Open serial port and create RtuMaster. Retries until success."""
        attempt = 0
        while True:
            attempt += 1
            try:
                print(f"Opening Riden on {self.port} @ {self.baudrate} (attempt {attempt})...")
                self.serial = Serial(self.port, self.baudrate, timeout=self.timeout)
                self.master = RtuMaster(self.serial)
                self.master.set_timeout(self.timeout)
                self._fail_count = 0
                self._fail_since = None
                self.online = True
                print("Serial connection established.")
                return
            except SerialException as e:
                self.online = False
                print(f"Riden port open failed ({e}), retrying in 5s...")
                time.sleep(5)

    def _close_serial(self):
        """Close serial and master if present."""
        try:
            if self.master:
                try:
                    # modbus_tk RtuMaster may not have close(), but closing serial is enough
                    if hasattr(self.master, "close"):
                        self.master.close()
                except Exception:
                    pass
            if self.serial:
                try:
                    self.serial.close()
                except Exception:
                    pass
        finally:
            self.master = None
            self.serial = None
            self.online = False

    def reconnect(self, aggressive=False):
        """
        Reopen serial port after error. If aggressive=True, don't wait before re-opening.
        Otherwise use exponential backoff based on failure count.
        """
        # Close existing
        try:
            self._close_serial()
        except Exception:
            pass

        # Compute backoff
        if not aggressive and self._fail_count and self._fail_count > 0:
            secs = min(self.reconnect_backoff_max, 2 ** min(self._fail_count, 10))
            print(f"Reconnect backoff: sleeping {secs}s (fail_count={self._fail_count})")
            time.sleep(secs)
        else:
            # small pause to allow device/adapter to settle
            time.sleep(0.5)

        # Try to re-open
        try:
            self._open_serial()
            # attempt to re-init device info
            try:
                self.init_device()
                self._fail_count = 0
                self._fail_since = None
                self.online = True
            except Exception as e:
                print("Warning: init_device failed after reconnect:", e)
                # still consider the transport open; further reads will detect issues
                self.online = True
        except Exception as e:
            print("Reconnect failed:", e)
            self.online = False

    def is_connected(self):
        return bool(self.serial and getattr(self.serial, "is_open", True) and self.master)

    # -------------------------
    # Defensive execute wrapper
    # -------------------------
    def _safe_execute(self, *args, **kwargs):
        """
        Call master's execute in a defensive manner.
        Some versions/signatures expect (slave, func, start, quantity) while others expect (slave, func, start, value).
        We'll try common permutations and handle ModbusInvalidResponseError / Serial exceptions.
        Returns the raw response or raises the exception for caller to handle.
        """
        if not self.master:
            raise SerialException("No master available for execute")

        # Try the raw call first (most common)
        try:
            return self.master.execute(*args, **kwargs)
        except TypeError:
            # Try common alternate signature permutations:
            try:
                # try (slave, func, start, value)
                return self.master.execute(args[0], args[1], args[2], args[3])
            except Exception:
                # last attempt: original args but drop trailing None/1 if present
                return self.master.execute(*args[:4])
        # Note: we intentionally don't swallow ModbusInvalidResponseError here;
        # caller will catch and handle retries/backoff.

    # -------------------------
    # Read / Write wrappers
    # -------------------------
    def read(self, register, length=1, retries=3, delay=0.2):
        """
        Read holding registers (function code 3).
        Returns single int if length==1 else a tuple/list of ints.
        On persistent failure returns None.
        """
        for attempt in range(1, retries + 1):
            try:
                if not self.is_connected():
                    print(" Riden serial not open, reconnecting...")
                    self.reconnect(aggressive=(attempt > 1))

                # Reset buffers only if serial object exists and appears healthy
                if self.serial:
                    try:
                        self.serial.reset_input_buffer()
                        self.serial.reset_output_buffer()
                    except Exception:
                        # some adapters may raise here — ignore and continue
                        pass

                # modbus function 3: read holding registers
                resp = self._safe_execute(self.address, 3, register, length)
                # normalize return type
                if length == 1:
                    # some libs return a tuple/list even for single reg
                    try:
                        return resp[0] if isinstance(resp, (list, tuple)) else int(resp)
                    except Exception:
                        return resp
                else:
                    return resp
            except (SerialException, OSError, ModbusInvalidResponseError) as e:
                print(f" Read failed ({attempt}/{retries}): {e}")
                # track fail count
                self._fail_count = (self._fail_count or 0) + 1
                if self._fail_since is None:
                    self._fail_since = time.time()
                # If underlying transport error, attempt reconnect immediately
                if isinstance(e, (SerialException, OSError)):
                    try:
                        self.reconnect()
                    except Exception:
                        pass
                # short delay before retry
                time.sleep(delay)

        # permanent failure after retries:
        print(f" Failed to read register {register} after {retries} retries.")
        # increase backoff severity and mark offline
        self._fail_count = (self._fail_count or 0) + 1
        self.online = False
        try:
            # close serial to avoid locking resource
            self._close_serial()
        except Exception:
            pass
        return None

    def write(self, register, value, retries=3, delay=0.2):
        """
        Write single register (function code 6).
        Returns the device response on success or None on permanent failure.
        """
        for attempt in range(1, retries + 1):
            try:
                if not self.is_connected():
                    print(" Riden serial not open, reconnecting...")
                    self.reconnect(aggressive=(attempt > 1))

                if self.serial:
                    try:
                        self.serial.reset_input_buffer()
                        self.serial.reset_output_buffer()
                    except Exception:
                        pass

                # Some modbus_tk variants accept (slave, 6, reg, value) or (slave, 6, reg, 1, value)
                try:
                    resp = self._safe_execute(self.address, 6, register, value)
                except TypeError:
                    # fallback to older signature
                    resp = self.master.execute(self.address, 6, register, 1, value)

                # if resp is list-like, return first element, otherwise return resp
                if isinstance(resp, (list, tuple)):
                    # e.g. modbus_tk may return list with written value
                    out = resp[0] if resp else None
                else:
                    out = resp
                # success -> reset failure counters
                self._fail_count = 0
                self._fail_since = None
                self.online = True
                return out
            except (SerialException, OSError, ModbusInvalidResponseError) as e:
                print(f" Write failed ({attempt}/{retries}): {e}")
                # track fail count
                self._fail_count = (self._fail_count or 0) + 1
                if self._fail_since is None:
                    self._fail_since = time.time()

                if isinstance(e, (SerialException, OSError)):
                    # force reconnect on transport errors
                    try:
                        self.reconnect()
                    except Exception:
                        pass
                time.sleep(delay)

        # permanent failure
        print(f"Failed to write register {register} after {retries} retries.")
        self.online = False
        try:
            self._close_serial()
        except Exception:
            pass
        return None

    def write_multiple(self, register: int, values: list[int] | tuple[int, ...], retries=3, delay=0.2):
        """
        Write multiple registers. Uses WRITE_MULTIPLE_REGISTERS define.
        Returns response or None on failure.
        """
        for attempt in range(1, retries + 1):
            try:
                if not self.is_connected():
                    print(" Riden serial not open, reconnecting...")
                    self.reconnect(aggressive=(attempt > 1))

                if self.serial:
                    try:
                        self.serial.reset_input_buffer()
                        self.serial.reset_output_buffer()
                    except Exception:
                        pass

                resp = self._safe_execute(self.address, WRITE_MULTIPLE_REGISTERS, register, values)
                # success
                self._fail_count = 0
                self._fail_since = None
                self.online = True
                return resp
            except (SerialException, OSError, ModbusInvalidResponseError) as e:
                print(f" Write multiple failed ({attempt}/{retries}): {e}")
                self._fail_count = (self._fail_count or 0) + 1
                if self._fail_since is None:
                    self._fail_since = time.time()
                if isinstance(e, (SerialException, OSError)):
                    try:
                        self.reconnect()
                    except Exception:
                        pass
                time.sleep(delay)

        print("Failed to write multiple registers after retries")
        self.online = False
        try:
            self._close_serial()
        except Exception:
            pass
        return None

    # -------------------------
    # Initialization / helpers
    # -------------------------
    def init(self):
        """Read initial registers to determine ID. Non-fatal if fails."""
        data = self.read(0, 10)
        if data is None:
            print("Unable to initialize device — Modbus read failed.")
            self.id = 0
            return

        try:
            self.id = self.get_id(data[R.ID])
        except Exception as e:
            print(f"Error parsing init data: {e}")
            self.id = 0

    def init_device(self):
        try:
            self.init()
            print(f"Riden init successful, ID={self.id}")
        except Exception as e:
            print(f"⚠️ Riden init_device() failed: {e}")

    def get_id(self, _id: int = None) -> int:
        self.id = _id or self.read(R.ID)
        return self.id

    def get_sn(self, _sn_h: int = None, _sn_l: int = None) -> str:
        _sn_h = _sn_h or self.read(R.SN_H)
        _sn_l = _sn_l or self.read(R.SN_L)
        self.sn = "%08d" % ((_sn_h << 16) | _sn_l)
        return self.sn

    def get_fw(self, _fw: int = None) -> int:
        self.fw = _fw or self.read(R.FW)
        return self.fw

    def update(self) -> None:
        """
        Update many registers. This method expects reads to work; if they fail it will raise/return early.
        This keeps the rest of the class safe if device is offline.
        """
        # safe reads; if any returns None, we proceed but keep defaults
        part1 = self.read(R.INT_C_S, (R.I_RANGE - R.INT_C_S) + 1)
        if part1 is None:
            part1 = (None,) * ((R.I_RANGE - R.INT_C_S) + 1)

        data = (None,) * 4 + tuple(part1)

        if self.type == "RD6012P":
            # index checks guarded — rely on returned data content
            try:
                if data[R.I_RANGE] == 0:
                    self.i_multi = 10000
                else:
                    self.i_multi = 1000
            except Exception:
                pass

        try:
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
        except Exception:
            # tolerate partial failures
            pass

        # second block
        part2 = self.read(R.BAT_MODE, (R.WH_L - R.BAT_MODE) + 1)
        if part2 is None:
            part2 = (None,) * ((R.WH_L - R.BAT_MODE) + 1)
        data += tuple(part2)

        try:
            self.is_bat_mode(data[R.BAT_MODE])
            self.get_v_bat(data[R.V_BAT])
            self.get_ext_c(data[R.EXT_C_S], data[R.EXT_C])
            self.get_ext_f(data[R.EXT_F_S], data[R.EXT_F])
            self.get_ah(data[R.AH_H], data[R.AH_L])
            self.get_wh(data[R.WH_H], data[R.WH_L])
        except Exception:
            pass

    # -------------------------
    # getters / setters (unchanged behaviour)
    # -------------------------
    def get_int_c(self, _int_c_s: int = None, _int_c: int = None) -> int:
        _int_c_s = _int_c_s or self.read(R.INT_C_S)
        _int_c = _int_c or self.read(R.INT_C)
        sign = -1 if _int_c_s else +1
        self.int_c = _int_c * sign if _int_c is not None else None
        return self.int_c

    def get_int_f(self, _int_f_s: int = None, _int_f: int = None) -> int:
        _int_f_s = _int_f_s or self.read(R.INT_F_S)
        _int_f = _int_f or self.read(R.INT_F)
        sign = -1 if _int_f_s else +1
        self.int_f = _int_f * sign if _int_f is not None else None
        return self.int_f

    def get_v_set(self, _v_set: int = None) -> float:
        _v_set = _v_set or self.read(R.V_SET)
        self.v_set = (_v_set / self.v_multi) if _v_set is not None else None
        return self.v_set

    def set_v_set(self, v_set: float) -> float:
        self.v_set = round(v_set * self.v_multi)
        return self.write(R.V_SET, int(self.v_set))

    def get_i_set(self, _i_set: int = None) -> float:
        _i_set = _i_set or self.read(R.I_SET)
        self.i_set = (_i_set / self.i_multi) if _i_set is not None else None
        return self.i_set

    def set_i_set(self, i_set: float) -> float:
        self.i_set = round(i_set * self.i_multi)
        result = self.write(R.I_SET, int(self.i_set))
        return result

    def get_v_out(self, _v_out: int = None) -> float:
        _v_out = _v_out or self.read(R.V_OUT)
        self.v_out = (_v_out / self.v_multi) if _v_out is not None else None
        return self.v_out

    def get_i_out(self, _i_out: int = None) -> float:
        _i_out = _i_out or self.read(R.I_OUT)
        self.i_out = (_i_out / self.i_multi) if _i_out is not None else None
        return self.i_out

    def get_p_out(self, _p_out: int = None) -> float:
        _p_out = _p_out or self.read(R.P_OUT)
        self.p_out = (_p_out / self.p_multi) if _p_out is not None else None
        return self.p_out

    def get_v_in(self, _v_in: int = None) -> float:
        _v_in = _v_in or self.read(R.V_IN)
        self.v_in = (_v_in / self.v_in_multi) if _v_in is not None else None
        return self.v_in

    def is_keypad(self, _keypad: int = None) -> bool:
        val = _keypad if _keypad is not None else self.read(R.KEYPAD)
        self.keypad = bool(val) if val is not None else None
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
        val = _output if _output is not None else self.read(R.OUTPUT)
        self.output = bool(val) if val is not None else None
        return self.output

    def set_output(self, output: bool) -> None:
        self.output = output
        return self.write(R.OUTPUT, int(self.output))

    def get_preset(self, _preset: int = None) -> int:
        self.preset = _preset or self.read(R.PRESET)
        return self.preset

    def set_preset(self, preset: int) -> int:
        self.preset = preset
        return self.write(R.PRESET, self.preset)

    def is_bat_mode(self, _bat_mode: int = None) -> bool:
        val = _bat_mode if _bat_mode is not None else self.read(R.BAT_MODE)
        self.bat_mode = bool(val) if val is not None else None
        return self.bat_mode

    def get_v_bat(self, _v_bat: int = None) -> float:
        _v_bat = _v_bat or self.read(R.V_BAT)
        self.v_bat = (_v_bat / self.v_multi) if _v_bat is not None else None
        return self.v_bat

    def get_ext_c(self, _ext_c_s: int = None, _ext_c: int = None) -> int:
        _ext_c_s = _ext_c_s or self.read(R.EXT_C_S)
        _ext_c = _ext_c or self.read(R.EXT_C)
        sign = -1 if _ext_c_s else +1
        self.ext_c = (_ext_c * sign) if _ext_c is not None else None
        return self.ext_c

    def get_ext_f(self, _ext_f_s: int = None, _ext_f: int = None) -> int:
        _ext_f_s = _ext_f_s or self.read(R.EXT_F_S)
        _ext_f = _ext_f or self.read(R.EXT_F)
        sign = -1 if _ext_f_s else +1
        self.ext_f = (_ext_f * sign) if _ext_f is not None else None
        return self.ext_f

    def get_ah(self, _ah_h: int = None, _ah_l: int = None) -> float:
        _ah_h = _ah_h or self.read(R.AH_H)
        _ah_l = _ah_l or self.read(R.AH_L)
        if _ah_h is None or _ah_l is None:
            self.ah = None
        else:
            self.ah = ((_ah_h << 16) | _ah_l) / 1000
        return self.ah

    def get_wh(self, _wh_h: int = None, _wh_l: int = None) -> float:
        _wh_h = _wh_h or self.read(R.WH_H)
        _wh_l = _wh_l or self.read(R.WH_L)
        if _wh_h is None or _wh_l is None:
            self.wh = None
        else:
            self.wh = ((_wh_h << 16) | _wh_l) / 1000
        return self.wh

    def get_date_time(self) -> datetime:
        if getattr(self, "type", None) == "RK6006":
            return None
        d = self.read(R.YEAR, 6)
        if not d:
            return None
        self.datetime = datetime(d[0], d[1], d[2], d[3], d[4], d[5])
        return self.datetime

    def set_date_time(self, d: datetime) -> int:
        return self.write_multiple(
            R.YEAR, (d.year, d.month, d.day, d.hour, d.minute, d.second)
        )

    def is_take_ok(self, _take_ok: int = None) -> bool:
        val = _take_ok if _take_ok is not None else self.read(R.OPT_TAKE_OK)
        self.take_ok = bool(val) if val is not None else None
        return self.take_ok

    def set_take_ok(self, take_ok: bool) -> bool:
        self.take_ok = take_ok
        return self.write(R.OPT_TAKE_OK, int(self.take_ok))

    def is_take_out(self, _take_out: int = None) -> bool:
        val = _take_out if _take_out is not None else self.read(R.OPT_TAKE_OUT)
        self.take_out = bool(val) if val is not None else None
        return self.take_out

    def set_take_out(self, take_out: bool) -> bool:
        self.take_out = take_out
        return self.write(R.OPT_TAKE_OUT, int(self.take_out))

    def is_boot_pow(self, _boot_pow: int = None) -> bool:
        val = _boot_pow if _boot_pow is not None else self.read(R.OPT_BOOT_POW)
        self.boot_pow = bool(val) if val is not None else None
        return self.boot_pow

    def set_boot_pow(self, boot_pow: bool) -> bool:
        self.boot_pow = boot_pow
        return self.write(R.OPT_BOOT_POW, int(self.boot_pow))

    def is_buzz(self, _buzz: int = None) -> bool:
        val = _buzz if _buzz is not None else self.read(R.OPT_BUZZ)
        self.buzz = bool(val) if val is not None else None
        return self.buzz

    def set_buzz(self, buzz: bool) -> bool:
        self.buzz = buzz
        return self.write(R.OPT_BUZZ, int(self.buzz))

    def is_logo(self, _logo: int = None) -> bool:
        val = _logo if _logo is not None else self.read(R.OPT_LOGO)
        self.logo = bool(val) if val is not None else None
        return self.logo

    def set_logo(self, logo: bool) -> bool:
        self.logo = logo
        return self.write(R.OPT_LOGO, int(self.logo))

    def get_lang(self) -> int:
        self.lang = self.read(R.OPT_LANG)
        return self.lang

    def set_lang(self, lang: int) -> int:
        self.lang = lang
        return self.write(R.OPT_LANG, int(lang))

    def get_light(self) -> int:
        self.light = self.read(R.OPT_LIGHT)
        return self.light

    def set_light(self, light: int) -> int:
        self.light = light
        return self.write(R.OPT_LIGHT, int(light))

    def reboot_bootloader(self) -> None:
        try:
            self.write(R.SYSTEM, R.BOOTLOADER)
        except ModbusInvalidResponseError:
            pass
