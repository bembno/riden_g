"""JK BMS BLE reader package.

Integration-oriented layout; no backward compatibility with the original
single-file ``bms_red.py`` script.

Library use (the main entry points)::

    from jkbms import JkBmsClient, JsonlStore, read_all, read_live

    readings = read_live("C8:47:80:58:A3:A6")       # one-shot, synchronous
    readings.cell.battery_voltage_V                  # typed attributes

    # regular capture into a local JSONL file:
    client = JkBmsClient("C8:47:80:58:A3:A6")
    store = JsonlStore("/home/pi/bms_data/readings.jsonl")
    for readings in client.poll_sync(interval=30):
        store.append(readings)

    # or fully async:
    async def main():
        async for readings in client.poll(interval=30):
            await sink(readings)

Modules:

- :mod:`jkbms.constants`  protocol constants and lookup tables
- :mod:`jkbms.protocol`   frame building and stream parsing
- :mod:`jkbms.models`     typed result models (``JkReadings`` aggregate)
- :mod:`jkbms.decoders`   raw frame -> model decoders
- :mod:`jkbms.storage`    ``JsonlStore`` local JSONL persistence
- :mod:`jkbms.client`    BLE client (``JkBmsClient``, one-shot helpers)
- :mod:`jkbms.pairing`   BlueZ pairing agent (dbus-fast, Linux only)
- :mod:`jkbms.cli`       command-line interface (``python -m jkbms``)
"""

from __future__ import annotations

from .constants import (BALANCER_STATUS, BATTERY_TYPES, CHARGE_STATUS,
                        DEFAULT_MAC, DEFAULT_PIN, ERRORS_JK02, LOGBOOK_CODES)
from .decoders import decode_cell_data, decode_info, decode_logbook, decode_settings
from .models import ABSENT, CellData, DeviceInfo, JkReadings, Logbook, Settings
from .protocol import FrameParser, build_command, crc8
from .storage import JsonlStore

__version__ = "2.0.0"


def __getattr__(name):
    """Lazily import hardware-touching names so the pure-protocol modules
    stay importable without ``bleak`` installed."""
    if name in ("JkBmsClient", "read_live", "read_all"):
        import jkbms.client as _client_mod
        return getattr(_client_mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ABSENT", "BALANCER_STATUS", "BATTERY_TYPES", "CHARGE_STATUS",
    "CellData", "DEFAULT_MAC", "DEFAULT_PIN", "ERRORS_JK02", "FrameParser",
    "JkReadings", "LOGBOOK_CODES", "Logbook", "Settings", "DeviceInfo",
    "JsonlStore", "JkBmsClient", "build_command", "crc8", "decode_cell_data",
    "decode_info", "decode_logbook", "decode_settings", "read_all",
    "read_live",
]
