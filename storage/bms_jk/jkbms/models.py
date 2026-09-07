"""Typed result models for decoded JK BMS frames."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Optional


class _Absent:
    """Sentinel for fields that do not apply to the detected frame layout."""

    def __repr__(self) -> str:
        return "<absent>"


ABSENT = _Absent()


def _export_value(value: Any) -> Any:
    if isinstance(value, _Model):
        return value.to_dict()
    if isinstance(value, list):
        return [_export_value(item) for item in value]
    return value


class _Model:
    """Mixin providing JSON-friendly dict export.

    Fields flagged ``metadata={"internal": True}`` and fields holding the
    ABSENT sentinel are omitted, mirroring the layout-dependent keys of the
    original plain-dict decoders.
    """

    def to_dict(self) -> dict:
        out = {}
        for f in fields(self):  # type: ignore[arg-type]
            if f.metadata.get("internal"):
                continue
            value = getattr(self, f.name)
            if value is ABSENT:
                continue
            out[f.name] = _export_value(value)
        return out


@dataclass
class DeviceInfo(_Model):
    model: str
    hardware_version: str
    software_version: str
    uptime_s: int
    power_on_count: int
    device_name: str
    device_passcode: str
    manufacturing_date: str
    serial_number: str
    passcode: str
    user_data: str
    setup_passcode: str


@dataclass
class CellData(_Model):
    layout: str
    frame_counter: int
    cells: List[float]
    cell_resistance_mOhm: List[Optional[int]]
    cells_active: int
    enabled_cells_bitmask: int
    high_v: float
    low_v: float
    vdiff_mV: int
    avg_cell_mV: int
    delta_cell_mV: int
    max_voltage_cell: int
    min_voltage_cell: int
    mos_temp_C: float
    t1_C: Optional[float]
    t2_C: Optional[float]
    wire_resistance_warning_bitmask: int
    battery_voltage_V: float
    current_A: float
    power_W: float
    errors_bitmask: int
    errors: List[str]
    balance_current_A: float
    balancer_status: str
    balancing: bool
    soc: int
    capacity_remaining_Ah: float
    nominal_capacity_Ah: float
    cycles: int
    cycle_capacity_Ah: float
    soh: int
    precharge: bool
    user_alarm: int
    total_runtime_s: int
    total_runtime: str
    charge_mosfet: bool
    discharge_mosfet: bool
    precharging: bool
    balancer_working: bool
    discharge_ocp_release_timer: int
    discharge_scp_release_timer: int
    charge_ocp_release_timer: int
    charge_scp_release_timer: int
    uvp_release_timer: int
    ovp_release_timer: int
    temp_sensor_absent_bitmask: int
    heating: bool
    emergency_countdown_s: int
    discharge_current_correction: int
    charge_sensor_voltage_V: float
    discharge_sensor_voltage_V: float
    battery_voltage_correction_factor: int
    battery_voltage_alt_V: float
    heating_current_A: float
    charger_plugged: bool
    smart_sleep_countdown_s: int
    pcl_module_active: bool
    detail_log_entry_count: int
    battery_type_code: Optional[int] = None
    battery_type: Optional[str] = None
    charge_status_time: Optional[int] = None
    charge_status: Optional[str] = None
    t3_C: Any = ABSENT
    t4_C: Any = ABSENT
    t5_C: Any = ABSENT
    dry_contact_1: Any = ABSENT
    dry_contact_2: Any = ABSENT
    nslots: int = field(default=24, metadata={"internal": True})
    tail: int = field(default=0, metadata={"internal": True})


@dataclass
class Settings(_Model):
    frame_counter: int
    smart_sleep_voltage_V: float
    cell_uvp_V: float
    cell_uvp_recovery_V: float
    cell_ovp_V: float
    cell_ovp_recovery_V: float
    balance_trigger_delta_mV: int
    soc_100_cell_V: float
    soc_0_cell_V: float
    request_charge_voltage_V: float
    request_float_voltage_V: float
    power_off_voltage_V: float
    max_charge_current_A: float
    charge_ocp_delay_s: int
    charge_ocp_recovery_s: int
    max_discharge_current_A: float
    discharge_ocp_delay_s: int
    discharge_ocp_recovery_s: int
    short_circuit_recovery_s: int
    max_balance_current_A: float
    charge_otp_C: float
    charge_otp_recovery_C: float
    discharge_otp_C: float
    discharge_otp_recovery_C: float
    charge_utp_C: float
    charge_utp_recovery_C: float
    mos_otp_C: float
    mos_otp_recovery_C: float
    cell_count_setting: int
    charge_switch: bool
    discharge_switch: bool
    balancer_switch: bool
    nominal_battery_capacity_Ah: float
    scp_delay_us: int
    balance_start_voltage_V: float
    wire_resistance_mOhm: List[int]
    device_address: Any = ABSENT
    precharge_time_s: Any = ABSENT
    controls_bitmask: Any = ABSENT
    controls_enabled: Any = ABSENT
    heating_start_C: Any = ABSENT
    heating_stop_C: Any = ABSENT
    smart_sleep_delay_min: Any = ABSENT
    discharge_utp_C: Any = ABSENT
    discharge_utp_recovery_C: Any = ABSENT


@dataclass
class LogbookEntry(_Model):
    time: str
    code: int
    event: str


@dataclass
class Logbook(_Model):
    count: int
    entries: List[LogbookEntry]


@dataclass
class JkReadings(_Model):
    """Aggregate of everything decoded from one read cycle.

    ``timestamp`` and ``raw_frames`` are runtime metadata (not exported
    by ``to_dict()``): the ISO-8601 UTC capture time, and the raw frames
    dict for advanced consumers.
    """

    info: Optional[DeviceInfo] = None
    cell: Optional[CellData] = None
    settings: Optional[Settings] = None
    logbook: Optional[Logbook] = None
    timestamp: Optional[str] = field(default=None, metadata={"internal": True})
    raw_frames: Optional[Dict[int, bytes]] = field(default=None,
                                                  metadata={"internal": True})

    def to_dict(self) -> dict:
        out = {}
        for f in fields(self):
            if f.metadata.get("internal"):
                continue
            value = getattr(self, f.name)
            if value is not None:
                out[f.name] = value.to_dict()
        return out

    @classmethod
    def from_frames(cls, frames: dict, *, timestamp: Optional[str] = None) -> "JkReadings":
        """Decode a {frame_type: raw_frame} mapping; missing frames stay None."""
        from .decoders import (decode_cell_data, decode_info, decode_logbook,
                               decode_settings)
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        cell = decode_cell_data(frames[2]) if 2 in frames else None
        return cls(
            info=decode_info(frames[3]) if 3 in frames else None,
            cell=cell,
            settings=(decode_settings(frames[1], cell.nslots if cell else 24)
                      if 1 in frames else None),
            logbook=decode_logbook(frames[5]) if 5 in frames else None,
            timestamp=timestamp,
            raw_frames=frames,
        )
