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
import threading
import time
from typing import Any, Dict, AsyncIterator, List, NamedTuple, Optional, Sequence, Tuple

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

# --- phase diagnostics for the watchdog / 24 h abms_log.txt test ---------
# LAST_DIAG always describes the *latest* read attempt: which phase it is
# in (find / pair / connect / notify / cmd / collect / done / error), how
# long each phase took and which frames arrived.  When the bridge hangs,
# the phase string shows exactly where it is stuck.  Updates are guarded
# by a generation counter so a leaked worker from a previously timed-out
# read cannot overwrite the current attempt's state.
LAST_DIAG: Dict[str, Any] = {"phase": "idle"}
_DIAG_LOCK = threading.Lock()
_DIAG_GEN = 0


def _diag_begin() -> int:
    global _DIAG_GEN
    with _DIAG_LOCK:
        _DIAG_GEN += 1
        LAST_DIAG.clear()
        LAST_DIAG.update(gen=_DIAG_GEN, phase="find", t0=time.time())
        return _DIAG_GEN


def _diag_set(gen: int, **kw: Any) -> None:
    with _DIAG_LOCK:
        if gen == LAST_DIAG.get("gen"):
            LAST_DIAG.update(kw)

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

        Phase timings are recorded in :data:`LAST_DIAG` as the read
        progresses so a stuck read can be attributed to find / pair /
        connect / notify / cmd / collect.
        """
        timeout = self.read_timeout if timeout is None else timeout
        gen = _diag_begin()
        t_read = time.monotonic()
        notify = {"n": 0, "bytes": 0}
        try:
            t0 = time.monotonic()
            dev = await BleakScanner.find_device_by_address(self.mac,
                                                            timeout=self.find_timeout)
            _diag_set(gen, find_ms=round((time.monotonic() - t0) * 1000, 1),
                      found=bool(dev))
            if not dev:
                raise RuntimeError("device not found (asleep / out of range?)")

            agent = None
            if self.bond:
                _diag_set(gen, phase="pair")
                t0 = time.monotonic()
                agent = BlueZPairingAgent(self.pin)
                try:
                    await agent.pair(self.mac)
                    await asyncio.sleep(1)
                    _diag_set(gen, pair_ms=round((time.monotonic() - t0) * 1000, 1))
                except Exception:
                    agent.close()
                    raise

            try:
                if commands is None:
                    commands = [(CMD_DEVICE_INFO, 1.0), (CMD_CELL_INFO, 0.5)]
                parser = FrameParser()
                frames: Dict[int, bytes] = {}
                _diag_set(gen, phase="connect",
                          commands=[[c, w] for c, w in commands])

                def handler(_sender, data: bytearray) -> None:
                    notify["n"] += 1
                    notify["bytes"] += len(data)
                    parsed = parser.feed(bytes(data))
                    for frame in parsed:
                        frames[frame[4]] = frame
                    _diag_set(gen, notify_n=notify["n"],
                              notify_bytes=notify["bytes"],
                              frames_seen=sorted(frames))

                t0 = time.monotonic()
                async with BleakClient(dev) as client:
                    _diag_set(gen,
                              connect_ms=round((time.monotonic() - t0) * 1000, 1),
                              phase="notify")
                    log.info("connected to %s", self.mac)
                    t0 = time.monotonic()
                    await client.start_notify(CHR, handler)
                    _diag_set(gen,
                              notify_ms=round((time.monotonic() - t0) * 1000, 1))
                    for i, (cmd, wait_s) in enumerate(commands):
                        _diag_set(gen, phase=f"cmd_{i}_{cmd:#04x}")
                        t0 = time.monotonic()
                        await client.write_gatt_char(CHR, build_command(cmd),
                                                     response=False)
                        _diag_set(gen, write_ms=round((time.monotonic() - t0) * 1000, 1))
                        await asyncio.sleep(wait_s)

                    _diag_set(gen, phase="collect")
                    t0 = time.monotonic()
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
                    _diag_set(gen,
                              collect_ms=round((time.monotonic() - t0) * 1000, 1))
                    await client.stop_notify(CHR)
                _diag_set(gen, phase="done")
            finally:
                if agent is not None:
                    agent.close()

            missing = [t for t in required if t not in frames]
            if missing:
                _diag_set(gen, phase="error",
                          error=f"missing frames {missing}")
                raise RuntimeError(f"no frame(s) {missing} within {timeout}s "
                                   f"(is the BMS bonded with PIN {self.pin}?)")
            _diag_set(gen, total_ms=round((time.monotonic() - t_read) * 1000, 1))
            return frames
        except Exception as e:
            _diag_set(gen, phase="error", error=str(e),
                      total_ms=round((time.monotonic() - t_read) * 1000, 1))
            raise

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
