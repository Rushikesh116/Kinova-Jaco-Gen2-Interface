#!/usr/bin/env python3
"""
safety_panel.py
================
Always-visible safety sidebar panel.

Controls:
  • Emergency Stop button (big red)
  • Stop All Motion button
  • Speed Scaling slider (0–100%)
  • Enable / Disable arm toggle
  • E-stop status indicator
  • Motion timeout display
"""

import math
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSlider, QFrame, QCheckBox
)
from PyQt5.QtCore import Qt, pyqtSignal, pyqtSlot, QTimer
from PyQt5.QtGui import QFont, QColor


class SafetyPanel(QWidget):
    """
    Right-hand safety sidebar. Always visible regardless of active tab.
    Emits signals consumed by main_window → ROS bridge.
    """

    # ---- Signals ----
    estop_requested      = pyqtSignal(bool)   # True = activate estop
    stop_motion_requested = pyqtSignal()
    speed_scale_changed  = pyqtSignal(int)    # 0–100 %
    arm_enable_changed   = pyqtSignal(bool)   # True = enable

    # Default speed % on startup
    DEFAULT_SPEED = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self._estop_active   = False
        self._arm_enabled    = True
        self._build_ui()

        # Auto-clear status message after 3 s
        self._msg_timer = QTimer(self)
        self._msg_timer.setSingleShot(True)
        self._msg_timer.timeout.connect(lambda: self._status_lbl.setText(''))

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # ---- Section title ----
        title = QLabel('⚠ SAFETY')
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet('color: #ff6b6b; font-size: 14px; font-weight: bold; letter-spacing: 2px;')
        layout.addWidget(title)

        layout.addWidget(self._make_sep())

        # ---- Emergency Stop ----
        self._estop_btn = QPushButton('🛑  EMERGENCY\nSTOP')
        self._estop_btn.setFixedHeight(80)
        self._estop_btn.setStyleSheet(self._estop_style(False))
        self._estop_btn.setFont(QFont('', 12, QFont.Bold))
        self._estop_btn.clicked.connect(self._toggle_estop)
        layout.addWidget(self._estop_btn)

        # ---- Stop All Motion ----
        stop_btn = QPushButton('⏹  Stop All Motion')
        stop_btn.setFixedHeight(40)
        stop_btn.setStyleSheet('''
            QPushButton {
                background: #37474f; color: #fff; border-radius: 6px; font-size: 12px;
            }
            QPushButton:hover { background: #546e7a; }
            QPushButton:pressed { background: #263238; }
        ''')
        stop_btn.clicked.connect(self.stop_motion_requested.emit)
        layout.addWidget(stop_btn)

        layout.addWidget(self._make_sep())

        # ---- Speed Scaling ----
        spd_lbl = QLabel('Speed Scale')
        spd_lbl.setStyleSheet('color: #ccc; font-size: 12px;')
        layout.addWidget(spd_lbl)

        self._speed_slider = QSlider(Qt.Horizontal)
        self._speed_slider.setRange(0, 100)
        self._speed_slider.setValue(self.DEFAULT_SPEED)
        self._speed_slider.setStyleSheet('''
            QSlider::groove:horizontal { height: 6px; background: #333; border-radius: 3px; }
            QSlider::handle:horizontal { background: #64b5f6; width: 16px; height: 16px;
                                         margin: -5px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #1565c0; border-radius: 3px; }
        ''')
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        layout.addWidget(self._speed_slider)

        self._speed_val_lbl = QLabel(f'{self.DEFAULT_SPEED}%')
        self._speed_val_lbl.setAlignment(Qt.AlignCenter)
        self._speed_val_lbl.setStyleSheet('color: #a5d6a7; font-size: 13px; font-weight: bold;')
        layout.addWidget(self._speed_val_lbl)

        layout.addWidget(self._make_sep())

        # ---- Arm Enable Toggle ----
        self._enable_cb = QCheckBox('Arm Motion Enabled')
        self._enable_cb.setChecked(True)
        self._enable_cb.setStyleSheet('color: #ccc; font-size: 12px;')
        self._enable_cb.stateChanged.connect(self._on_enable_changed)
        layout.addWidget(self._enable_cb)

        layout.addStretch()

        # ---- Status message ----
        self._status_lbl = QLabel('')
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet('color: #ff8a65; font-size: 11px;')
        layout.addWidget(self._status_lbl)

        self.setStyleSheet('background: #1e1e2e; border-left: 1px solid #333;')
        self.setFixedWidth(180)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _toggle_estop(self):
        """Toggle emergency stop on/off."""
        self._estop_active = not self._estop_active
        self._estop_btn.setStyleSheet(self._estop_style(self._estop_active))
        if self._estop_active:
            self._estop_btn.setText('🟢  RESUME\n(Clear E-Stop)')
            self._set_status('⚠ E-Stop ACTIVE — arm halted')
        else:
            self._estop_btn.setText('🛑  EMERGENCY\nSTOP')
            self._set_status('E-Stop cleared')
        self.estop_requested.emit(self._estop_active)

    def _on_speed_changed(self, value: int):
        self._speed_val_lbl.setText(f'{value}%')
        self.speed_scale_changed.emit(value)

    def _on_enable_changed(self, state: int):
        enabled = (state == Qt.Checked)
        self._arm_enabled = enabled
        self.arm_enable_changed.emit(enabled)
        if not enabled:
            self._set_status('Arm motion DISABLED')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @pyqtSlot(bool)
    def set_estop(self, active: bool):
        """Programmatically update e-stop display (e.g. from joystick button)."""
        if active != self._estop_active:
            self._toggle_estop()

    def get_speed_scale(self) -> float:
        """Return current speed scale as 0.0 – 1.0."""
        return self._speed_slider.value() / 100.0

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)
        self._msg_timer.start(4000)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _estop_style(active: bool) -> str:
        if active:
            return '''
                QPushButton { background: #1b5e20; color: #a5d6a7;
                              border: 2px solid #388e3c; border-radius: 8px; }
                QPushButton:hover { background: #2e7d32; }
            '''
        return '''
            QPushButton { background: #b71c1c; color: #fff;
                          border: 2px solid #ff1744; border-radius: 8px; }
            QPushButton:hover { background: #c62828; }
            QPushButton:pressed { background: #7f0000; }
        '''

    @staticmethod
    def _make_sep():
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet('color: #333;')
        return sep
