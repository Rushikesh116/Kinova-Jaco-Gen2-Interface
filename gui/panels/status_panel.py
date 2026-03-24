#!/usr/bin/env python3
"""
status_panel.py
================
Arm status panel — always visible at the top of the main window.
Displays connection status, active control mode, error messages,
and current speed scale as colour-coded indicators.
"""

from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QFrame
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont


class StatusIndicator(QLabel):
    """A small coloured dot + label for binary status."""

    _COLOURS = {
        'green':  '#00e676',
        'red':    '#ff1744',
        'yellow': '#ffd600',
        'grey':   '#757575',
    }

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._label = label
        self.set_colour('grey')

    def set_colour(self, colour: str):
        c = self._COLOURS.get(colour, '#757575')
        self.setText(
            f'<span style="color:{c};">&#9679;</span>'
            f'&nbsp;<span style="color:#ccc;">{self._label}</span>'
        )
        self.setTextFormat(Qt.RichText)


class StatusPanel(QWidget):
    """
    Horizontal status bar shown at the top of the main window.
    Shows: arm connection, e-stop state, active mode, speed scale.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(24)

        font_bold = QFont()
        font_bold.setBold(True)

        # ---- Arm connection ----
        self._arm_indicator = StatusIndicator('Arm: DISCONNECTED')
        layout.addWidget(self._arm_indicator)

        self._sep1 = self._make_sep()
        layout.addWidget(self._sep1)

        # ---- E-stop state ----
        self._estop_indicator = StatusIndicator('E-Stop: INACTIVE')
        layout.addWidget(self._estop_indicator)

        self._sep2 = self._make_sep()
        layout.addWidget(self._sep2)

        # ---- Control mode ----
        lbl = QLabel('Mode:')
        lbl.setStyleSheet('color: #aaa; font-size: 12px;')
        layout.addWidget(lbl)

        self._mode_label = QLabel('—')
        self._mode_label.setFont(font_bold)
        self._mode_label.setStyleSheet('color: #64b5f6; font-size: 13px;')
        layout.addWidget(self._mode_label)

        self._sep3 = self._make_sep()
        layout.addWidget(self._sep3)

        # ---- Speed scale ----
        lbl2 = QLabel('Speed:')
        lbl2.setStyleSheet('color: #aaa; font-size: 12px;')
        layout.addWidget(lbl2)

        self._speed_label = QLabel('30%')
        self._speed_label.setFont(font_bold)
        self._speed_label.setStyleSheet('color: #a5d6a7; font-size: 13px;')
        layout.addWidget(self._speed_label)

        layout.addStretch()

        # ---- Message area (errors / status messages) ----
        self._msg_label = QLabel('')
        self._msg_label.setStyleSheet('color: #ff8a65; font-size: 12px;')
        layout.addWidget(self._msg_label)

        self.setStyleSheet('background: #1a1a2e; border-bottom: 1px solid #333;')

    @staticmethod
    def _make_sep():
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet('color: #444;')
        return sep

    # ------------------------------------------------------------------
    # Public update slots (called by main_window from bridge signals)
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def update_arm_state(self, state: dict):
        connected = state.get('connected', False)
        if connected:
            self._arm_indicator.set_colour('green')
            self._arm_indicator._label = 'Arm: CONNECTED'
            self._arm_indicator.set_colour('green')
        else:
            self._arm_indicator._label = 'Arm: DISCONNECTED'
            self._arm_indicator.set_colour('grey')

    @pyqtSlot(bool)
    def update_estop(self, active: bool):
        if active:
            self._estop_indicator._label = 'E-Stop: ACTIVE'
            self._estop_indicator.set_colour('red')
        else:
            self._estop_indicator._label = 'E-Stop: INACTIVE'
            self._estop_indicator.set_colour('green')

    @pyqtSlot(str)
    def update_mode(self, mode: str):
        self._mode_label.setText(mode)

    @pyqtSlot(int)
    def update_speed(self, percent: int):
        self._speed_label.setText(f'{percent}%')

    @pyqtSlot(str)
    def show_message(self, msg: str):
        self._msg_label.setText(msg)
