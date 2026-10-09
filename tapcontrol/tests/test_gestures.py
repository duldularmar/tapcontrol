"""Tests for gesture grouping and timing logic (pure logic, no audio/GUI)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tapcontrol.config.settings import GestureDef, Settings            # noqa: E402
from tapcontrol.gestures.recognizer import (                           # noqa: E402
    GestureRecognizer, group_taps, resolve_gesture,                    # noqa: E402
)                                                                      # noqa: E402


def make_recognizer(counts=None, delay_ms=100, cooldown_ms=0,
                    max_interval_ms=150):
    gestures = [GestureDef(n, f"act{n}", enabled=True,
                           max_interval_ms=max_interval_ms)
                for n in (counts or (1, 2, 3))]
    r = GestureRecognizer(gestures, execute_delay_ms=delay_ms)
    r.cooldown_ms = cooldown_ms
    return r


class GroupingTests(unittest.TestCase):
    def test_split_by_gap(self):
        groups = group_taps([0, 100, 200, 700, 800], 400)
        self.assertEqual(groups, [[0, 100, 200], [700, 800]])

    def test_exact_boundary_is_same_group(self):
        groups = group_taps([0, 400, 900], 400)
        self.assertEqual(groups, [[0, 400], [900]])

    def test_resolve_gesture(self):
        gs = [GestureDef(1, "a", enabled=True),
              GestureDef(2, "b", enabled=False)]
        self.assertEqual(resolve_gesture(1, gs).action, "a")
        self.assertIsNone(resolve_gesture(2, gs))
        self.assertIsNotNone(resolve_gesture(2, gs, enabled_only=False))


class RecognizerTimingTests(unittest.TestCase):
    # Recognizer semantics: a pending gesture executes after the *grouping*
    # window for the next hypothetical tap expires (an earlier execute could
    # steal the 2nd tap of a double). Below, max_interval=150ms and the
    # execute delay (100ms) is smaller, so execution happens ~150ms after the
    # last tap.
    def test_single_tap_fires_after_grouping_window(self):
        r = make_recognizer()
        r.add_tap(0.0)
        self.assertIsNone(r.check_timeout(0.05))   # too early
        res = r.check_timeout(0.16)                # window passed
        self.assertIsNotNone(res)
        self.assertEqual(res.tap_count, 1)
        self.assertEqual(res.action, "act1")

    def test_double_tap_groups_and_waits(self):
        r = make_recognizer()
        self.assertIsNone(r.add_tap(0.0))          # 1st tap, still pending
        self.assertIsNone(r.check_timeout(0.11))   # not executed yet
        res = r.add_tap(0.12)                      # 2nd tap within gap
        self.assertIsNone(res)                     # double still pending
        res = r.check_timeout(0.30)
        self.assertIsNotNone(res)
        self.assertEqual(res.tap_count, 2)

    def test_gap_exceeding_max_interval_closes_gesture(self):
        r = make_recognizer()
        self.assertIsNone(r.add_tap(0.0))
        # 2nd tap more than max_interval later -> single fires first
        res = r.add_tap(1.5)
        self.assertIsNotNone(res)
        self.assertEqual(res.tap_count, 1)

    def test_cooldown_blocks_execution(self):
        r = make_recognizer(delay_ms=100, cooldown_ms=1000)
        r.add_tap(0.0)
        res = r.check_timeout(0.2)
        self.assertIsNotNone(res)
        # execute again within cooldown -> suppressed
        r.add_tap(0.5)
        self.assertIsNone(r.check_timeout(0.7))

    def test_unknown_count_not_executed(self):
        r = make_recognizer(counts=(1, 2))
        for i in range(5):
            r.add_tap(i * 0.1)
        # finishing after 5 taps: no gesture defined for 5 -> nothing
        self.assertIsNone(r.check_timeout(0.8))

    def test_disabled_count_not_executed(self):
        r = GestureRecognizer([GestureDef(1, "a", enabled=False)], 100)
        r.cooldown_ms = 0
        r.add_tap(0.0)
        self.assertIsNone(r.check_timeout(0.2))

    def test_reset_clears_pending(self):
        r = make_recognizer()
        r.add_tap(0.0)
        r.reset()
        self.assertIsNone(r.check_timeout(1.0))


class SettingsTests(unittest.TestCase):
    def test_roundtrip_save_load(self):
        s = Settings()
        s.sensitivity = 7
        s.calibration.calibrated = True
        s.calibration.noise_floor_dbfs = -52.0
        s.calibration.tap_peak_dbfs = -14.0
        tmp = os.path.join(os.path.dirname(__file__), "_tmp_cfg.json")
        s.save(tmp)
        s2 = Settings.load(tmp)
        os.unlink(tmp)
        self.assertEqual(s2.sensitivity, 7)
        self.assertTrue(s2.calibration.calibrated)
        self.assertEqual(s2.calibration.noise_floor_dbfs, -52.0)
        self.assertEqual(s2.gestures[0].action, "play_pause")
        # threshold derived between floor and tap peak
        thr = s2.threshold_dbfs()
        self.assertTrue(s2.calibration.noise_floor_dbfs < thr
                        < s2.calibration.tap_peak_dbfs)

    def test_corrupt_file_falls_back(self):
        tmp = os.path.join(os.path.dirname(__file__), "_tmp_bad.json")
        with open(tmp, "w") as fh:
            fh.write("{not json")
        s = Settings.load(tmp)
        os.unlink(tmp)
        self.assertEqual(s.sensitivity, 5)   # defaults restored


if __name__ == "__main__":
    unittest.main(verbosity=2)
