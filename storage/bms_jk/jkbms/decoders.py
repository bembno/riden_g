"""Decoders turning raw 300-byte JK BMS frames into typed models.

Frame layouts follow syssi/esphome-jk-bms (JK02_24S / JK02_32S). Newer
firmware (SW >= 11, e.g. 19.x) reserves 32 cell slots instead of 24, which
shifts the tail fields; the layout is auto-detected per frame.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .constants import (BALANCER_STATUS, BATTERY_TYPES, CHARGE_STATUS,
                        CONTROL_BITS, ERRORS_JK02, LOGBOOK_CODES)
from .models import CellData, DeviceInfo, Logbook, LogbookEntry, Settings

# --- little-endian decode helpers ---
def u16(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8)


def i16(b: bytes, i: int) -> int:
    v = u16(b, i)
    return v - 0x10000 if v >= 0x8000 else v


def u32(b: bytes, i: int) -> int:
    return b[i] | (b[i + 1] << 8) | (b[i + 2] << 16) | (b[i + 3] << 24)


def i32(b: bytes, i: int) -> int:
    v = u32(b, i)
    return v - 0x100000000 if v >= 0x80000000 else v


def s8(b: bytes, i: int) -> int:
    v = b[i]
    return v - 0x100 if v >= 0x80 else v


def sstr(b: bytes, off: int, ln: int) -> str:
    try:
        end = b.index(0x00, off)
    except ValueError:
        end = min(off + ln, len(b))
    return b[off:min(end, off + ln)].decode("utf-8", "replace")


def error_bits(mask: int) -> List[str]:
    out = []
    for bit in range(32):
        if mask & (1 << bit):
            name = ERRORS_JK02[bit]
            if name:
                out.append(name)
    return out


def fmt_secs(v: int) -> str:
    v = int(v)
    d, v = divmod(v, 86400)
    h, v = divmod(v, 3600)
    m, s = divmod(v, 60)
    return f"{d}d {h}h {m}m {s}s"


def decode_info(info: bytes) -> DeviceInfo:
    """Decode frame 0x03 (device info)."""
    return DeviceInfo(
        model=sstr(info, 6, 16),
        hardware_version=sstr(info, 22, 8),
        software_version=sstr(info, 30, 8),
        uptime_s=u32(info, 38),
        power_on_count=u32(info, 42),
        device_name=sstr(info, 46, 16),
        device_passcode=sstr(info, 62, 16),
        manufacturing_date=("20" + sstr(info, 78, 6)) if info[78] != 0 else "",
        serial_number=sstr(info, 86, 11),
        passcode=sstr(info, 97, 5),
        user_data=sstr(info, 102, 16),
        setup_passcode=sstr(info, 118, 16),
    )


def _detect_layout(s: bytes) -> Tuple[int, int]:
    """Return (nslots, tail) for a live-cell frame.

    Detection compares the avg-cell field against the actual cell mean and
    the pack voltage field against the sum of cells, at the offsets of both
    known layouts (24-slot and 32-slot).
    """
    volts = [u16(s, 6 + i * 2) for i in range(32)]
    active_mv = [v for v in volts if 0 < v < 5000]
    total_mv = sum(active_mv)
    mean_mv = total_mv / len(active_mv) if active_mv else 0

    nslots = 24
    if active_mv and abs(u16(s, 74) - mean_mv) <= 5:
        nslots = 32
    elif active_mv and abs(u16(s, 58) - mean_mv) <= 5:
        nslots = 24

    tail = 32 if nslots == 32 else 0
    if active_mv:
        for cand in (0, 32):
            if abs(u32(s, 118 + cand) - total_mv) <= total_mv * 0.15:
                tail = cand
                break
    return nslots, tail


def decode_cell_data(s: bytes) -> CellData:
    """Decode frame 0x02 (live cell data)."""
    nslots, tail = _detect_layout(s)
    head = 16 if nslots == 32 else 0

    volts = [u16(s, 6 + i * 2) for i in range(nslots)]
    cells = [v / 1000.0 for v in volts]
    res = [u16(s, 64 + head + i * 2) for i in range(nslots)]
    res = [None if (r == 0xFFFF or c == 0) else r for r, c in zip(res, cells)]
    active = [c for c in cells if c > 0]

    if nslots == 32:
        mos_raw = i16(s, 112 + tail)
        err_mask = u32(s, 134 + tail)
    else:
        mos_raw = i16(s, 134 + tail)
        err_mask = u16(s, 136 + tail)

    def temp(off: int) -> Optional[float]:
        v = i16(s, off)
        return None if v <= -100 else v / 10.0

    v = u32(s, 118 + tail) / 1000.0
    i = i32(s, 126 + tail) / 1000.0
    bal_status = s[140 + tail]
    charge_status = s[248 + tail] if nslots == 32 else None

    extras = {}
    if nslots == 32:
        dry = s[249 + tail]
        extras = {
            "t3_C": temp(226 + tail),
            "t4_C": temp(224 + tail),
            "t5_C": temp(222 + tail),
            "dry_contact_1": bool(dry & 0x02),
            "dry_contact_2": bool(dry & 0x04),
        }

    return CellData(
        layout=f"{nslots}-slot, tail+{tail}",
        frame_counter=s[5],
        cells=[round(c, 3) for c in cells],
        cell_resistance_mOhm=res,
        cells_active=len(active),
        enabled_cells_bitmask=u32(s, 54 + head),
        high_v=round(max(active), 3) if active else 0,
        low_v=round(min(active), 3) if active else 0,
        vdiff_mV=round((max(active) - min(active)) * 1000) if active else 0,
        avg_cell_mV=u16(s, 58 + head),
        delta_cell_mV=u16(s, 60 + head),
        max_voltage_cell=s[62 + head] + 1,
        min_voltage_cell=s[63 + head] + 1,
        mos_temp_C=mos_raw / 10.0,
        t1_C=temp(130 + tail),
        t2_C=temp(132 + tail),
        wire_resistance_warning_bitmask=u32(s, 114 + tail),
        battery_voltage_V=round(v, 2),
        current_A=round(i, 2),
        power_W=round(v * i, 1),
        errors_bitmask=err_mask,
        errors=error_bits(err_mask),
        balance_current_A=i16(s, 138 + tail) / 1000.0,
        balancer_status=BALANCER_STATUS.get(bal_status, f"unknown(0x{bal_status:02x})"),
        balancing=bal_status != 0,
        soc=s[141 + tail],
        capacity_remaining_Ah=round(u32(s, 142 + tail) / 1000.0, 2),
        nominal_capacity_Ah=round(u32(s, 146 + tail) / 1000.0, 2),
        cycles=u32(s, 150 + tail),
        cycle_capacity_Ah=round(u32(s, 154 + tail) / 1000.0, 2),
        soh=s[158 + tail],
        precharge=bool(s[159 + tail]),
        user_alarm=u16(s, 160 + tail),
        total_runtime_s=u32(s, 162 + tail),
        total_runtime=fmt_secs(u32(s, 162 + tail)),
        charge_mosfet=bool(s[166 + tail]),
        discharge_mosfet=bool(s[167 + tail]),
        precharging=bool(s[168 + tail]),
        balancer_working=bool(s[169 + tail]),
        discharge_ocp_release_timer=u16(s, 170 + tail),
        discharge_scp_release_timer=u16(s, 172 + tail),
        charge_ocp_release_timer=u16(s, 174 + tail),
        charge_scp_release_timer=u16(s, 176 + tail),
        uvp_release_timer=u16(s, 178 + tail),
        ovp_release_timer=u16(s, 180 + tail),
        temp_sensor_absent_bitmask=u16(s, 182 + tail),
        heating=bool(s[183 + tail]),
        emergency_countdown_s=u16(s, 186 + tail),
        discharge_current_correction=u16(s, 188 + tail),
        charge_sensor_voltage_V=u16(s, 190 + tail) / 1000.0,
        discharge_sensor_voltage_V=u16(s, 192 + tail) / 1000.0,
        battery_voltage_correction_factor=u32(s, 194 + tail),
        battery_voltage_alt_V=u16(s, 202 + tail) / 100.0,
        heating_current_A=i16(s, 204 + tail) / 1000.0,
        charger_plugged=bool(s[213 + tail]),
        smart_sleep_countdown_s=u32(s, 238 + tail),
        pcl_module_active=bool(s[242 + tail]),
        detail_log_entry_count=u32(s, 234 + tail),
        battery_type_code=s[243 + tail] if nslots == 32 else None,
        battery_type=BATTERY_TYPES.get(s[243 + tail], "unknown") if nslots == 32 else None,
        charge_status_time=u16(s, 246 + tail) if nslots == 32 else None,
        charge_status=CHARGE_STATUS.get(charge_status, "unknown") if nslots == 32 else None,
        nslots=nslots,
        tail=tail,
        **extras,
    )


def decode_settings(s: bytes, nslots: int = 24) -> Settings:
    """Decode frame 0x01 (settings / protection thresholds)."""
    is32 = nslots == 32
    extras = {}
    if is32:
        mask = s[282] | (s[283] << 8)
        extras = {
            "device_address": s[270],
            "precharge_time_s": s[274],
            "controls_bitmask": mask,
            "controls_enabled": [name for bit, name in CONTROL_BITS.items()
                                 if mask & (1 << bit)],
            "heating_start_C": s8(s, 284),
            "heating_stop_C": s8(s, 285),
            "smart_sleep_delay_min": s[286],
            "discharge_utp_C": s8(s, 296),
            "discharge_utp_recovery_C": s8(s, 297),
        }
    return Settings(
        frame_counter=s[5],
        smart_sleep_voltage_V=u32(s, 6) / 1000.0,
        cell_uvp_V=u32(s, 10) / 1000.0,
        cell_uvp_recovery_V=u32(s, 14) / 1000.0,
        cell_ovp_V=u32(s, 18) / 1000.0,
        cell_ovp_recovery_V=u32(s, 22) / 1000.0,
        balance_trigger_delta_mV=u32(s, 26),
        soc_100_cell_V=u32(s, 30) / 1000.0,
        soc_0_cell_V=u32(s, 34) / 1000.0,
        request_charge_voltage_V=u32(s, 38) / 1000.0,
        request_float_voltage_V=u32(s, 42) / 1000.0,
        power_off_voltage_V=u32(s, 46) / 1000.0,
        max_charge_current_A=u32(s, 50) / 1000.0,
        charge_ocp_delay_s=u32(s, 54),
        charge_ocp_recovery_s=u32(s, 58),
        max_discharge_current_A=u32(s, 62) / 1000.0,
        discharge_ocp_delay_s=u32(s, 66),
        discharge_ocp_recovery_s=u32(s, 70),
        short_circuit_recovery_s=u32(s, 74),
        max_balance_current_A=u32(s, 78) / 1000.0,
        charge_otp_C=u32(s, 82) / 10.0,
        charge_otp_recovery_C=u32(s, 86) / 10.0,
        discharge_otp_C=u32(s, 90) / 10.0,
        discharge_otp_recovery_C=u32(s, 94) / 10.0,
        charge_utp_C=i32(s, 98) / 10.0,
        charge_utp_recovery_C=i32(s, 102) / 10.0,
        mos_otp_C=i32(s, 106) / 10.0,
        mos_otp_recovery_C=i32(s, 110) / 10.0,
        cell_count_setting=s[114],
        charge_switch=bool(s[118]),
        discharge_switch=bool(s[122]),
        balancer_switch=bool(s[126]),
        nominal_battery_capacity_Ah=u32(s, 130) / 1000.0,
        scp_delay_us=u32(s, 134),
        balance_start_voltage_V=u32(s, 138) / 1000.0,
        wire_resistance_mOhm=([u32(s, 142 + i * 4) for i in range(32)] if is32
                               else [u32(s, 158 + i * 4) for i in range(24)]),
        **extras,
    )


def decode_logbook(s: bytes) -> Logbook:
    """Decode frame 0x05 (event logbook)."""
    count = u32(s, 6)
    entries = []
    for i in range(min(count, 50)):
        base = 11 + i * 5
        if base + 5 > len(s):
            break
        ts = u32(s, base)
        code = s[base + 4]
        entries.append(LogbookEntry(
            time=fmt_secs(ts),
            code=code,
            event=LOGBOOK_CODES.get(code, f"Unknown (0x{code:02X})"),
        ))
    return Logbook(count=count, entries=entries)
