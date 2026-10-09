"""TapControl — simple, stable single-window UI.

One page, no tabs: big Start/Stop button, live meter, mic selector,
calibration, gesture toggles, sensitivity, tiny event history, tray + hotkey.
All pipeline logic unchanged from the verified implementation.
"""
from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMenu, QPushButton, QSlider,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ..actions import win_actions
from ..config.settings import Settings
from ..core.calibration import CalibrationSession
from ..core.pipeline import TapPipeline
from ..audio.capture import rms_to_dbfs
from . import theme
from .panels import LevelScope

COLORS = theme.DARK_C


class GestureRow(QWidget):
    """Compact one-line gesture: checkbox + count label + action combo."""
    changed = Signal()

    def __init__(self, tap_count: int, action: str, enabled: bool,
                 actions_list: List[str], parent=None):
        super().__init__(parent)
        self.tap_count = tap_count
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 1, 4, 1)
        lay.setSpacing(8)
        self.chk = QCheckBox()
        self.chk.setChecked(enabled)
        self.chk.toggled.connect(self.changed)
        self.lbl = QLabel(f"{tap_count} tap{'s' if tap_count > 1 else ''}")
        self.lbl.setFixedWidth(70)
        self.combo = QComboBox()
        for aid in actions_list:
            self.combo.addItem(win_actions.describe(aid), aid)
        idx = self.combo.findData(action)
        self.combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo.currentIndexChanged.connect(self.changed)
        lay.addWidget(self.chk)
        lay.addWidget(self.lbl)
        lay.addWidget(self.combo, 1)

    def values(self):
        return self.chk.isChecked(), self.combo.currentData()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.pipeline = TapPipeline(
            settings_getter=lambda: self.settings,
            on_tap=self._on_tap_detected,
            on_gesture=self._on_gesture_executed,
            on_error=self._on_pipeline_error,
        )
        self.calibration: Optional[CalibrationSession] = None
        self._cal_timer: Optional[QTimer] = None
        self._last_tap_ui: Optional[float] = None
        self._updating = False

        self.setWindowTitle("TapControl")
        self.setFixedSize(560, 680)          # fixed size = stable layout
        self._build_ui()
        self._build_tray()
        self._build_hotkey()

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_pipeline)
        self._poll.start(60)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(10)

        # Header: title + status pill
        head = QHBoxLayout()
        t = QLabel("TapControl")
        t.setStyleSheet(f"font-size:18px; font-weight:700; color:{COLORS['text']};")
        head.addWidget(t)
        head.addStretch(1)
        self.status_pill = QLabel("Idle")
        self._set_status_pill("Idle", "#8a8f98")
        head.addWidget(self.status_pill)
        root.addLayout(head)

        # Big Start/Stop button
        self.big_btn = QPushButton("Start Listening")
        self.big_btn.setObjectName("bigButton")
        self.big_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.big_btn.clicked.connect(self.toggle_listening)
        root.addWidget(self.big_btn)

        # Feedback line (last gesture)
        self.feedback = QLabel("Ready. Calibrate first for best results.")
        self.feedback.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.feedback.setStyleSheet(
            f"font-size:15px; font-weight:600; color:{COLORS['text']};")
        self.feedback.setFixedHeight(24)
        root.addWidget(self.feedback)

        # Level meter card
        card = QFrame()
        card.setStyleSheet(self._card_css())
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 6, 8, 6)
        self.scope = LevelScope(dark=self.settings.theme == "dark")
        self.scope.setMinimumHeight(120)
        cl.addWidget(self.scope)
        info = QHBoxLayout()
        self.lbl_level = QLabel("Level: --")
        self.lbl_floor = QLabel("Floor: --")
        self.lbl_thresh = QLabel("Threshold: --")
        for l in (self.lbl_level, self.lbl_floor, self.lbl_thresh):
            l.setStyleSheet(f"color:{COLORS['text_dim']}; font-size:11px;")
        info.addWidget(self.lbl_level)
        info.addStretch(1)
        info.addWidget(self.lbl_floor)
        info.addStretch(1)
        info.addWidget(self.lbl_thresh)
        cl.addLayout(info)
        root.addWidget(card, 1)

        # Mic + calibration row
        row = QHBoxLayout()
        self.device_combo = QComboBox()
        self._refresh_devices()
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        cal_btn = QPushButton("Calibrate")
        cal_btn.clicked.connect(self.start_calibration)
        row.addWidget(QLabel("Mic:"))
        row.addWidget(self.device_combo, 1)
        row.addWidget(cal_btn)
        root.addLayout(row)

        # Sensitivity slider row
        srow = QHBoxLayout()
        srow.addWidget(QLabel("Sensitivity"))
        self.sens = QSlider(Qt.Orientation.Horizontal)
        self.sens.setRange(1, 10)
        self.sens.setValue(self.settings.sensitivity)
        self.sens.valueChanged.connect(self._on_sensitivity)
        self.sens_val = QLabel(str(self.settings.sensitivity))
        self.sens_val.setFixedWidth(20)
        srow.addWidget(self.sens, 1)
        srow.addWidget(self.sens_val)
        root.addLayout(srow)

        # Gestures card (compact list)
        gcard = QFrame()
        gcard.setStyleSheet(self._card_css())
        gl = QVBoxLayout(gcard)
        gl.setContentsMargins(8, 6, 8, 6)
        gl.setSpacing(0)
        from ..config.settings import KNOWN_ACTIONS
        self.gesture_rows: List[GestureRow] = []
        existing = {g.tap_count: g for g in self.settings.gestures}
        for count in range(1, 6):        # just the five main gestures
            g = existing.get(count)
            r = GestureRow(count, g.action if g else "play_pause",
                           bool(g and g.enabled), list(KNOWN_ACTIONS))
            r.changed.connect(self._gestures_changed)
            gl.addWidget(r)
            self.gesture_rows.append(r)
        root.addWidget(gcard)

        # History (small)
        self.history = QListWidget()
        self.history.setFixedHeight(96)
        root.addWidget(self.history, 1)

        # Options row
        opts = QHBoxLayout()
        theme_combo = QComboBox()
        theme_combo.addItems(["dark", "light"])
        theme_combo.setCurrentText(self.settings.theme)
        theme_combo.currentTextChanged.connect(self._on_theme_changed)
        opts.addWidget(QLabel("Theme:"))
        opts.addWidget(theme_combo)
        opts.addStretch(1)
        self.chk_debug = QCheckBox("Debug info")
        self.chk_debug.setChecked(self.settings.debug_mode)
        self.chk_debug.toggled.connect(self._on_debug_toggled)
        opts.addWidget(self.chk_debug)
        root.addLayout(opts)

    def _card_css(self) -> str:
        return (f"QFrame{{background:{COLORS['card']};"
                f"border:1px solid {COLORS['border']};border-radius:10px;}}")

    # ---------------------------------------------------------------- tray
    def _build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        toggle = QAction("Start/Stop listening", menu)
        toggle.triggered.connect(self.toggle_listening)
        show = QAction("Show window", menu)
        show.triggered.connect(self.show_normal)
        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.real_quit)
        menu.addAction(toggle)
        menu.addSeparator()
        menu.addAction(show)
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("TapControl")
        self.tray.activated.connect(
            lambda r: self.show_normal()
            if r == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    # ---------------------------------------------------------------- hotkey
    def _build_hotkey(self):
        self.hotkey = QShortcut(QKeySequence(self.settings.global_hotkey), self)
        self.hotkey.activated.connect(self.toggle_listening)

    # ---------------------------------------------------------------- actions
    def toggle_listening(self):
        if self.calibration:
            self._abort_calibration()
        if self.pipeline.is_running():
            self.pipeline.stop()
            self.big_btn.setText("Start Listening")
            self._set_status_pill("Idle", "#8a8f98")
            self.feedback.setText("Stopped.")
        else:
            if self.pipeline.start():
                self.big_btn.setText("Stop Listening")
                self._set_status_pill("Listening", COLORS["ok"])
                self.feedback.setText("Listening for taps…")
            else:
                self._set_status_pill("Mic error", COLORS["danger"])
                self.feedback.setText("Could not open the microphone.")

    def start_calibration(self):
        if not self.pipeline.is_running():
            if not self.pipeline.start():
                self.feedback.setText("Microphone error — cannot calibrate.")
                self._set_status_pill("Mic error", COLORS["danger"])
                return
            self.big_btn.setText("Stop Listening")
        self.pipeline.set_calibration_mode(True)
        self.calibration = CalibrationSession(
            self.settings,
            level_feed=lambda: (self.pipeline.snapshot().level_rms,
                                self.pipeline.snapshot().level_peak),
            tap_feed=self._pipeline_taps)
        self.feedback.setText(self.calibration.start())
        self._set_status_pill("Calibrating", "#b36b00")
        self._cal_timer = QTimer(self)
        self._cal_timer.timeout.connect(self._calibration_poll)
        self._cal_timer.start(80)

    def _pipeline_taps(self) -> List[float]:
        return self.pipeline.drain_calibration_taps()

    def _calibration_poll(self):
        if not self.calibration:
            return
        msg = self.calibration.update()
        if msg:
            self.feedback.setText(msg)
        if self.calibration and self.calibration.phase == "done":
            self.pipeline.set_calibration_mode(False)
            self.pipeline.apply_settings()
            self._cal_timer.stop()
            self.feedback.setText("Calibration complete ✓")
            self._set_status_pill("Listening", COLORS["ok"])
            self.save_settings()
            self.calibration = None

    def _abort_calibration(self):
        if self._cal_timer:
            self._cal_timer.stop()
            self._cal_timer = None
        self.pipeline.set_calibration_mode(False)
        self.calibration = None

    # ---------------------------------------------------------------- slots
    def _poll_pipeline(self):
        snap = self.pipeline.snapshot()
        db = rms_to_dbfs(snap.level_rms) if snap.running else -80.0
        self.scope.push_level(db)
        self.scope.set_reference(snap.threshold_dbfs, snap.noise_floor_dbfs)
        self.lbl_level.setText(f"Level: {db:.0f} dB")
        self.lbl_floor.setText(f"Floor: {snap.noise_floor_dbfs:.0f}")
        self.lbl_thresh.setText(f"Thresh: {snap.threshold_dbfs:.0f}")
        if self.chk_debug.isChecked() and snap.running:
            msg = (f"DBG taps={snap.taps_detected} gestures="
                   f"{snap.gestures_executed} dropped={snap.dropped_blocks} "
                   f"peaks={self.pipeline.debug_peaks()[-6:]}")
            self.statusBar().showMessage(msg)
        elif snap.running:
            self.statusBar().clearMessage()

    def _on_tap_detected(self, peak: float):
        from PySide6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(self, "_ui_tap",
                                 Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(float, float(peak)))

    def _on_gesture_executed(self, result, ok: bool):
        from PySide6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(
            self, "_ui_gesture", Qt.ConnectionType.QueuedConnection,
            Q_ARG(int, int(result.tap_count)),
            Q_ARG(str, str(result.action)),
            Q_ARG(bool, bool(ok)))

    def _on_pipeline_error(self, msg: str):
        from PySide6.QtCore import QMetaObject, Q_ARG
        QMetaObject.invokeMethod(self, "_ui_error",
                                 Qt.ConnectionType.QueuedConnection,
                                 Q_ARG(str, msg))

    # UI-thread slots
    def _ui_tap(self, peak: float):
        self.scope.flash()
        self._last_tap_ui = time.monotonic()

    def _ui_gesture(self, count: int, action: str, ok: bool):
        name = win_actions.describe(action)
        mark = "✓" if ok else "✗"
        self.feedback.setText(f"{mark} {count} taps → {name}")
        self.history.insertItem(
            0, QListWidgetItem(
                f"{time.strftime('%H:%M:%S')}  {count} taps → {name} {mark}"))
        while self.history.count() > 100:
            self.history.takeItem(self.history.count() - 1)

    def _ui_error(self, msg: str):
        self.statusBar().showMessage(msg, 8000)
        self._set_status_pill("Error", COLORS["danger"])

    # ---------------------------------------------------------------- config
    def _gestures_changed(self):
        if self._updating:
            return
        from ..config.settings import GestureDef
        gestures = []
        for row in self.gesture_rows:
            enabled, action = row.values()
            if enabled and action:
                gestures.append(GestureDef(tap_count=row.tap_count,
                                           action=action, enabled=True))
        if gestures:
            self.settings.gestures = gestures
            self.pipeline.apply_settings()
            self.save_settings()

    def _refresh_devices(self):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItem("System default", None)
        for d in self.pipeline._mic.list_input_devices():
            if not d["default"]:
                self.device_combo.addItem(d["name"], d["index"])
        if self.settings.device is not None:
            idx = self.device_combo.findData(self.settings.device)
            if idx >= 0:
                self.device_combo.setCurrentIndex(idx)
        self.device_combo.blockSignals(False)

    def _on_device_changed(self, idx: int):
        if self._updating or idx < 0:
            return
        self.settings.device = self.device_combo.itemData(idx)
        self.save_settings()
        if self.pipeline.is_running():      # restart on new device
            self.pipeline.stop()
            self.toggle_listening()

    def _on_sensitivity(self, v: int):
        self.sens_val.setText(str(v))
        self.settings.sensitivity = v
        self.pipeline.apply_settings()
        self.save_settings()

    def _on_theme_changed(self, name: str):
        self.settings.theme = name
        self.save_settings()

    def _on_debug_toggled(self, on: bool):
        self.settings.debug_mode = on
        self.pipeline.debug_mode = on
        self.save_settings()

    # ---------------------------------------------------------------- misc
    def _set_status_pill(self, text: str, color: str):
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(
            f"padding:3px 12px; border-radius:10px; font-weight:600;"
            f" background:{color}33; color:{color};")

    def show_normal(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, ev):
        ev.ignore()
        self.hide()
        self.tray.showMessage("TapControl",
                              "Still listening in the tray.",
                              QSystemTrayIcon.MessageIcon.Information, 2000)

    def real_quit(self):
        self._abort_calibration()
        self.pipeline.stop()
        self.save_settings()
        self.tray.hide()
        QApplication.quit()

    def save_settings(self):
        try:
            self.settings.save()
        except Exception:
            pass
