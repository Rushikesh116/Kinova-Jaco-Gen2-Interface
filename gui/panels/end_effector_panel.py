#!/usr/bin/env python3
"""
end_effector_panel.py
======================
Tab panel for End Effector / Gripper control.

Features:
  • Open / Close gripper buttons
  • Adjustable grip force slider
  • Numeric position setpoint spinner
  • Tool status indicator (open / closed / moving)
  • Live gripper position readback
  • Joystick button mapping (A=open, B=close)
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QSlider, QDoubleSpinBox, QProgressBar, QFrame
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer
from PyQt5.QtGui import QFont


class EndEffectorPanel(QWidget):
    """Gripper / tool control panel."""

    def __init__(self, ros_bridge, safety_panel, parent=None):
        super().__init__(parent)
        self._bridge  = ros_bridge
        self._safety  = safety_panel
        self._gripper_pos = 0.0   # 0=open, 1=closed (normalised)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # ---- Header ----
        hdr = QLabel('🤏  End Effector / Gripper Control')
        hdr.setStyleSheet('color: #ce93d8; font-size: 16px; font-weight: bold;')
        layout.addWidget(hdr)

        hint = QLabel('Press A (joystick) to open  |  Press B (joystick) to close')
        hint.setStyleSheet('color: #888; font-size: 11px;')
        layout.addWidget(hint)

        # ---- Status group ----
        status_group = self._build_status_group()
        layout.addWidget(status_group)

        # ---- Control group ----
        ctrl_group = self._build_control_group()
        layout.addWidget(ctrl_group)

        layout.addStretch()

    def _build_status_group(self) -> QGroupBox:
        group = QGroupBox('Gripper Status')
        group.setStyleSheet(self._group_style())
        layout = QVBoxLayout(group)

        # Status label
        row1 = QHBoxLayout()
        row1.addWidget(QLabel('Status:'))
        self._status_lbl = QLabel('UNKNOWN')
        self._status_lbl.setStyleSheet('color: #ffd600; font-size: 14px; font-weight: bold;')
        row1.addWidget(self._status_lbl)
        row1.addStretch()
        layout.addLayout(row1)

        # Position bar
        row2 = QHBoxLayout()
        row2.addWidget(QLabel('Position:'))
        self._pos_bar = QProgressBar()
        self._pos_bar.setRange(0, 100)
        self._pos_bar.setValue(0)
        self._pos_bar.setFormat('%v%')
        self._pos_bar.setStyleSheet('''
            QProgressBar { background: #1a1a2e; border: 1px solid #444;
                           border-radius: 6px; text-align: center; color: #ccc; }
            QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                  stop:0 #4a00e0, stop:1 #8e2de2);
                                  border-radius: 6px; }
        ''')
        row2.addWidget(self._pos_bar, stretch=1)

        self._pos_lbl = QLabel('0%')
        self._pos_lbl.setFixedWidth(40)
        self._pos_lbl.setAlignment(Qt.AlignRight)
        self._pos_lbl.setStyleSheet('color: #ce93d8; font-weight: bold;')
        row2.addWidget(self._pos_lbl)
        layout.addLayout(row2)

        return group

    def _build_control_group(self) -> QGroupBox:
        group = QGroupBox('Gripper Control')
        group.setStyleSheet(self._group_style())
        layout = QVBoxLayout(group)
        layout.setSpacing(12)

        # ---- Open / Close buttons ----
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        self._open_btn = QPushButton('🟢  Open Gripper')
        self._open_btn.setFixedHeight(52)
        self._open_btn.setStyleSheet('''
            QPushButton { background: #1b5e20; color: #a5d6a7; border: 2px solid #388e3c;
                          border-radius: 8px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #2e7d32; }
            QPushButton:pressed { background: #0a3d0a; }
        ''')
        self._open_btn.clicked.connect(self._open_gripper)
        btn_row.addWidget(self._open_btn)

        self._close_btn = QPushButton('🔴  Close Gripper')
        self._close_btn.setFixedHeight(52)
        self._close_btn.setStyleSheet('''
            QPushButton { background: #7f0000; color: #ef9a9a; border: 2px solid #c62828;
                          border-radius: 8px; font-size: 14px; font-weight: bold; }
            QPushButton:hover { background: #b71c1c; }
            QPushButton:pressed { background: #500000; }
        ''')
        self._close_btn.clicked.connect(self._close_gripper)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        # ---- Force slider ----
        force_row = QHBoxLayout()
        force_lbl = QLabel('Grip Force:')
        force_lbl.setStyleSheet('color: #aaa; font-size: 12px;')
        force_row.addWidget(force_lbl)

        self._force_slider = QSlider(Qt.Horizontal)
        self._force_slider.setRange(0, 100)
        self._force_slider.setValue(50)
        self._force_slider.setStyleSheet('''
            QSlider::groove:horizontal { height: 6px; background: #333; border-radius: 3px; }
            QSlider::handle:horizontal { background: #ce93d8; width: 16px; height: 16px;
                                         margin: -5px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #6a1b9a; border-radius: 3px; }
        ''')
        force_row.addWidget(self._force_slider, stretch=1)

        self._force_val = QLabel('50%')
        self._force_val.setFixedWidth(40)
        self._force_val.setAlignment(Qt.AlignRight)
        self._force_val.setStyleSheet('color: #ce93d8; font-weight: bold;')
        self._force_slider.valueChanged.connect(
            lambda v: self._force_val.setText(f'{v}%')
        )
        force_row.addWidget(self._force_val)
        layout.addLayout(force_row)

        # ---- Precise position setpoint ----
        pos_row = QHBoxLayout()
        pos_lbl = QLabel('Target Position:')
        pos_lbl.setStyleSheet('color: #aaa; font-size: 12px;')
        pos_row.addWidget(pos_lbl)

        self._pos_spin = QDoubleSpinBox()
        self._pos_spin.setRange(0.0, 100.0)
        self._pos_spin.setSuffix('%')
        self._pos_spin.setSingleStep(5.0)
        self._pos_spin.setValue(0.0)
        self._pos_spin.setFixedWidth(90)
        self._pos_spin.setStyleSheet(
            'background: #1a1a2e; color: #ccc; border: 1px solid #444; border-radius: 4px;')
        pos_row.addWidget(self._pos_spin)

        go_btn = QPushButton('Go')
        go_btn.setFixedWidth(50)
        go_btn.setStyleSheet('''
            QPushButton { background: #1565c0; color: #fff; border-radius: 4px; font-size: 12px; }
            QPushButton:hover { background: #1976d2; }
        ''')
        go_btn.clicked.connect(self._go_to_position)
        pos_row.addWidget(go_btn)
        pos_row.addStretch()
        layout.addLayout(pos_row)

        return group

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _open_gripper(self):
        """Fully open the gripper."""
        self._bridge.publish_gripper(0.0)
        self._update_status_display(0.0, 'OPENING')

    def _close_gripper(self):
        """Fully close the gripper."""
        self._bridge.publish_gripper(1.0)
        self._update_status_display(1.0, 'CLOSING')

    def _go_to_position(self):
        """Move gripper to the setpoint percentage."""
        target = self._pos_spin.value() / 100.0
        self._bridge.publish_gripper(target)
        self._update_status_display(target, 'MOVING')

    # ------------------------------------------------------------------
    # Joystick integration
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def update_joy(self, joy: dict):
        """Handle joystick button presses for gripper."""
        buttons = joy.get('buttons', [])
        if len(buttons) > 0 and buttons[0]:   # A button = open
            self._open_gripper()
        elif len(buttons) > 1 and buttons[1]: # B button = close
            self._close_gripper()

    # ------------------------------------------------------------------
    # Feedback
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def update_arm_state(self, state: dict):
        """Update gripper feedback if included in arm state."""
        # Gripper position is not in the default arm state blob.
        # If your driver publishes gripper feedback, update here.
        pass

    def _update_status_display(self, position: float, label: str):
        """Update the status indicator and position bar."""
        self._gripper_pos = position
        pct = int(position * 100)
        self._pos_bar.setValue(pct)
        self._pos_lbl.setText(f'{pct}%')
        self._status_lbl.setText(label)
        if position <= 0.05:
            colour = '#a5d6a7'  # green = open
        elif position >= 0.95:
            colour = '#ef9a9a'  # red = closed
        else:
            colour = '#ffd600'  # yellow = partial
        self._status_lbl.setStyleSheet(f'color: {colour}; font-size: 14px; font-weight: bold;')

    # ------------------------------------------------------------------

    @staticmethod
    def _group_style() -> str:
        return '''
            QGroupBox { color: #ccc; border: 1px solid #444; border-radius: 6px;
                        margin-top: 8px; font-size: 13px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        '''
