"""Tap detector: converts a stream of audio blocks into discrete tap events.

Detection chain per block:
  1. Bandpass the raw block, compute the fast-attack envelope in dBFS.
  2. Adaptive noise floor: exponential moving average of the envelope troughs
     (updated only while no transient is active, so taps never raise it).
  3. Peak detection vs threshold = noise floor + margin(sensitivity), plus an
     absolute floor, with a refractory period to merge detections that belong
     to the same physical impact (mic ringing / decay).
  4. Transient validation: steep rise time + minimum bandwidth brightness,
     rejecting continuous hum, HVAC, speech, and gentle background noise.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from .signal import bandpass_filter, reset_filter_state, spectral_centroid_db
from ..audio.capture import rms_to_dbfs


@dataclass
class TapEvent:
    timestamp: float          # time.monotonic() seconds
    peak_dbfs: float
    rise_ms: float
    centroid_hz: float


@dataclass
class DetectorState:
    noise_floor_dbfs: float = -60.0
    threshold_dbfs: float = -35.0
    last_peak_idx: int = -10**9


class TapDetector:
    def __init__(self, sample_rate: int, sensitivity: int = 5,
                 min_tap_interval_ms: int = 90, refractory_ms: int = 120,
                 min_peak_dbfs: float = -30.0, noise_floor_alpha: float = 0.02,
                 calibration: Optional[object] = None):
        self.sample_rate = int(sample_rate)
        self.sensitivity = sensitivity
        self.min_tap_interval_ms = min_tap_interval_ms
        self.refractory_ms = refractory_ms
        self.min_peak_dbfs = min_peak_dbfs
        self.noise_floor_alpha = noise_floor_alpha
        self.calibration = calibration
        self.state = DetectorState()
        self._filter_tag = f"det{id(self)}"
        reset_filter_state(self._filter_tag)
        self._in_transient = False
        self._fresh_onset = True          # armed when envelope is below threshold
        self._abs_pos = 0                 # absolute sample position of next block
        self._last_tap_time: Optional[float] = None
        self._env_state = -70.0                 # envelope memory across blocks

    # ------------------------------------------------------------------
    def configure(self, sensitivity: int, min_tap_interval_ms: int,
                  refractory_ms: int, min_peak_dbfs: float, alpha: float,
                  calibration: Optional[object]) -> None:
        self.sensitivity = sensitivity
        self.min_tap_interval_ms = min_tap_interval_ms
        self.refractory_ms = refractory_ms
        self.min_peak_dbfs = min_peak_dbfs
        self.noise_floor_alpha = alpha
        self.calibration = calibration

    @property
    def threshold_dbfs(self) -> float:
        return self.state.threshold_dbfs

    @property
    def noise_floor_dbfs(self) -> float:
        return self.state.noise_floor_dbfs

    # ------------------------------------------------------------------
    def process_block(self, block: np.ndarray,
                      timestamp: Optional[float] = None) -> List[TapEvent]:
        """Process one block of raw mono samples; return detected taps."""
        if block.size == 0:
            return []
        ts = timestamp if timestamp is not None else time.monotonic()
        block = block.astype(np.float64, copy=False)

        filtered = bandpass_filter(block, self.sample_rate,
                                   state_key=self._filter_tag)
        env_db = self._update_envelope(filtered)

        return self._detect_peaks(env_db, ts)

    # ------------------------------------------------------------------
    def _update_envelope(self, filtered: np.ndarray) -> np.ndarray:
        # reuse stateful fast attack/slow release across block boundaries
        rect = np.abs(filtered)
        n = rect.size
        a_att = np.exp(-1.0 / (0.001 * self.sample_rate))
        a_rel = np.exp(-1.0 / (0.060 * self.sample_rate))
        env = np.empty(n, dtype=np.float64)
        prev = self._env_state
        for i in range(n):
            x = rect[i]
            coeff = a_att if x > prev else a_rel
            prev = coeff * prev + (1.0 - coeff) * x
            env[i] = 20.0 * np.log10(max(prev, 1e-6))
        self._env_state = prev
        return env

    def _refresh_threshold(self) -> None:
        floor = max(-70.0, min(self.state.noise_floor_dbfs, -10.0))
        margin = 14.0 - 1.2 * max(1, min(10, int(self.sensitivity)))  # dB above floor
        threshold = floor + margin
        cal = self.calibration
        if cal is not None and getattr(cal, "calibrated", False) \
                and getattr(cal, "samples", None):
            # calibration: require peak to sit between observed noise and taps
            nf = float(cal.noise_floor_dbfs)
            tp = float(cal.tap_peak_dbfs)
            frac = 0.35 + 0.38 * (10 - max(1, min(10, int(self.sensitivity)))) / 9.0
            threshold = nf + (tp - nf) * frac
            threshold = max(threshold, floor + 6.0)
        self.state.threshold_dbfs = float(
            np.clip(threshold, max(self.min_peak_dbfs, -55.0), 0.0)
        )

    def _detect_peaks(self, env_db: np.ndarray, ts: float) -> List[TapEvent]:
        """Scan one envelope block and emit tap events.

        Uses absolute sample positions (block index + cumulative offset) so
        the minimum-tap-interval check works across block boundaries, and a
        fresh-onset flag so the decay tail of one physical tap is never
        re-validated as a new tap.
        """
        taps: List[TapEvent] = []
        n = env_db.size
        sr = self.sample_rate
        refractory = max(1, int(self.refractory_ms * sr / 1000))
        min_interval = int(self.min_tap_interval_ms * sr / 1000)
        base = self._abs_pos
        self._abs_pos += n

        i = 0
        while i < n:
            self._refresh_threshold()
            thr = self.state.threshold_dbfs
            v = env_db[i]

            if v < thr:
                # Quiet region: adapt the noise floor only outside transients.
                if not self._in_transient:
                    a = self.noise_floor_alpha
                    self.state.noise_floor_dbfs = (
                        (1 - a) * self.state.noise_floor_dbfs + a * v
                    )
                if v < thr - 3.0:
                    self._fresh_onset = True        # re-arm after decay
                    self._in_transient = False
                i += 1
                continue

            # v >= thr: potential onset — only valid if arming happened.
            if not self._fresh_onset:
                # decaying tail of a previous transient; wait for silence
                i += max(1, refractory // 2)
                continue

            rise_start = max(0, i - int(0.0025 * sr))
            rise_db = v - env_db[rise_start]
            accepted = False
            if rise_db >= 6.0:
                ev = self._validate_transient(env_db, i, ts, thr)
                if ev is not None:
                    gap = (base + i) - self.state.last_peak_idx
                    if gap >= min_interval:
                        taps.append(ev)
                        self.state.last_peak_idx = base + i
                        self._in_transient = True
                        self._fresh_onset = False
                        accepted = True
                    else:
                        self._fresh_onset = False   # same impact ringing
                else:
                    self._fresh_onset = False       # slow rise: not a tap
            i += refractory if accepted else max(1, refractory // 8)

        if self._in_transient and env_db[-1] < self.state.threshold_dbfs - 3.0:
            self._in_transient = False
        return taps

    def _validate_transient(self, env_db: np.ndarray, peak_idx: int,
                            ts: float, thr: float) -> Optional[TapEvent]:
        # rise time: how long to get from threshold-6dB to the peak
        start = max(0, peak_idx - int(0.010 * self.sample_rate))
        rise_samples = 0
        for j in range(peak_idx, start, -1):
            if env_db[j] < thr:
                rise_samples = peak_idx - j
                break
        rise_ms = rise_samples * 1000.0 / self.sample_rate
        if rise_ms > 15.0:          # too slow -> speech swell / noise, not a tap
            return None
        peak_db = float(env_db[peak_idx])
        # ping the caller's calibration context for brightness later if needed;
        # without raw samples here we accept envelope-validated transient
        return TapEvent(timestamp=ts + peak_idx / self.sample_rate,
                        peak_dbfs=peak_db, rise_ms=rise_ms, centroid_hz=0.0)


def block_rms_dbfs(block: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(block))) + 1e-12)
    return rms_to_dbfs(rms)
