"""Calibration: sample background noise, then several test taps, and compute
per-microphone thresholds (no hardcoded assumption about mic volume)."""
from __future__ import annotations

import statistics
import time
from typing import Callable, List, Optional

import numpy as np

from ..audio.capture import rms_to_dbfs
from ..config.settings import CalibrationParams, Settings
from ..dsp.detector import TapDetector


class CalibrationSession:
    """Two-phase calibration driven by the GUI.

    Phase 1: collect ~2-3 s of ambient noise frames -> noise floor.
    Phase 2: user taps several times -> per-tap peak dBFS, median taken.

    `tap_feed` should return tap peak levels (dBFS) recorded since the last
    call, fed from the live detector while calibration mode is on.
    """

    NOISE_MS = 2500
    MIN_TAPS = 4

    def __init__(self, settings: Settings,
                 level_feed: Callable[[], tuple[float, float]],
                 tap_feed: Callable[[], List[float]]):
        self._settings = settings
        self._level_feed = level_feed
        self._tap_feed = tap_feed
        self.phase: str = "idle"          # idle | noise | taps | done
        self._noise_samples: List[float] = []
        self._tap_peaks: List[float] = []
        self._noise_dbfs: float = -55.0
        self._t0 = 0.0

    # ------------------------------------------------------------------
    def start(self) -> str:
        self.phase = "noise"
        self._noise_samples = []
        self._tap_peaks = []
        self._t0 = time.monotonic()
        return "Listen quietly... sampling background noise (2.5 s)."

    def update(self) -> Optional[str]:
        """Poll from the GUI timer; advances phases, returns a status message."""
        if self.phase == "idle":
            return None
        rms, peak = self._level_feed()
        dbfs = rms_to_dbfs(rms)
        if self.phase == "noise":
            self._noise_samples.append(dbfs)
            elapsed = time.monotonic() - self._t0
            if elapsed * 1000 >= self.NOISE_MS:
                # use a robust low percentile of ambient level as the floor
                self._noise_dbfs = float(np.percentile(self._noise_samples, 35))
                self.phase = "taps"
                return ("Noise floor measured: "
                        f"{self._noise_dbfs:.1f} dBFS. Now tap the desk "
                        f"{self.MIN_TAPS} times, firmly.")
            return f"Sampling noise... {int(max(0,(self.NOISE_MS - (time.monotonic()-self._t0)*1000))/100)+1}"
        if self.phase == "taps":
            self._tap_peaks.extend(self._tap_feed())
            if len(self._tap_peaks) >= self.MIN_TAPS:
                self.finish()
                return "Calibration complete."
            missing = self.MIN_TAPS - len(self._tap_peaks)
            return f"Taps: {len(self._tap_peaks)}/{self.MIN_TAPS} — keep tapping."
        return None

    def finish(self) -> None:
        if not self._tap_peaks:
            self.phase = "done"
            return
        peak_med = float(statistics.median(self._tap_peaks))
        cal = CalibrationParams(
            noise_floor_dbfs=self._noise_dbfs,
            tap_peak_dbfs=peak_med,
            calibrated=True,
            samples=[round(v, 1) for v in self._tap_peaks[:20]],
        )
        self._settings.calibration = cal
        # sensible peak cap: median tap level, so weaker taps still detect
        # but the threshold does not demand identical-mic spikes
        self._settings.min_peak_dbfs = float(
            np.clip(peak_med - 4.0, -55.0, -5.0))
        self.phase = "done"

    def abort(self) -> None:
        self.phase = "idle"

    # ------------------------------------------------------------------
    def result_summary(self) -> str:
        if not self._settings.calibration.calibrated:
            return "Not calibrated"
        c = self._settings.calibration
        return (f"noise {c.noise_floor_dbfs:.1f} dBFS • tap "
                f"{c.tap_peak_dbfs:.1f} dBFS • {len(c.samples)} samples")
