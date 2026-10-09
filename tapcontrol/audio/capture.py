"""Microphone capture via sounddevice.

The PortAudio callback stays extremely lightweight: it only copies the block
into a thread-safe queue (with drop-oldest overflow policy) and updates a
lock-free RMS level. All signal processing happens in a separate worker thread.
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd


class MicrophoneCapture:
    """Continuous microphone input. Never blocks the audio callback."""

    def __init__(self, sample_rate: int = 48_000, block_size: int = 480,
                 device: Optional[int] = None, channels: int = 1,
                 queue_size: int = 64):
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.device = device
        self.channels = max(1, int(channels))
        self._q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=queue_size)
        self._stream: Optional[sd.InputStream] = None
        self._lock = threading.Lock()
        self._level_rms = 0.0
        self._level_peak = 0.0
        self._dropped_blocks = 0
        self._running = False
        self._last_callback_error: Optional[str] = None

    # ---- public API -------------------------------------------------
    def list_input_devices(self):
        out = []
        try:
            for i, d in enumerate(sd.query_devices()):
                if d["max_input_channels"] > 0:
                    out.append({"index": i, "name": d["name"],
                                "channels": d["max_input_channels"],
                                "default": i == sd.default.device[0]})
        except Exception:
            pass
        return out

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return True
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    blocksize=self.block_size,
                    device=self.device,
                    channels=self.channels,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._running = True
                self._last_callback_error = None
                return True
            except Exception as exc:                       # device missing/busy
                self._last_callback_error = str(exc)
                self._stream = None
                self._running = False
                return False

    def stop(self) -> None:
        with self._lock:
            self._running = False
            stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def read_block(self, timeout: float = 0.25) -> Optional[np.ndarray]:
        """Worker thread: fetch next audio block or None on timeout."""
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def current_level(self) -> tuple[float, float]:
        """(rms, peak) of the most recent block, for GUI meters."""
        return self._level_rms, self._level_peak

    def dropped_blocks(self) -> int:
        return self._dropped_blocks

    def last_error(self) -> Optional[str]:
        return self._last_callback_error

    def restart(self) -> bool:
        """Recover after microphone disconnection."""
        self.stop()
        time.sleep(0.15)
        return self.start()

    # ---- internal ----------------------------------------------------
    def _audio_callback(self, indata, frames, time_info, status) -> None:
        # Callback contract: no locks held long, no blocking calls.
        if status:
            self._last_callback_error = str(status)
        mono = indata[:, 0].copy()
        lvl = float(np.sqrt(np.mean(np.square(mono))) + 1e-12)
        self._level_rms = lvl
        self._level_peak = float(np.max(np.abs(mono)) + 1e-12)
        try:
            self._q.put_nowait(mono)
        except queue.Full:
            # drop the oldest block, keep the newest (latency stays bounded)
            try:
                self._q.get_nowait()
                self._q.put_nowait(mono)
            except (queue.Empty, queue.Full):
                pass
            self._dropped_blocks += 1


def rms_to_dbfs(rms: float) -> float:
    return 20.0 * np.log10(max(rms, 1e-10))
