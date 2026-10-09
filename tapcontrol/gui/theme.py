"""Windows 11-inspired theme: dark/light stylesheets with rounded surfaces."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

DARK_C = {
    "bg": "#202124", "surface": "#2a2b2f", "surface2": "#323438",
    "card": "#2b2c31", "text": "#e8eaed", "text_dim": "#9aa0a6",
    "accent": "#8ab4f8", "accent_dark": "#6690e0", "danger": "#f28b82",
    "ok": "#81c995", "border": "#3c4043", "meter": "#8ab4f8",
    "thresh": "#f28b82", "wave": "#a8c7fa",
}

LIGHT_C = {
    "bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#eef0f3",
    "card": "#ffffff", "text": "#202124", "text_dim": "#5f6368",
    "accent": "#1a73e8", "accent_dark": "#1557b0", "danger": "#d93025",
    "ok": "#188038", "border": "#dadce0", "meter": "#1a73e8",
    "thresh": "#d93025", "wave": "#1a73e8",
}

FAMILY = '"Segoe UI Variable Display", "Segoe UI", sans-serif'


def build_stylesheet(dark: bool) -> str:
    c = DARK_C if dark else LIGHT_C
    return f"""
* {{ font-family: {FAMILY}; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}

QLabel {{ color: {c['text']}; }}
QLabel.dim {{ color: {c['text_dim']}; font-size: 12px; }}
QLabel.h1 {{ font-size: 22px; font-weight: 600; }}
QLabel.h2 {{ font-size: 15px; font-weight: 600; }}

QFrame.card {{
  background: {c['card']};
  border: 1px solid {c['border']};
  border-radius: 12px;
}}
QFrame.card QFrame {{ background: transparent; }}

QPushButton {{
  background: {c['surface']};
  border: 1px solid {c['border']};
  border-radius: 8px;
  padding: 8px 16px;
}}
QPushButton:hover {{ background: {c['surface2']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:disabled {{ color: {c['text_dim']}; }}

QPushButton#bigButton {{
  background: {c['accent']}; color: #ffffff;
  font-size: 16px; font-weight: 600; padding: 16px 28px; border: none;
  border-radius: 10px;
}}
QPushButton#bigButton:hover {{ background: {c['accent_dark']}; }}
QPushButton#bigButtonlistening {{
  background: {c['surface']}; color: {c['text']};
}}
QPushButton#bigButtonlistening:hover {{ background: {c['surface2']}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
  background: {c['surface']};
  border: 1px solid {c['border']};
  border-radius: 6px;
  padding: 5px 8px;
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
  background: {c['surface']};
  border: 1px solid {c['border']};
  selection-background-color: {c['accent']};
}}

QSlider::groove:horizontal {{
  height: 4px; background: {c['border']}; border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
  background: {c['accent']}; border-radius: 2px;
}}
QSlider::handle:horizontal {{
  width: 16px; height: 16px; margin: -7px 0;
  border-radius: 8px; background: {c['accent']};
  border: 2px solid {c['bg']};
}}
QSlider::handle:horizontal:hover {{ background: {c['accent_dark']}; }}

QCheckBox::indicator {{
  width: 18px; height: 18px; border-radius: 4px;
  border: 1px solid {c['border']}; background: {c['surface']};
}}
QCheckBox::indicator:checked {{
  background: {c['accent']}; border-color: {c['accent']};
}}

QProgressBar {{
  background: {c['surface']}; border: none; border-radius: 4px;
  height: 8px; text-align: center;
}}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}

QListWidget {{
  background: {c['card']}; border: 1px solid {c['border']};
  border-radius: 8px; padding: 4px;
}}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {c['surface2']}; }}

QTabWidget::pane {{
  border: 1px solid {c['border']}; border-radius: 10px;
  background: {c['card']}; top: -1px;
}}
QTabBar::tab {{
  background: transparent; color: {c['text_dim']};
  padding: 8px 18px; margin-right: 2px;
  border-top-left-radius: 8px; border-top-right-radius: 8px;
}}
QTabBar::tab:selected {{
  background: {c['card']}; color: {c['text']};
  border: 1px solid {c['border']}; border-bottom: none;
}}

QStatusBar {{
  background: {c['card']}; color: {c['text_dim']};
  border-top: 1px solid {c['border']};
}}
QToolTip {{
  background: {c['surface']}; color: {c['text']};
  border: 1px solid {c['border']}; padding: 4px;
}}
QScrollArea {{ border: none; background: transparent; }}
QMenuBar {{ background: {c['bg']}; }}
QMenuBar::item:selected {{ background: {c['surface']}; }}
QMenu {{
  background: {c['surface']}; border: 1px solid {c['border']};
  border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 6px 24px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['surface2']}; }}
"""


def apply_theme(app: QApplication, dark: bool) -> None:
    app.setStyleSheet(build_stylesheet(dark))
    if not dark:
        app.setPalette(QPalette())   # default light
    else:
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor(DARK_C["bg"]))
        pal.setColor(QPalette.WindowText, QColor(DARK_C["text"]))
        pal.setColor(QPalette.Base, QColor(DARK_C["card"]))
        pal.setColor(QPalette.Text, QColor(DARK_C["text"]))
        pal.setColor(QPalette.Button, QColor(DARK_C["surface"]))
        pal.setColor(QPalette.ButtonText, QColor(DARK_C["text"]))
        pal.setColor(QPalette.Highlight, QColor(DARK_C["accent"]))
        app.setPalette(pal)


def colors(dark: bool) -> dict:
    return DARK_C if dark else LIGHT_C
