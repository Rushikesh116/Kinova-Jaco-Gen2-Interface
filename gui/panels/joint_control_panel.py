#!/usr/bin/env python3
"""
joint_control_panel.py — Joint Control tab (pure Python / KinovaBridge version)
Joint angles displayed, +/- buttons held to drive velocity, joystick sticks via KinovaBridge.
"""
import math
from PyQt5.QtWidgets import (
    QWidget, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QGroupBox
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer

# Axis indices on SHANWAN Android Gamepad
_AX_LS_X = 0   # Left  stick  left/right
_AX_LS_Y = 1   # Left  stick  up/down
_AX_RS_X = 2   # Right stick  left/right
_AX_RS_Y = 3   # Right stick  up/down
_AX_L2   = 4   # L2 trigger  (-1=released, +1=fully pressed)
_AX_R2   = 5   # R2 trigger  (-1=released, +1=fully pressed)
_BTN_BACK_J5 = 6   # Back button -> maps to J5+
_BTN_START_J6 = 7  # Start button -> maps to J6+

MAX_SPEED_DPS = 60.0   # deg/s at 100% speed -- bridge applies speed-scale on top

JOINT_NAMES  = ['Joint 1', 'Joint 2', 'Joint 3', 'Joint 4', 'Joint 5', 'Joint 6']
JOINT_LIMITS = [(-180, 180), (47, 313), (19, 341), (-180, 180), (-180, 180), (-180, 180)]



class JointRow(QWidget):
    def __init__(self, index, limits, parent=None):
        super().__init__(parent)
        self._index   = index
        self._limits  = limits
        self._current = 0.0
        lo, hi = limits

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        name = QLabel(JOINT_NAMES[index])
        name.setFixedWidth(60)
        name.setStyleSheet('color:#aaa;font-size:12px;')
        layout.addWidget(name)

        self._minus = self._btn('−')
        layout.addWidget(self._minus)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(int(lo*100), int(hi*100))
        self._slider.setValue(0)
        self._slider.setEnabled(False)   # display-only, arm feedback drives it
        self._slider.setStyleSheet('''
            QSlider::groove:horizontal{height:6px;background:#333;border-radius:3px;}
            QSlider::handle:horizontal{background:#42a5f5;width:14px;height:14px;
                margin:-4px 0;border-radius:7px;}
            QSlider::sub-page:horizontal{background:#1565c0;border-radius:3px;}''')
        layout.addWidget(self._slider, stretch=1)

        self._plus = self._btn('+')
        layout.addWidget(self._plus)

        self._lbl = QLabel('  0.0°')
        self._lbl.setFixedWidth(62)
        self._lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._lbl.setStyleSheet('color:#80cbc4;font-size:12px;font-weight:bold;')
        layout.addWidget(self._lbl)

    def _btn(self, text):
        b = QPushButton(text)
        b.setFixedSize(28, 28)
        b.setAutoRepeat(False)
        b.setStyleSheet('QPushButton{background:#263238;color:#fff;border-radius:4px;font-size:14px;}'
                        'QPushButton:hover{background:#37474f;}'
                        'QPushButton:pressed{background:#1565c0;}')
        return b

    def set_feedback(self, deg):
        self._current = deg
        self._lbl.setText(f'{deg:+6.1f}°')
        lo, hi = self._limits
        self._slider.blockSignals(True)
        self._slider.setValue(int(max(lo, min(hi, deg)) * 100))
        self._slider.blockSignals(False)

    @property
    def current_deg(self):
        return self._current

    @property
    def held_direction(self) -> int:
        """Returns -1, 0, or +1 — uses isDown() so it resets even if mouse leaves button."""
        if self._plus.isDown():
            return +1
        if self._minus.isDown():
            return -1
        return 0


class JointControlPanel(QWidget):
    def __init__(self, bridge, safety_panel, parent=None):
        super().__init__(parent)
        self._bridge   = bridge
        self._safety   = safety_panel
        self._rows     = []
        self._joy_axes = [0.0]*6   # normalised -1..+1 per joint
        self._build_ui()

        # 100 Hz command timer — matches the official kinova-ros driver rate
        # The Kinova trajectory FIFO has a short timeout; sending faster keeps motion continuous
        self._cmd_timer = QTimer(self)
        self._cmd_timer.setInterval(10)   # 100 Hz
        self._cmd_timer.timeout.connect(self._send_velocity)
        self._cmd_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(8)

        hdr = QLabel('🦾  Joint Control Mode')
        hdr.setStyleSheet('color:#64b5f6;font-size:16px;font-weight:bold;')
        layout.addWidget(hdr)

        hint = QLabel('Hold +/− buttons or use joystick sticks to move each joint.')
        hint.setStyleSheet('color:#888;font-size:11px;')
        layout.addWidget(hint)

        group = QGroupBox('Joint Positions')
        group.setStyleSheet(self._grp())
        grp_l = QVBoxLayout(group)
        grp_l.setSpacing(4)

        for i, lim in enumerate(JOINT_LIMITS):
            row = JointRow(i, lim)
            self._rows.append(row)
            grp_l.addWidget(row)
        layout.addWidget(group)

        joy_row = QHBoxLayout()
        joy_lbl = QLabel('Joystick:')
        joy_lbl.setStyleSheet('color:#888;font-size:11px;')
        joy_row.addWidget(joy_lbl)
        self._joy_lbl = QLabel('—')
        self._joy_lbl.setStyleSheet('color:#a5d6a7;font-size:11px;')
        joy_row.addWidget(self._joy_lbl)
        joy_row.addStretch()
        layout.addLayout(joy_row)
        layout.addStretch()

    @pyqtSlot(dict)
    def update_arm_state(self, state):
        for i, row in enumerate(self._rows):
            pos = state.get('joint_positions', [])
            if i < len(pos):
                row.set_feedback(pos[i])

    @pyqtSlot(dict)
    def update_joy(self, joy):
        axes    = joy.get('axes', [])
        buttons = joy.get('buttons', [])

        def ax(i):   return axes[i]    if i < len(axes)    else 0.0
        def btn(i):  return buttons[i] if i < len(buttons) else 0

        # J1: Left stick Left/Right
        self._joy_axes[0] =  ax(_AX_LS_X)
        # J2: Left stick Up/Down (up = positive = increase angle)
        self._joy_axes[1] = -ax(_AX_LS_Y)
        # J3: Right stick Up/Down
        self._joy_axes[2] = -ax(_AX_RS_Y)
        # J4: Right stick Left/Right
        self._joy_axes[3] =  ax(_AX_RS_X)
        # J5: Back button (6) = +, R2 trigger = − (trigger is already 0.0..1.0 from handler)
        self._joy_axes[4] = btn(_BTN_BACK_J5) - ax(_AX_R2)
        # J6: Start button (7) = +, L2 trigger = −
        self._joy_axes[5] = btn(_BTN_START_J6) - ax(_AX_L2)

        self._joy_lbl.setText('  '.join(f'J{i+1}:{v:+.2f}' for i,v in enumerate(self._joy_axes)))

    def _send_velocity(self):
        if not self.isVisible():
            return
            
        # Send raw velocity — bridge applies the speed-scale, so don't multiply here
        vels = [v * MAX_SPEED_DPS for v in self._joy_axes]

        # Button hold overrides joystick for that joint
        for i, row in enumerate(self._rows):
            d = row.held_direction
            if d != 0:
                vels[i] = d * MAX_SPEED_DPS

        # Always send — zeros explicitly stop the arm when nothing is pressed
        self._bridge.publish_joint_velocity(vels)

    @staticmethod
    def _grp():
        return ('QGroupBox{color:#ccc;border:1px solid #444;border-radius:6px;'
                'margin-top:8px;font-size:13px;}'
                'QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}')
