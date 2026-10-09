"""Gesture recognizer: groups tap events into gestures (1..N taps) and decides
when to execute. Executes only after the grouping timeout expires, so a single
tap does not conflict with a double tap."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from ..config.settings import GestureDef, Settings


@dataclass
class GestureResult:
    tap_count: int
    action: str
    taps: List[float] = field(default_factory=list)
    at: float = 0.0


class GestureError(Exception):
    pass


class GestureRecognizer:
    """Accumulates TapEvents with timestamps and emits GestureResults.

    Timing model:
      - taps closer together than `max_interval_ms` belong to the same gesture;
      - a gap bigger than that closes the gesture;
      - execution happens only after `execute_delay_ms` of silence from the
        last tap (single tap waits before firing so "2" can still arrive).
    """

    def __init__(self, gestures: List[GestureDef],
                 execute_delay_ms: int = 420):
        self.gestures = {int(g.tap_count): g for g in gestures}
        self.execute_delay_s = max(0.05, execute_delay_ms) / 1000.0
        self._pending: List[float] = []   # tap timestamps (monotonic)
        self._cooldown_until = 0.0
        self._pending_count = 0

    # ------------------------------------------------------------------
    def configure(self, gestures: List[GestureDef],
                  execute_delay_ms: int) -> None:
        self.gestures = {int(g.tap_count): g for g in gestures}
        self.execute_delay_s = max(0.05, execute_delay_ms) / 1000.0

    def reset(self) -> None:
        self._pending.clear()
        self._pending_count = 0

    def start_cooldown(self, ms: int) -> None:
        self._cooldown_until = time.monotonic() + max(0, ms) / 1000.0

    def in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    # ------------------------------------------------------------------
    def add_tap(self, ts: Optional[float] = None) -> Optional[GestureResult]:
        """Register a tap. Returns a GestureResult when the pending gesture
        has timed out and should be executed (including when a new tap stays
        ungrouped because the previous gesture just closed)."""
        now = ts if ts is not None else time.monotonic()
        result: Optional[GestureResult] = None

        if self._pending:
            gap_ms = (now - self._pending[-1]) * 1000.0
            max_gap = self._current_max_gap_ms()
            if gap_ms > max_gap:
                # previous gesture is closed by the gap itself
                result = self._finalize(now)
        self._pending.append(now)
        self._pending_count += 1
        return result

    def check_timeout(self, now: Optional[float] = None) -> Optional[GestureResult]:
        """Called periodically (and after each tap): if the execute delay after
        the last tap has elapsed, finalize the pending gesture.

        Two conditions end the pending gesture:
        - since the last tap we waited at least the *next tap's* max interval
          (gap can no longer become a multi-tap gesture), AND
        - at least the execute delay elapsed (short delay so responsivity is
          bounded, but a single tap still waits for a possible double tap).
        """
        now = now if now is not None else time.monotonic()
        if not self._pending:
            return None
        since_last_ms = (now - self._pending[-1]) * 1000.0
        max_gap = self._next_tap_gap_ms()
        delay_ms = self.execute_delay_s * 1000.0
        wait_ms = max(max_gap, min(delay_ms, 2.0 * max_gap))
        if since_last_ms >= wait_ms:
            return self._finalize(now)
        return None

    # ------------------------------------------------------------------
    def _current_max_gap_ms(self) -> float:
        if not self._pending:
            return 0.0
        gd = self.gestures.get(len(self._pending))
        if gd is None:
            gd = self.gestures.get(1)
        return float(gd.max_interval_ms if gd is not None else 450.0)

    def _next_tap_gap_ms(self) -> float:
        """Max gap allowed between the LAST tap and a hypothetical NEXT tap
        (i.e. joining the gesture one tap later)."""
        if not self._pending:
            return 0.0
        gd = self.gestures.get(len(self._pending) + 1)
        if gd is None:
            gd = self.gestures.get(len(self._pending)) or self.gestures.get(1)
        return float(gd.max_interval_ms if gd is not None else 450.0)

    def _finalize(self, now: float) -> Optional[GestureResult]:
        count = len(self._pending)
        self._pending.clear()
        if self.in_cooldown():
            self._pending_count = 0
            return None
        gd = self.gestures.get(count)
        if gd is None or not gd.enabled:
            self._pending_count = 0
            return None     # gesture not configured/enabled for this count
        self.start_cooldown_from_settings()
        self._pending_count = 0
        return GestureResult(tap_count=count, action=gd.action,
                             taps=[now], at=now)

    # Cooldown uses the shared Settings value passed at configure time.
    cooldown_ms: int = 700

    def start_cooldown_from_settings(self) -> None:
        self._cooldown_until = time.monotonic() + self.cooldown_ms / 1000.0


def group_taps(taps_ms: List[float], max_gap_ms: float) -> List[List[float]]:
    """Pure helper used by tests: split sorted tap times (ms) into gestures."""
    groups: List[List[float]] = []
    cur: List[float] = []
    for t in taps_ms:
        if cur and (t - cur[-1]) > max_gap_ms:
            groups.append(cur)
            cur = []
        cur.append(t)
    if cur:
        groups.append(cur)
    return groups


def resolve_gesture(count: int, gestures: List[GestureDef],
                    enabled_only: bool = True) -> Optional[GestureDef]:
    for g in gestures:
        if g.tap_count == count and (g.enabled or not enabled_only):
            return g
    return None
