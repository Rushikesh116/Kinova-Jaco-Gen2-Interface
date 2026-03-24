#!/usr/bin/env python3
"""
joystick_panel.py
==================
Tab panel showing live joystick state and allowing axis/button remapping.

Features:
  • Live axis bar graphs (QProgressBar for each axis)
  • Button state indicators (coloured squares)
  • Connection status indicator
  • Axis-to-action remapping via dropdowns
  • Raw /joy topic data display
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QGroupBox, QProgressBar, QComboBox, QFrame, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSlot
from PyQt5.QtGui import QFont


# Action labels for remapping dropdowns
ACTIONS = [
    '— None —',
    'Cartesian X+', 'Cartesian X-',
    'Cartesian Y+', 'Cartesian Y-',
    'Cartesian Z+', 'Cartesian Z-',
    'Roll+', 'Roll-', 'Pitch+', 'Pitch-', 'Yaw+', 'Yaw-',
    'Joint 1', 'Joint 2', 'Joint 3', 'Joint 4', 'Joint 5', 'Joint 6',
    'Open Gripper', 'Close Gripper',
    'Emergency Stop', 'Home Arm',
]

BUTTON_LABELS_XBOX = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'Back', 'Start', 'L3', 'R3']


class AxisBar(QWidget):
    """One axis: label + dual-direction progress bar + numeric value."""

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._idx = index
        name_lbl = QLabel(f'Axis {index}:')
        name_lbl.setFixedWidth(50)
        name_lbl.setStyleSheet('color: #aaa; font-size: 11px;')
        layout.addWidget(name_lbl)

        # Negative side bar
        self._neg_bar = QProgressBar()
        self._neg_bar.setRange(0, 100)
        self._neg_bar.setValue(0)
        self._neg_bar.setTextVisible(False)
        self._neg_bar.setFixedHeight(10)
        self._neg_bar.setInvertedAppearance(True)  # grows left
        self._neg_bar.setStyleSheet('''
            QProgressBar { background: #1a1a2e; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #ef5350; border-radius: 3px; }
        ''')
        layout.addWidget(self._neg_bar, stretch=1)

        center = QLabel('0')
        center.setFixedWidth(8)
        center.setAlignment(Qt.AlignCenter)
        center.setStyleSheet('color: #555;')
        layout.addWidget(center)

        # Positive side bar
        self._pos_bar = QProgressBar()
        self._pos_bar.setRange(0, 100)
        self._pos_bar.setValue(0)
        self._pos_bar.setTextVisible(False)
        self._pos_bar.setFixedHeight(10)
        self._pos_bar.setStyleSheet('''
            QProgressBar { background: #1a1a2e; border: none; border-radius: 3px; }
            QProgressBar::chunk { background: #42a5f5; border-radius: 3px; }
        ''')
        layout.addWidget(self._pos_bar, stretch=1)

        self._val_lbl = QLabel('+0.00')
        self._val_lbl.setFixedWidth(48)
        self._val_lbl.setAlignment(Qt.AlignRight)
        self._val_lbl.setStyleSheet('color: #80cbc4; font-size: 11px; font-family: monospace;')
        layout.addWidget(self._val_lbl)

    def set_value(self, v: float):
        pct = min(100, int(abs(v) * 100))
        if v >= 0:
            self._pos_bar.setValue(pct)
            self._neg_bar.setValue(0)
        else:
            self._pos_bar.setValue(0)
            self._neg_bar.setValue(pct)
        self._val_lbl.setText(f'{v:+.2f}')


class JoystickPanel(QWidget):
    """Live joystick display and remapping panel."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._axis_bars:   list[AxisBar]  = []
        self._btn_labels:  list[QLabel]   = []
        self._connected    = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ---- Header ----
        hdr = QLabel('🎮  Joystick Monitor & Remapping')
        hdr.setStyleSheet('color: #ffcc80; font-size: 16px; font-weight: bold;')
        layout.addWidget(hdr)

        # ---- Connection status ----
        status_row = QHBoxLayout()
        conn_lbl = QLabel('Controller:')
        conn_lbl.setStyleSheet('color: #aaa; font-size: 12px;')
        status_row.addWidget(conn_lbl)
        self._conn_indicator = QLabel('⬤  NOT CONNECTED')
        self._conn_indicator.setStyleSheet('color: #ef5350; font-size: 12px; font-weight: bold;')
        status_row.addWidget(self._conn_indicator)
        status_row.addStretch()
        layout.addLayout(status_row)

        # ---- Two columns: Axes | Buttons ----
        cols = QHBoxLayout()
        cols.setSpacing(12)

        # Axes group
        axes_group = QGroupBox('Axes (live)')
        axes_group.setStyleSheet(self._group_style())
        axes_layout = QVBoxLayout(axes_group)
        axes_layout.setSpacing(4)
        for i in range(8):   # support up to 8 axes
            bar = AxisBar(i)
            self._axis_bars.append(bar)
            axes_layout.addWidget(bar)
        cols.addWidget(axes_group, stretch=2)

        # Buttons group
        btns_group = QGroupBox('Buttons (live)')
        btns_group.setStyleSheet(self._group_style())
        btns_layout = QGridLayout(btns_group)
        btns_layout.setSpacing(4)
        for i in range(12):
            lbl_text = BUTTON_LABELS_XBOX[i] if i < len(BUTTON_LABELS_XBOX) else f'Btn{i}'
            lbl = QLabel(lbl_text)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(40, 30)
            lbl.setStyleSheet(self._btn_inactive_style())
            self._btn_labels.append(lbl)
            btns_layout.addWidget(lbl, i // 3, i % 3)
        cols.addWidget(btns_group, stretch=1)
        layout.addLayout(cols)

        # ---- Remapping section ----
        layout.addWidget(self._build_remap_group())
        layout.addStretch()

    def _build_remap_group(self) -> QGroupBox:
        """Axis-to-action remapping dropdowns."""
        group = QGroupBox('Axis Remapping (effective on next launch)')
        group.setStyleSheet(self._group_style())
        grid = QGridLayout(group)

        grid.addWidget(self._hdr('Axis'), 0, 0)
        grid.addWidget(self._hdr('Assigned Action'), 0, 1)

        default_actions = [
            'Cartesian X+', 'Cartesian Y+', 'Roll+',
            'Yaw+', 'Cartesian Z+', 'Pitch+'
        ]

        self._remap_combos = []
        for i in range(6):
            grid.addWidget(QLabel(f'Axis {i}'), i + 1, 0)
            combo = QComboBox()
            combo.addItems(ACTIONS)
            if i < len(default_actions):
                idx = ACTIONS.index(default_actions[i]) if default_actions[i] in ACTIONS else 0
                combo.setCurrentIndex(idx)
            combo.setStyleSheet('background: #1a1a2e; color: #ccc; border: 1px solid #444;')
            grid.addWidget(combo, i + 1, 1)
            self._remap_combos.append(combo)

        return group

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def update_joy(self, joy: dict):
        """Update live display from processed joystick dict."""
        if not self._connected:
            self._connected = True
            self._conn_indicator.setText('⬤  CONNECTED')
            self._conn_indicator.setStyleSheet(
                'color: #a5d6a7; font-size: 12px; font-weight: bold;')

        axes    = joy.get('axes', [])
        buttons = joy.get('buttons', [])

        for i, bar in enumerate(self._axis_bars):
            bar.set_value(axes[i] if i < len(axes) else 0.0)

        for i, lbl in enumerate(self._btn_labels):
            pressed = bool(buttons[i]) if i < len(buttons) else False
            lbl.setStyleSheet(
                self._btn_active_style() if pressed else self._btn_inactive_style()
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_style() -> str:
        return '''
            QGroupBox { color: #ccc; border: 1px solid #444; border-radius: 6px;
                        margin-top: 8px; font-size: 13px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        '''

    @staticmethod
    def _btn_inactive_style() -> str:
        return ('QLabel { background: #1a1a2e; color: #555; border: 1px solid #333; '
                'border-radius: 4px; font-size: 11px; }')

    @staticmethod
    def _btn_active_style() -> str:
        return ('QLabel { background: #1565c0; color: #fff; border: 1px solid #42a5f5; '
                'border-radius: 4px; font-size: 11px; font-weight: bold; }')

    @staticmethod
    def _hdr(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet('color: #888; font-size: 11px;')
        return lbl
