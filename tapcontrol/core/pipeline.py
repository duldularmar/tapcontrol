"""Pipeline: audio capture thread -> detector -> gesture recognizer -> actions.

Runs entirely off the GUI thread. The GUI polls shared state via
`snapshot()`; detected taps and executed gestures are delivered to the GUI
through thread-safe queued invocations (see gui.window).
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from ..audio.capture import MicrophoneCapture, rms_to_dbfs
from ..dsp.detector import TapDetector
from ..gestures.recognizer import GestureRecognizer, GestureResult
from ..actions import win_actions
from ..config.settings import Settings


@dataclass
class PipelineSnapshot:
    running: bool = False
    level_rms: float = 0.0
    level_peak: float = 0.0
    level_dbfs: float = -80.0
    noise_floor_dbfs: float = -70.0
    threshold_dbfs: float = -40.0
    taps_detected: int = 0
    gestures_executed: int = 0
    dropped_blocks: int = 0
    last_error: Optional[str] = None
    pending_taps: int = 0


class TapPipeline:
    """Owns the audio and processing threads; thread-safe towards the GUI."""

    def __init__(self, settings_getter: Callable[[], Settings],
                 on_tap: Optional[Callable[[float], None]] = None,
                 on_gesture: Optional[Callable[[GestureResult, bool], None]] = None,
                 on_error: Optional[Callable[[str], None]] = None):
        self._get_settings = settings_getter
        self._on_tap = on_tap
        self._on_gesture = on_gesture
        self._on_error = on_error

        self._mic = MicrophoneCapture(device=settings_getter().device,
                                      sample_rate=settings_getter().sample_rate,
                                      block_size=settings_getter().block_size)
        self._detector = TapDetector(sample_rate=settings_getter().sample_rate)
        self._recognizer = GestureRecognizer([], 420)
        self._recognizer.cooldown_ms = settings_getter().cooldown_ms

        self._lock = threading.RLock()
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._calibration_mode = False
        self._calib_taps: List[float] = []    # tap peaks for the wizard
        self._taps_total = 0
        self._gestures_total = 0
        self._snapshot = PipelineSnapshot()
        self.debug_mode = False
        self._dbg_last_peaks: List[float] = []   # recent peak dBFS values

    # ---------------- lifecycle ----------------
    def start(self) -> bool:
        with self._lock:
            if self._running():
                return True
            s = self._get_settings()
            self._mic = MicrophoneCapture(device=s.device,
                                          sample_rate=s.sample_rate,
                                          block_size=s.block_size)
            self._detector = TapDetector(
                sample_rate=s.sample_rate, sensitivity=s.sensitivity,
                min_tap_interval_ms=s.min_tap_interval_ms,
                refractory_ms=s.refractory_ms, min_peak_dbfs=s.min_peak_dbfs,
                noise_floor_alpha=s.noise_floor_alpha,
                calibration=s.calibration if s.calibration.calibrated else None)
            self._recognizer = GestureRecognizer(
                [g for g in s.gestures], s.gesture_execute_delay_ms)
            self._recognizer.cooldown_ms = s.cooldown_ms
            ok = self._mic.start()
            if not ok:
                err = self._mic.last_error() or "microphone unavailable"
                if self._on_error:
                    self._on_error(f"Could not start microphone: {err}")
                return False
            self._stop_evt.clear()
            self._thread = threading.Thread(
                target=self._run, name="TapControlWorker", daemon=True)
            self._thread.start()
            # snapshot.running reflects thread state; mark running immediately
            with self._lock:
                pass
            return True

    def _running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def is_running(self) -> bool:
        return self._running()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None
        self._mic.stop()          # always closes the audio stream on exit
        self._recognizer.reset()
        self._update_snapshot()

    # ---------------- calibration hooks ----------------
    def set_calibration_mode(self, on: bool) -> None:
        with self._lock:
            self._calibration_mode = bool(on)
            self._calib_taps = []
        if on:
            self._recognizer.reset()

    def calibration_mode(self) -> bool:
        with self._lock:
            return self._calibration_mode

    def drain_calibration_taps(self) -> List[float]:
        """Tap peak levels (dBFS) recorded since the last call."""
        with self._lock:
            out = self._calib_taps
            self._calib_taps = []
            return out

    # ---------------- runtime config ----------------
    def apply_settings(self) -> None:
        """Hot-apply settings changes (sliders, gestures) without restarting."""
        s = self._get_settings()
        self._detector.configure(
            sensitivity=s.sensitivity,
            min_tap_interval_ms=s.min_tap_interval_ms,
            refractory_ms=s.refractory_ms,
            min_peak_dbfs=s.min_peak_dbfs,
            alpha=s.noise_floor_alpha,
            calibration=s.calibration if s.calibration.calibrated else None)
        self._recognizer.configure(
            [g for g in s.gestures], s.gesture_execute_delay_ms)
        self._recognizer.cooldown_ms = s.cooldown_ms

    # ---------------- worker loop ----------------
    def _run(self) -> None:
        while not self._stop_evt.is_set():
            block = self._mic.read_block(timeout=0.15)
            if block is None:
                # recover if the device died while we were running
                if not self._mic.is_running():
                    msg = self._mic.last_error() or "microphone stream ended"
                    self._notify_error(msg)
                    if not self._mic.restart():
                        time.sleep(0.5)   # back off before next attempt
                self._recognizer.check_timeout()
                self._update_snapshot()
                continue
            now = time.monotonic()
            taps = self._detector.process_block(block, now)
            with self._lock:
                calib = self._calibration_mode
            for t in taps:
                self._taps_total += 1
                if self.debug_mode:
                    with self._lock:
                        self._dbg_last_peaks = self._dbg_last_peaks[-9:] + [
                            round(t.peak_dbfs, 1), round(t.rise_ms, 1)]
                if self._on_tap:
                    try:
                        self._on_tap(t.peak_dbfs)
                    except Exception:
                        pass
                if calib:
                    with self._lock:
                        self._calib_taps.append(t.peak_dbfs)
                else:
                    self._recognizer.add_tap(t.timestamp)
            result = self._recognizer.check_timeout(now)
            if result is not None and not calib:
                self._execute(result)
            self._update_snapshot()

    def _execute(self, result: GestureResult) -> None:
        self._gestures_total += 1
        ok = False
        try:
            ok = win_actions.execute_action(result.action)
        except Exception:
            ok = False
        if self._on_gesture:
            try:
                self._on_gesture(result, ok)
            except Exception:
                pass

    def _notify_error(self, msg: str) -> None:
        if self._on_error:
            try:
                self._on_error(msg)
            except Exception:
                pass

    # ---------------- snapshot for GUI ----------------
    def _update_snapshot(self) -> None:
        rms, peak = self._mic.current_level()
        snap = PipelineSnapshot(
            running=self._running(),
            level_rms=rms, level_peak=peak,
            level_dbfs=rms_to_dbfs(rms) if rms else -80.0,
            noise_floor_dbfs=self._detector.noise_floor_dbfs,
            threshold_dbfs=self._detector.threshold_dbfs,
            taps_detected=self._taps_total,
            gestures_executed=self._gestures_total,
            dropped_blocks=self._mic.dropped_blocks(),
            last_error=self._mic.last_error(),
            pending_taps=0,
        )
        with self._lock:
            self._snapshot = snap

    def snapshot(self) -> PipelineSnapshot:
        with self._lock:
            return self._snapshot

    def debug_peaks(self) -> List[float]:
        """Recent detected peaks interleaved with rise times (debug mode)."""
        with self._lock:
            return list(self._dbg_last_peaks)
