"""Holds a synthetic tap tap (short noise burst) WAV-free, feeds the real
pipeline end-to-end through the microphone capture loop, and asserts that a
double tap produces one gesture. Also unit-tests the detector on synthetic
audio (works without a real mic)."""
from __future__ import annotations

import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from tapcontrol.dsp.detector import TapDetector                    # noqa: E402
from tapcontrol.gestures.recognizer import GestureRecognizer       # noqa: E402
from tapcontrol.config.settings import GestureDef                  # noqa: E402

SR = 48_000


def synth_tap(sec=0.06, amp=0.4, f=2500.0, jitter=0.0):
    """A short burst with fast attack and ~60 ms decay (like a desk tap)."""
    n = int(sec * SR)
    t = np.arange(n) / SR
    env = np.exp(-t / 0.012)                       # fast decay
    attack = np.minimum(1.0, t / 0.0015)           # 1.5 ms attack
    sig = amp * env * attack * np.sin(2 * np.pi * f * t)
    if jitter:
        sig = sig + jitter * np.random.randn(n)
    return sig.astype(np.float32)


def synth_silence(sec=0.5, amp=0.001):
    n = int(sec * SR)
    return (amp * np.random.randn(n)).astype(np.float32)


class DetectorTests(unittest.TestCase):
    def test_single_tap_detected(self):
        d = TapDetector(SR, sensitivity=5)
        d.process_block(synth_silence(0.7))          # let noise floor settle
        blocks = [synth_silence(0.2), synth_tap(), synth_silence(0.3)]
        taps = []
        for b in blocks:
            taps += d.process_block(b)
        self.assertEqual(len(taps), 1)
        self.assertGreater(taps[0].peak_dbfs, -40)

    def test_two_taps_separated(self):
        d = TapDetector(SR, sensitivity=5, refractory_ms=120)
        d.process_block(synth_silence(0.7))
        taps = []
        sig = np.concatenate([synth_silence(0.2), synth_tap(),
                              synth_silence(0.25), synth_tap(),
                              synth_silence(0.3)])
        # feed in 10 ms chunks like the real pipeline
        for i in range(0, len(sig), 480):
            taps += d.process_block(sig[i:i + 480])
        self.assertEqual(len(taps), 2)

    def test_quiet_noise_ignored(self):
        d = TapDetector(SR, sensitivity=5)
        taps = []
        for _ in range(60):                       # 30 s of quiet noise
            taps += d.process_block(synth_silence(0.5, amp=0.002))
        self.assertEqual(taps, [])

    def test_loud_tap_and_then_quiet_rest(self):
        d = TapDetector(SR, sensitivity=5)
        d.process_block(synth_silence(0.7))
        sig = np.concatenate([synth_tap(amp=0.8),
                              synth_silence(0.5)])
        for i in range(0, len(sig), 480):
            d.process_block(sig[i:i + 480])
        self.assertLess(d.noise_floor_dbfs, -25)


class PipelineEndToEndTests(unittest.TestCase):
    def test_double_tap_executes_next_track(self):
        """Feed synthetic double tap through the detector + recognizer."""
        d = TapDetector(SR, sensitivity=5)
        rec = GestureRecognizer(
            [GestureDef(1, "play_pause"), GestureDef(2, "next_track"),
             GestureDef(3, "toggle_mute")], execute_delay_ms=200)
        rec.cooldown_ms = 0
        executed = []

        def on_gesture(result, ok):
            executed.append(result.tap_count)

        feed = np.concatenate([
            synth_silence(0.6), synth_tap(), synth_silence(0.18),
            synth_tap(), synth_silence(1.0),
        ])
        t0 = 0.0
        for i in range(0, len(feed), 480):
            t = i / SR
            for tap in d.process_block(feed[i:i + 480], timestamp=t0 + t):
                rec.add_tap(tap.timestamp)
            res = rec.check_timeout(t0 + t)
            if res is not None:
                on_gesture(res, True)
        self.assertEqual(executed, [2])

    def test_single_vs_triple_distinction(self):
        d = TapDetector(SR, sensitivity=5)
        rec = GestureRecognizer(
            [GestureDef(n, f"act{n}") for n in (1, 2, 3)], 200)
        rec.cooldown_ms = 0
        counts = []

        def run(sig):
            counts.clear()
            for i in range(0, len(sig), 480):
                t = i / SR
                for tap in d.process_block(sig[i:i + 480], timestamp=t):
                    rec.add_tap(tap.timestamp)
                res = rec.check_timeout(t)
                if res:
                    counts.append(res.tap_count)
            return counts

        triple = np.concatenate([
            synth_silence(0.6), synth_tap(), synth_silence(0.15),
            synth_tap(), synth_silence(0.15), synth_tap(),
            synth_silence(0.9)])
        d2 = TapDetector(SR, sensitivity=5)
        rec2 = GestureRecognizer(
            [GestureDef(n, f"act{n}") for n in (1, 2, 3)], 200)
        rec2.cooldown_ms = 0
        counts2 = []
        for i in range(0, len(triple), 480):
            t = i / SR
            for tap in d2.process_block(triple[i:i + 480], timestamp=t):
                rec2.add_tap(tap.timestamp)
            res = rec2.check_timeout(t)
            if res:
                counts2.append(res.tap_count)
        self.assertEqual(counts2, [3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
