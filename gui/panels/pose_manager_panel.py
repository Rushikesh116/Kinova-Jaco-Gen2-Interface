#!/usr/bin/env python3
"""
pose_manager_panel.py
======================
Tab panel for saving and recalling named robot poses.

Features:
  • Save current joint/Cartesian pose with a name
  • List of saved poses with quick recall
  • Home arm button
  • Reset pose button
  • Poses persisted to ~/.kinova_gui/poses.json
"""

import json
import os
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QListWidget, QListWidgetItem, QLineEdit,
    QMessageBox, QSplitter, QTextEdit
)
from PyQt5.QtCore import Qt, pyqtSlot


POSES_FILE = os.path.expanduser('~/.kinova_gui/poses.json')

# Home pose — standard Kinova Jaco Gen2 home configuration (degrees)
HOME_POSE_DEG = [275.31, 167.36, 57.23, 241.09, 82.63, 75.74]


def _ensure_dir():
    """Create the ~/.kinova_gui directory if it doesn't exist."""
    os.makedirs(os.path.dirname(POSES_FILE), exist_ok=True)


class PoseManagerPanel(QWidget):
    """Save, load, and recall named robot arm poses."""

    def __init__(self, ros_bridge, parent=None):
        super().__init__(parent)
        self._bridge       = ros_bridge
        self._poses: dict  = {}     # {name: {joints, ee_position, ee_orientation, timestamp}}
        self._current_state: dict = {}   # last arm state from bridge

        # Connect to arm state
        self._bridge.signals.arm_state_received.connect(self._on_arm_state)

        self._load_poses()
        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # ---- Header ----
        hdr = QLabel('📌  Pose Manager')
        hdr.setStyleSheet('color: #80cbc4; font-size: 16px; font-weight: bold;')
        layout.addWidget(hdr)

        # ---- Quick actions row ----
        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)

        home_btn = QPushButton('🏠  Home Arm')
        home_btn.setFixedHeight(40)
        home_btn.setStyleSheet(self._action_btn_style('#1565c0'))
        home_btn.clicked.connect(self._home_arm)
        quick_row.addWidget(home_btn)

        reset_btn = QPushButton('↺  Reset Pose')
        reset_btn.setFixedHeight(40)
        reset_btn.setStyleSheet(self._action_btn_style('#37474f'))
        reset_btn.clicked.connect(self._reset_pose)
        quick_row.addWidget(reset_btn)

        quick_row.addStretch()
        layout.addLayout(quick_row)

        # ---- Main splitter: Save | List ----
        splitter = QSplitter(Qt.Horizontal)

        # Left: Save pose
        save_widget = self._build_save_group()
        splitter.addWidget(save_widget)

        # Right: Pose list
        list_widget = self._build_list_group()
        splitter.addWidget(list_widget)

        splitter.setSizes([350, 400])
        layout.addWidget(splitter, stretch=1)

    def _build_save_group(self) -> QGroupBox:
        group = QGroupBox('Save Current Pose')
        group.setStyleSheet(self._group_style())
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        # Name input
        layout.addWidget(QLabel('Pose Name:'))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText('e.g. inspection_point_1')
        self._name_edit.setStyleSheet(
            'background: #1a1a2e; color: #ccc; border: 1px solid #444; '
            'border-radius: 4px; padding: 4px 8px;')
        layout.addWidget(self._name_edit)

        # Current pose preview
        layout.addWidget(QLabel('Current Joint Angles (deg):'))
        self._preview_lbl = QLabel('Waiting for arm state…')
        self._preview_lbl.setWordWrap(True)
        self._preview_lbl.setStyleSheet(
            'color: #80cbc4; font-size: 11px; background: #0d1117; '
            'border: 1px solid #333; border-radius: 4px; padding: 6px;')
        layout.addWidget(self._preview_lbl)

        # Save button
        save_btn = QPushButton('💾  Save Pose')
        save_btn.setFixedHeight(38)
        save_btn.setStyleSheet(self._action_btn_style('#2e7d32'))
        save_btn.clicked.connect(self._save_pose)
        layout.addWidget(save_btn)

        layout.addStretch()
        return group

    def _build_list_group(self) -> QGroupBox:
        group = QGroupBox('Saved Poses')
        group.setStyleSheet(self._group_style())
        layout = QVBoxLayout(group)

        self._pose_list = QListWidget()
        self._pose_list.setStyleSheet('''
            QListWidget { background: #0d1117; color: #ccc; border: 1px solid #333;
                          border-radius: 4px; font-size: 12px; }
            QListWidget::item:selected { background: #1565c0; color: #fff; }
            QListWidget::item:hover { background: #1a1a2e; }
        ''')
        self._pose_list.currentRowChanged.connect(self._on_pose_selected)
        layout.addWidget(self._pose_list, stretch=1)

        # Pose detail view
        self._detail_lbl = QTextEdit()
        self._detail_lbl.setReadOnly(True)
        self._detail_lbl.setFixedHeight(80)
        self._detail_lbl.setStyleSheet(
            'background: #0d1117; color: #888; border: 1px solid #333; '
            'font-size: 11px; font-family: monospace;')
        layout.addWidget(self._detail_lbl)

        # Action buttons
        btn_row = QHBoxLayout()
        goto_btn = QPushButton('▶  Go To Pose')
        goto_btn.setFixedHeight(36)
        goto_btn.setStyleSheet(self._action_btn_style('#1565c0'))
        goto_btn.clicked.connect(self._go_to_pose)
        btn_row.addWidget(goto_btn)

        del_btn = QPushButton('🗑  Delete')
        del_btn.setFixedHeight(36)
        del_btn.setStyleSheet(self._action_btn_style('#b71c1c'))
        del_btn.clicked.connect(self._delete_pose)
        btn_row.addWidget(del_btn)
        layout.addLayout(btn_row)

        return group

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _save_pose(self):
        """Save current arm state as a named pose."""
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, 'No Name', 'Please enter a pose name.')
            return
        if not self._current_state:
            QMessageBox.warning(self, 'No State', 'No arm state received yet.')
            return

        self._poses[name] = {
            'joints':       self._current_state.get('joint_positions', []),
            'ee_position':  self._current_state.get('ee_position', []),
            'ee_orientation': self._current_state.get('ee_orientation', []),
            'timestamp':    datetime.now().isoformat(),
        }
        self._save_poses()
        self._refresh_list()
        self._name_edit.clear()

    def _go_to_pose(self):
        """Send joint velocity commands to drive arm to selected pose (open-loop)."""
        name = self._selected_pose_name()
        if name is None:
            return
        pose = self._poses[name]
        joints = pose.get('joints', [])
        if not joints:
            QMessageBox.information(self, 'Empty', 'Pose has no joint data.')
            return
        # For now we just log the intent — real go-to requires position control
        # which depends on the driver. Uncomment the block below once you have
        # a position controller hooked up.
        QMessageBox.information(
            self, 'Go To Pose',
            f'Target: {name}\nJoints: {[f"{j:.1f}°" for j in joints]}\n\n'
            f'NOTE: Implement position control in arm_commander_node.py '
            f'and call the appropriate service/action here.'
        )

    def _delete_pose(self):
        """Delete the selected pose."""
        name = self._selected_pose_name()
        if name is None:
            return
        ans = QMessageBox.question(
            self, 'Delete Pose', f'Delete pose "{name}"?',
            QMessageBox.Yes | QMessageBox.No
        )
        if ans == QMessageBox.Yes:
            del self._poses[name]
            self._save_poses()
            self._refresh_list()

    def _home_arm(self):
        """Send arm to home position."""
        # Publish home as a joint position target
        # (requires position control — same note as _go_to_pose)
        QMessageBox.information(
            self, 'Home Arm',
            f'Homing to: {HOME_POSE_DEG}\n\n'
            f'Connect your driver\'s home service/action in arm_commander_node.py.'
        )

    def _reset_pose(self):
        """Reset to a neutral/retracted pose (all zeros)."""
        QMessageBox.information(
            self, 'Reset Pose',
            'Resetting arm to zero configuration.\n'
            'Implement via position control in arm_commander_node.py.'
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def _on_arm_state(self, state: dict):
        self._current_state = state
        joints = state.get('joint_positions', [])
        text = '\n'.join(
            f'J{i+1}: {v:+.1f}°' for i, v in enumerate(joints)
        )
        self._preview_lbl.setText(text or 'No joint data')

    def _on_pose_selected(self, row: int):
        name = self._selected_pose_name()
        if name is None:
            return
        pose = self._poses[name]
        joints = pose.get('joints', [])
        pos    = pose.get('ee_position', [])
        detail = (
            f"Saved: {pose.get('timestamp', '—')}\n"
            f"Joints (deg): {', '.join(f'{v:.1f}' for v in joints)}\n"
            f"EE pos (m):   {', '.join(f'{v:.4f}' for v in pos)}"
        )
        self._detail_lbl.setText(detail)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_poses(self):
        try:
            with open(POSES_FILE) as f:
                self._poses = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self._poses = {}

    def _save_poses(self):
        _ensure_dir()
        with open(POSES_FILE, 'w') as f:
            json.dump(self._poses, f, indent=2)

    def _refresh_list(self):
        self._pose_list.clear()
        for name in sorted(self._poses.keys()):
            self._pose_list.addItem(QListWidgetItem(name))

    def _selected_pose_name(self) -> str | None:
        item = self._pose_list.currentItem()
        return item.text() if item else None

    # ------------------------------------------------------------------
    # Style helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _group_style() -> str:
        return '''
            QGroupBox { color: #ccc; border: 1px solid #444; border-radius: 6px;
                        margin-top: 8px; font-size: 13px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        '''

    @staticmethod
    def _action_btn_style(colour: str) -> str:
        return f'''
            QPushButton {{ background: {colour}; color: #fff; border-radius: 6px;
                           font-size: 13px; font-weight: bold; }}
            QPushButton:hover {{ background: {colour}cc; }}
            QPushButton:pressed {{ background: {colour}88; }}
        '''
