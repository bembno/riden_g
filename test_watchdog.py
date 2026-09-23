#!/usr/bin/env python3
"""Unit tests for the BMS watchdog decision logic (storage/bms_watchdog.py).

Runs anywhere - no BLE hardware, no MQTT, no Pi required:

    python test_watchdog.py

Covers the two production requirements:
  * never reset during normal operation or legitimate long-running work
    (slow BLE reads up to the hard timeout, error backoff up to MAX_BACKOFF)
  * always reset when the loop has genuinely stopped making progress, or
    when it spins tightly without ever completing a successful read.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "storage"))

from bms_watchdog import (  # noqa: E402
    LoopRateDetector, WatchdogConfig, check_progress, heartbeat_due)

CFG = WatchdogConfig()  # production defaults


class TestThresholds(unittest.TestCase):
    def test_stuck_threshold_exceeds_worst_legitimate_gap(self):
        """The reset threshold must leave a wide margin over any legal gap:
        a normal BMS outage (5 min backoff) or a slow read (2 min hard
        timeout) must never look 'stuck'."""
        self.assertGreater(CFG.stuck_s, CFG.worst_legit_gap_s * 1.5)

    def test_worst_gap_is_max_of_backoff_and_read_not_sum(self):
        """Progress is marked around every sleep/read, so the worst gap is
        max(backoff, read) - never their sum."""
        self.assertEqual(CFG.worst_legit_gap_s,
                         CFG.max_backoff_s + CFG.backoff_jitter_s)


class TestProgress(unittest.TestCase):
    def test_normal_30s_loop_never_stuck(self):
        """A healthy loop marking progress every ~30 s stays below the
        threshold for a simulated hour."""
        now = 1_000_000.0
        for _ in range(120):  # one hour of 30 s cycles
            now += 30.0
            self.assertIsNone(check_progress(now - 30.0, now, CFG))

    def test_long_error_backoff_never_stuck(self):
        """Worst legit pattern: 120 s BLE read attempt (progress marked at
        start and at outcome), then a 305 s backoff sleep (progress marked
        after the read outcome and after the sleep). Max single gap is the
        305 s sleep - still under the 600 s threshold."""
        t0 = 1_000_000.0
        gaps = [
            ("read attempt", t0, t0 + 120.0),
            ("backoff sleep", t0 + 120.0, t0 + 120.0 + 305.0),
            ("next read", t0 + 425.0, t0 + 425.0 + 1.0),
        ]
        for name, last, now in gaps:
            self.assertIsNone(check_progress(last, now, CFG),
                              msg=f"false stuck during legit phase: {name}")

    def test_stuck_detected_just_past_threshold(self):
        now = 2_000_000.0
        self.assertIsNotNone(check_progress(now - (CFG.stuck_s + 1), now, CFG))

    def test_not_stuck_just_below_threshold(self):
        now = 2_000_000.0
        self.assertIsNone(check_progress(now - (CFG.stuck_s - 1), now, CFG))

    def test_genuinely_frozen_loop_detected(self):
        """No progress marker at all for 10 minutes -> stuck."""
        now = 3_000_000.0
        reason = check_progress(now - 600.0 - 60.0, now, CFG)
        self.assertIsNotNone(reason)
        self.assertIn("no main-loop progress", reason)


class TestLoopRate(unittest.TestCase):
    def test_normal_rate_not_flagged(self):
        det = LoopRateDetector(CFG)
        now = 1_000_000.0
        cycles, success = 0, now
        for _ in range(20):          # 20 windows of 30 s
            now += 30.0
            cycles += 1              # one cycle per window = healthy
            success = now - 5.0      # read succeeded moments ago
            self.assertIsNone(det.observe(cycles, success, now))
        self.assertEqual(det.strikes, 0)

    def test_tight_loop_without_success_triggers_after_strikes(self):
        """Cycles racing ~10x faster than POLL_INTERVAL with zero successes
        -> flagged on the 2nd consecutive abnormal window (the first
        watchdog call only arms the baseline)."""
        det = LoopRateDetector(CFG)
        now = 1_000_000.0
        success = 0.0  # never succeeded
        # window 0: arm baseline
        now += 30.0
        self.assertIsNone(det.observe(1, success, now))
        self.assertEqual(det.strikes, 0)
        # window 1: abnormal but first strike only
        now += 30.0
        self.assertIsNone(det.observe(41, success, now))
        self.assertEqual(det.strikes, 1)
        # window 2: strike limit reached -> reason
        now += 30.0
        reason = det.observe(81, success, now)
        self.assertIsNotNone(reason)
        self.assertIn("tight loop", reason)

    def test_single_glitch_window_does_not_trigger(self):
        det = LoopRateDetector(CFG)
        now = 1_000_000.0
        now += 30.0
        self.assertIsNone(det.observe(1, now - 5.0, now))          # arm healthy
        now += 30.0
        self.assertIsNone(det.observe(50, now - 60.0, now))         # glitch window
        self.assertEqual(det.strikes, 1)
        now += 30.0
        self.assertIsNone(det.observe(51, now - 5.0, now))          # recovery resets
        self.assertEqual(det.strikes, 0)

    def test_error_loop_with_backoff_not_flagged(self):
        """Failing reads slow the loop down via backoff - far below the
        rate threshold, so a prolonged outage never looks like a tight loop."""
        det = LoopRateDetector(CFG)
        now = 1_000_000.0
        cycles = 0
        for _ in range(20):
            now += 60.0   # backoff makes cycles slower, not faster
            cycles += 1
            self.assertIsNone(det.observe(cycles, 0.0, now))
        self.assertEqual(det.strikes, 0)

    def test_high_rate_with_recent_success_not_flagged(self):
        """Fast cycles are only abnormal when paired with zero successes;
        a (hypothetical) healthy fast loop must not reset the bridge."""
        det = LoopRateDetector(CFG)
        now = 1_000_000.0
        now += 30.0
        self.assertIsNone(det.observe(1, now, now))
        now += 30.0
        # 40 cycles but a success happened inside this window
        self.assertIsNone(det.observe(41, now - 10.0, now))
        self.assertEqual(det.strikes, 0)


class TestHeartbeat(unittest.TestCase):
    def test_heartbeat_cadence(self):
        now = 1_000_000.0
        self.assertFalse(heartbeat_due(now, now + 60.0, CFG))
        self.assertTrue(heartbeat_due(now, now + CFG.hb_s, CFG))
        self.assertTrue(heartbeat_due(now, now + CFG.hb_s + 1.0, CFG))


if __name__ == "__main__":
    unittest.main(verbosity=2)
