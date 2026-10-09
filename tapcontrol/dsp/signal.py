"""Signal processing: bandpass filtering and energy envelope extraction."""
from __future__ import annotations

import numpy as np
from scipy import signal as sp_signal


# Persistent filter state so block boundaries do not introduce discontinuities
# (a hard reset at every 10 ms block would attenuate the filter's own transient
# and swallow the first of two closely spaced taps).
_SOS_STATE: dict = {}


def bandpass_filter(block: np.ndarray, sample_rate: int,
                    hp_hz: float = 150.0, lp_hz: float = 4500.0,
                    state_key: object = "default") -> np.ndarray:
    """Bandpass for tap transients with continuous state across blocks.

    Desk taps carry most energy between ~300 Hz and ~4 kHz. Removing rumble
    below 150 Hz (HVAC, traffic, fans) and hiss above 4.5 kHz makes the energy
    envelope far cleaner before peak detection.
    """
    nyq = sample_rate / 2.0
    hp = min(max(hp_hz, 10.0), nyq * 0.9)
    lp = min(max(lp_hz, hp + 50.0), nyq * 0.95)
    sos = sp_signal.butter(2, [hp, lp], btype="bandpass", fs=sample_rate,
                           output="sos")
    key = (state_key, sample_rate, round(hp, 1), round(lp, 1))
    zi = _SOS_STATE.get(key)
    if zi is None:
        zi = np.zeros((sos.shape[0], 2))
    out, zf = sp_signal.sosfilt(sos, np.asarray(block, dtype=np.float64), zi=zi)
    _SOS_STATE[key] = zf
    return out


def reset_filter_state(state_key: object = "default") -> None:
    _SOS_STATE.pop((state_key, ), None)
    for k in [k for k in _SOS_STATE if k[0] == state_key]:
        _SOS_STATE.pop(k, None)


def envelope_dbfs(filtered: np.ndarray, sample_rate: int,
                  attack_ms: float = 1.0, release_ms: float = 60.0) -> np.ndarray:
    """Fast-attack / slow-release energy envelope in dBFS.

    The fast attack captures the transient onset of a tap; the slow release
    means one physical tap produces a single hump on the envelope instead of
    ringing into several peaks.
    """
    rect = np.abs(filtered)
    n = rect.size
    if n == 0:
        return rect
    a_att = np.exp(-1.0 / (attack_ms * 1e-3 * sample_rate))
    a_rel = np.exp(-1.0 / (release_ms * 1e-3 * sample_rate))
    env = np.empty(n, dtype=np.float64)
    prev = 0.0
    for i in range(n):
        x = rect[i]
        coeff = a_att if x > prev else a_rel
        prev = coeff * prev + (1.0 - coeff) * x
        env[i] = prev
    floor = 1e-6
    return 20.0 * np.log10(np.maximum(env, floor))


def spectral_centroid_db(filtered: np.ndarray,
                         sample_rate: int) -> float:
    """Rough brightness measure used to reject low-frequency speech/rumble."""
    spec = np.abs(np.fft.rfft(filtered))
    freqs = np.fft.rfftfreq(filtered.size, 1.0 / sample_rate)
    total = spec.sum()
    if total <= 0:
        return 0.0
    return float((freqs * spec).sum() / total)
