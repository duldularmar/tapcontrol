"""Custom widgets: audio-reactive meter, threshold bar, gesture feedback."""
from __future__ import annotations

from collections import deque
from typing import Deque, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme


class LevelScope(QWidget):
    """Scrolling amplitude meter: recent dBFS levels + threshold + noise floor.

    Purely GUI-side: filled from a polling timer with level snapshots, so it
    never touches the audio threads directly.
    """

    def __init__(self, dark=True, parent=None):
        super().__init__(parent)
        self._c = theme.colors(dark)
        self.setMinimumHeight(150)
        self._levels: Deque[Optional[float]] = deque([None] * 240, maxlen=240)
        self._threshold = -40.0
        self._floor = -70.0
        self._flash_until = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._decay_flash)
        self._timer.start(60)

    def set_theme(self, dark: bool) -> None:
        self._c = theme.colors(dark)
        self.update()

    def push_level(self, dbfs: float) -> None:
        self._levels.append(float(dbfs))
        self.update()

    def set_reference(self, threshold: float, floor: float) -> None:
        self._threshold = threshold
        self._floor = floor

    def flash(self) -> None:
        self._flash_until = self._timer_remaining = None
        import time
        self._flash_until = time.monotonic() + 0.25
        self.update()

    def _decay_flash(self) -> None:
        import time
        if self._flash_until and time.monotonic() > self._flash_until:
            self._flash_until = None
            self.update()

    def paintEvent(self, ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._c["surface2"]))
        p.drawRoundedRect(QRectF(0, 0, w, h), 10, 10)

        top_db, bot_db = 0.0, -80.0
        def y(v: float) -> float:
            t = (float(v) - bot_db) / (top_db - bot_db)
            return (1.0 - t) * h

        # noise floor band
        p.setPen(QPen(QColor(self._c["text_dim"], ), 1, Qt.PenStyle.DashLine)
                 if False else QPen(QColor(120, 120, 120, 110), 1,
                                    Qt.PenStyle.DashLine))
        fy = y(self._floor)
        p.drawLine(QPointF(0, fy), QPointF(w, fy))

        # threshold line
        p.setPen(QPen(QColor(self._c["thresh"]), 2, Qt.PenStyle.DotLine))
        ty = y(self._threshold)
        p.drawLine(QPointF(0, ty), QPointF(w, ty))

        # level bars
        bar_w = max(2.0, w / len(self._levels))
        x = 0.0
        import time
        flashing = self._flash_until is not None and time.monotonic() < self._flash_until
        accent = QColor(self._c["meter"])
        if flashing:
            accent = accent.lighter(150)
        p.setBrush(accent)
        p.setPen(Qt.PenStyle.NoPen)
        for lvl in self._levels:
            if lvl is not None:
                yy = y(min(max(lvl, bot_db), top_db))
                p.drawRoundedRect(QRectF(x, yy, bar_w * 0.75, h - yy), 1, 1)
            x += bar_w
        p.end()
