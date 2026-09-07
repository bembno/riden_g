"""BLE client reading JK BMS frames (JK-B2A24S15P, BEKEN BLE module).

Typical integration::

    from jkbms import JkBmsClient, read_all, read_live

    readings = read_live("C8:47:80:58:A3:A6")     # one-shot, sync
    print(readings.cell.battery_voltage_V)

    for readings in JkBmsClient(mac).poll(interval=30):
        store.append(readings)                     # or your own sink
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Dict, List, NamedTuple, Optional, Sequence, Tuple

from .constants import (CHR, CMD_CELL_INFO, CMD_DEVICE_INFO, CMD_LOGBOOK,
                        DEFAULT_MAC, DEFAULT_PIN)
from .models import JkReadings
from .pairing import BlueZPairingAgent
from .protocol import FrameParser, build_command

try:
    from bleak import BleakClient, BleakScanner
except ImportError as _exc:  # pragma: no cover
    raise ImportError(
        "bleak not installed: pip3 install --break-system-packages bleak dbus-fast"
    ) from _exc

log = logging.getLogger("jkbms.client")

Command = Tuple[int, float]

COMMANDS_LIVE: List[Command] = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5)]
COMMANDS_ALL: List[Command] = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5),
                               (CMD_LOGBOOK, 0.3)]


class BleCandidate(NamedTuple):
    """A BLE device advertising the JK BMS ffe0 service."""

    address: str
    name: Optional[str]
    service_uuids: List[str]


class JkBmsClient:
    """Connect, optionally bond (PIN), and collect frames from a JK BMS.

    Parameters mirror the behaviour of the original ``bms_red.py`` reader:
    ``want_types`` frames are collected; ``required`` frames must arrive
    within ``read_timeout`` seconds; once the required frames are in,
    collection continues up to ``optional_wait`` more seconds.
    """

    def __init__(self, mac: str = DEFAULT_MAC, pin: str = DEFAULT_PIN, *,
                 bond: bool = True, find_timeout: float = 15.0,
                 read_timeout: float = 25.0) -> None:
        self.mac = mac
        self.pin = pin
        self.bond = bond
        self.find_timeout = find_timeout
        self.read_timeout = read_timeout
        self._agent: Optional[BlueZPairingAgent] = None

    async def scan(self, timeout: float = 10.0) -> List[BleCandidate]:
        """Discover JK BMS candidates by the ffe0 service UUID."""
        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        found = []
        for d, adv in devices.values():
            uuids = [str(u) for u in (adv.service_uuids or [])]
            if any("ffe0" in u for u in uuids):
                found.append(BleCandidate(d.address, d.name, uuids))
        return found

    async def read_frames(self, want_types: Sequence[int] = (2,),
                          required: Sequence[int] = (2,),
                          commands: Optional[Sequence[Command]] = None,
                          optional_wait: float = 0,
                          timeout: Optional[float] = None) -> Dict[int, bytes]:
        """Run a command sequence and collect response frames.

        ``commands`` is a list of ``(cmd_byte, wait_s)`` sent in order
        (default: device info 0x97, then cell info 0x96). Returns a dict
        ``{frame_type: raw_300_byte_frame}``.
        """
        timeout = self.read_timeout if timeout is None else timeout
        dev = await BleakScanner.find_device_by_address(self.mac,
                                                        timeout=self.find_timeout)
        if not dev:
            raise RuntimeError("device not found (asleep / out of range?)")

        if self.bond:
            self._agent = BlueZPairingAgent(self.pin)
            await self._agent.pair(self.mac)
            await asyncio.sleep(1)

        try:
            if commands is None:
                commands = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5)]
            parser = FrameParser()
            frames: Dict[int, bytes] = {}

            def handler(_sender, data: bytearray) -> None:
                for frame in parser.feed(bytes(data)):
                    frames[frame[4]] = frame

            async with BleakClient(dev) as client:
                log.info("connected to %s", self.mac)
                await client.start_notify(CHR, handler)
                for cmd, wait_s in commands:
                    await client.write_gatt_char(CHR, build_command(cmd),
                                                 response=False)
                    await asyncio.sleep(wait_s)

                deadline = time.time() + timeout
                grace_end: Optional[float] = None
                while True:
                    now = time.time()
                    have_req = all(t in frames for t in required)
                    have_all = all(t in frames for t in want_types)
                    if have_req:
                        if grace_end is None:
                            grace_end = now + optional_wait
                        if have_all or now >= grace_end:
                            break
                    if now >= deadline:
                        break
                    await asyncio.sleep(0.2)
                await client.stop_notify(CHR)
        finally:
            if self._agent is not None:
                self._agent.close()
                self._agent = None

        missing = [t for t in required if t not in frames]
        if missing:
            raise RuntimeError(f"no frame(s) {missing} within {timeout}s "
                               f"(is the BMS bonded with PIN {self.pin}?)")
        return frames

    # -- high-level convenience API -------------------------------------
    async def read_live(self) -> JkReadings:
        """One read cycle: device info + live cell data, decoded."""
        frames = await self.read_frames(want_types=(2, 3), required=(2,),
                                         commands=COMMANDS_LIVE, optional_wait=3)
        return JkReadings.from_frames(frames)

    async def read_all(self) -> JkReadings:
        """Full read cycle: info, live data, settings, logbook, decoded."""
        frames = await self.read_frames(want_types=(1, 2, 3, 5), required=(2,),
                                         commands=COMMANDS_ALL, optional_wait=8)
        return JkReadings.from_frames(frames)

    async def poll(self, interval: float = 30.0,
                   include_all: bool = False) -> AsyncIterator[JkReadings]:
        """Yield readings forever, one every ``interval`` seconds.

        Read errors are logged and re-raised for the caller to decide
        (e.g. ``stop_on_error`` handling in :meth:`poll_sync`).
        """
        read = self.read_all if include_all else self.read_live
        while True:
            start = time.monotonic()
            yield await read()
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - start)))

    def poll_sync(self, interval: float = 30.0, include_all: bool = False,
                  stop_on_error: bool = False):
        """Blocking generator yielding :class:`JkReadings` forever.

        Read errors are logged; by default the loop continues after the
        interval, with ``stop_on_error=True`` the generator ends instead.
        Use :meth:`poll` from async code instead.
        """
        read = self.read_all if include_all else self.read_live
        while True:
            start = time.monotonic()
            try:
                yield _run(read())
            except Exception as e:
                log.error("read failed: %s", e)
                if stop_on_error:
                    return
            delay = max(0.0, interval - (time.monotonic() - start))
            time.sleep(delay)


def _run(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError("called from a running event loop; use the async API")


def read_live(mac: str = DEFAULT_MAC, *, pin: str = DEFAULT_PIN,
              bond: bool = True, **kwargs) -> JkReadings:
    """One-shot synchronous read (device info + live cell data)."""
    client = JkBmsClient(mac, pin, bond=bond, **kwargs)
    return _run(client.read_live())


def read_all(mac: str = DEFAULT_MAC, *, pin: str = DEFAULT_PIN,
             bond: bool = True, **kwargs) -> JkReadings:
    """One-shot synchronous full read (info, live, settings, logbook)."""
    client = JkBmsClient(mac, pin, bond=bond, **kwargs)
    return _run(client.read_all())
