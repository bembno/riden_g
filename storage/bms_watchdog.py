"""Watchdog decision logic for the BMS bridge (bms_mqtt.py).

Pure logic only: no I/O, no threads, no bleak import - so it can be
unit-tested on any machine (see test_watchdog.py) without BLE hardware.

Two failure modes are detected:

1. Stopped making progress: the main loop did not complete an iteration
   (no progress marker) for longer than ``stuck_s``.  Progress is marked
   at the start of every iteration, after every read outcome (success,
   error or timeout) and after every sleep - so the largest legitimate
   gap without a marker is ``max_backoff_s + backoff_jitter_s`` (error
   backoff sleep) or ``read_hard_timeout_s`` (BLE read attempt), never
   both.  ``stuck_s`` must exceed ``worst_legit_gap_s`` with margin so a
   normal BMS outage (up to 5 min backoff) or a slow-but-alive BLE read
   (up to 2 min) never resets the bridge.

2. Continuously looping without progress: the iteration counter races
   far ahead of what POLL_INTERVAL allows while no successful read
   completed in the same window (tight error loop / livelock).  Legit
   operation only ever slows down (backoff grows with failures), so a
   several-fold excess of cycle rate with zero successes cannot happen
   normally.  Two consecutive abnormal windows are required before a
   reset to tolerate one-off timing glitches.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WatchdogConfig:
    """Thresholds for the BMS bridge watchdog.

    Defaults are sized for the production bridge: POLL_INTERVAL=30s,
    READ_HARD_TIMEOUT=120s, MAX_BACKOFF=300s (+5s jitter).
    """
    stuck_s: float = 600.0            # no progress marker for this long -> stuck
    check_s: float = 30.0             # watchdog evaluation cadence
    hb_s: float = 120.0               # heartbeat record cadence (also during stalls)
    poll_interval_s: float = 30.0
    read_hard_timeout_s: float = 120.0
    max_backoff_s: float = 300.0
    backoff_jitter_s: float = 5.0
    loop_factor: float = 5.0          # cycles/window vs expected before flagging
    loop_min_cycles: int = 6          # absolute floor for the flag
    loop_strikes: int = 2             # consecutive abnormal windows before reset

    @property
    def worst_legit_gap_s(self) -> float:
        """Largest gap between progress markers that normal operation can produce."""
        return max(self.max_backoff_s + self.backoff_jitter_s,
                   self.read_hard_timeout_s + 10.0)


def check_progress(last_progress: float, now: float,
                   cfg: WatchdogConfig) -> Optional[str]:
    """Return a reason string when the main loop is stuck, else None."""
    age = now - last_progress
    if age > cfg.stuck_s:
        return (f"no main-loop progress for {age:.0f}s "
                f"(limit {cfg.stuck_s:.0f}s)")
    return None


def heartbeat_due(last_hb: float, now: float, cfg: WatchdogConfig) -> bool:
    """True when a heartbeat diagnostic record should be written."""
    return (now - last_hb) >= cfg.hb_s


class LoopRateDetector:
    """Flags a main loop spinning much faster than POLL_INTERVAL allows
    while never completing a successful read.

    Call :meth:`observe` once per watchdog window with the cumulative
    cycle counter and the timestamp of the last successful read.
    Returns a reason string when ``cfg.loop_strikes`` consecutive
    abnormal windows were seen, else None.
    """

    def __init__(self, cfg: WatchdogConfig) -> None:
        self.cfg = cfg
        self.strikes = 0
        self._last_cycles: Optional[int] = None
        self._last_t: float = 0.0

    def observe(self, cycles: int, last_success: float, now: float) -> Optional[str]:
        cfg = self.cfg
        if self._last_cycles is None:
            self._last_cycles = cycles
            self._last_t = now
            return None
        delta = cycles - self._last_cycles
        window = now - self._last_t
        self._last_cycles = cycles
        self._last_t = now
        if window <= 0:
            return None
        expected = window / max(cfg.poll_interval_s, 1e-6)
        threshold = max(float(cfg.loop_min_cycles), cfg.loop_factor * expected)
        no_success = (now - last_success) >= window if last_success > 0 else True
        if delta > threshold and no_success:
            self.strikes += 1
            if self.strikes >= cfg.loop_strikes:
                return (f"tight loop without successful reads: {delta} cycles "
                        f"in {window:.0f}s (threshold {threshold:.1f}, "
                        f"strikes {self.strikes})")
            return None
        self.strikes = 0
        return None
