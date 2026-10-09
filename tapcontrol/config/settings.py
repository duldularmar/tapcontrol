"""Application configuration: dataclasses that serialize cleanly to JSON."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

CONFIG_DIR_NAME = "TapControl"
CONFIG_FILE_NAME = "config.json"


def default_config_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, CONFIG_DIR_NAME, CONFIG_FILE_NAME)


@dataclass
class CalibrationParams:
    """Values produced by the calibration wizard (thresholds not hardcoded)."""
    noise_floor_dbfs: float = -55.0
    tap_peak_dbfs: float = -18.0
    calibrated: bool = False
    samples: List[float] = field(default_factory=list)


@dataclass
class GestureDef:
    tap_count: int
    action: str          # logical action id, e.g. "play_pause"
    enabled: bool = True
    max_interval_ms: int = 450   # max gap between consecutive taps in the gesture


# Logical action identifiers GestureDef.action may point to. Never shell commands.
KNOWN_ACTIONS = (
    "play_pause", "next_track", "prev_track", "toggle_mute",
    "volume_up", "volume_down",
)


@dataclass
class Settings:
    # Audio
    sample_rate: int = 48_000
    block_size: int = 480            # 10 ms blocks
    device: Optional[int] = None     # None = system default input
    channels: int = 1

    # Detection
    sensitivity: int = 5             # 1..10, 10 = most sensitive
    min_tap_interval_ms: int = 90    # debounce: single physical tap -> one detection
    gesture_gap_ms: int = 420        # grouping timeout: gaps longer than this end gesture
    gesture_gap_max_ms: int = 1000   # slider upper bound
    gesture_execute_delay_ms: int = 420  # wait after last tap before executing
    cooldown_ms: int = 700           # after executing a gesture, ignore taps this long
    min_peak_dbfs: float = -30.0     # absolute cap; refined by calibration
    refractory_ms: int = 120         # min time between independent detected peaks
    noise_floor_alpha: float = 0.02  # adaptive noise floor smoothing factor

    # Calibration
    calibration: CalibrationParams = field(default_factory=CalibrationParams)

    # Gestures
    gestures: List[GestureDef] = field(default_factory=lambda: [
        GestureDef(1, "play_pause"),
        GestureDef(2, "next_track"),
        GestureDef(3, "toggle_mute"),
        GestureDef(4, "volume_down"),
        GestureDef(5, "volume_up"),
    ])

    # App behaviour
    theme: str = "dark"
    start_minimized: bool = False
    launch_on_startup: bool = False
    global_hotkey: str = "ctrl+alt+t"   # enable/disable listening
    debug_mode: bool = False

    # Runtime (not persisted)
    enabled: bool = True

    # ---------------- persistence ----------------
    @staticmethod
    def load(path: Optional[str] = None) -> "Settings":
        path = path or default_config_path()
        s = Settings()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            s._apply(raw)
        except FileNotFoundError:
            pass
        except (json.JSONDecodeError, OSError, TypeError, KeyError, ValueError):
            # corrupted config -> fall back to defaults, keep file for inspection
            pass
        return s

    def _apply(self, raw: Dict[str, Any]) -> None:
        allowed = {f for f in self.__dataclass_fields__}  # includes calibration/gestures
        for key, value in (raw or {}).items():
            if key not in allowed or key in ("enabled",):
                continue
            if key == "calibration" and isinstance(value, dict):
                known = set(asdict(self.calibration))
                self.calibration = CalibrationParams(
                    **{k: v for k, v in value.items() if k in known}
                )
            elif key == "gestures" and isinstance(value, list):
                gs = []
                for g in value:
                    if isinstance(g, dict) and g.get("tap_count") and g.get("action"):
                        act = str(g["action"])
                        if act in KNOWN_ACTIONS:
                            gs.append(GestureDef(
                                tap_count=int(g["tap_count"]),
                                action=act,
                                enabled=bool(g.get("enabled", True)),
                                max_interval_ms=int(g.get("max_interval_ms", 450)),
                            ))
                if gs:
                    self.gestures = gs
            elif hasattr(self, key):
                cur = getattr(self, key)
                if isinstance(cur, bool):
                    setattr(self, key, bool(value))
                elif isinstance(cur, int) and not isinstance(cur, bool):
                    setattr(self, key, int(value))
                elif isinstance(cur, float):
                    setattr(self, key, float(value))
                elif isinstance(cur, str):
                    setattr(self, key, str(value))

    def save(self, path: Optional[str] = None) -> None:
        path = path or default_config_path()
        d = asdict(self)
        d.pop("enabled", None)
        data: Dict[str, Any] = {}
        for key, value in d.items():
            if isinstance(value, dict) and "samples" in value:
                value = {**value, "samples": [round(v, 2) for v in value["samples"]]}
            data[key] = value
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # atomic-ish write: temp file then replace
        fd, tmp = tempfile.mkstemp(prefix="tc_", suffix=".json",
                                   dir=os.path.dirname(path) or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ---------------- derived helpers ----------------
    def threshold_dbfs(self) -> float:
        """Adaptive detection threshold: base + calibration refinement."""
        base = float(self.min_peak_dbfs)
        cal = self.calibration
        if cal.calibrated and cal.noise_floor_dbfs is not None:
            span = max(6.0, cal.tap_peak_dbfs - cal.noise_floor_dbfs)
            target = cal.noise_floor_dbfs + span * (1.0 - self._sens_frac() * 0.85)
            base = max(-60.0, min(0.0, target))
        return base

    def _sens_frac(self) -> float:
        return max(1, min(10, int(self.sensitivity))) / 10.0

    def execute_delay_s(self) -> float:
        return max(0.05, self.gesture_execute_delay_ms) / 1000.0


class SettingsLock:
    """Thin lock so GUI and worker do not race on settings access."""
    lock = threading.RLock()
