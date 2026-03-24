#!/usr/bin/env python3
"""
main_window.py — Main PyQt5 window for the pure-Python Kinova controller.
Identical layout to the ROS2 version; uses KinovaBridge instead of RosBridge.
"""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer
from PyQt5.QtGui import QFont

from gui.panels.status_panel        import StatusPanel
from gui.panels.safety_panel        import SafetyPanel
from gui.panels.joint_control_panel import JointControlPanel
from gui.panels.cartesian_panel     import CartesianPanel
from gui.panels.end_effector_panel  import EndEffectorPanel
from gui.panels.joystick_panel      import JoystickPanel
from gui.panels.pose_manager_panel  import PoseManagerPanel
from gui.panels.arm_3d_panel        import ArmVisualizer3DPanel


class MainWindow(QMainWindow):
    """Top-level window — assembles all panels, routes signals."""

    MODE_NAMES = ['Joint Control', 'Cartesian Control',
                  'End Effector', 'Joystick', 'Poses', '3D View']

    def __init__(self, bridge, simulated: bool = False):
        super().__init__()
        self._bridge         = bridge
        self._e_stop_active  = False
        self._simulated      = simulated
        self._prev_btns      = []   # for edge-detection debounce

        title = 'Kinova Jaco Gen2 — Control GUI'
        if simulated:
            title += '  [SIMULATION MODE]'
        self.setWindowTitle(title)
        self.resize(1280, 780)
        self.setMinimumSize(900, 600)

        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Status bar (top)
        self._status_panel = StatusPanel()
        root.addWidget(self._status_panel)

        # Main content
        content = QHBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)

        # ---- Tabs ----
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet('''
            QTabWidget::pane { border:none; background:#12121f; }
            QTabBar::tab { background:#1a1a2e; color:#888; padding:10px 20px;
                           border-bottom:2px solid transparent; font-size:13px; }
            QTabBar::tab:selected { color:#64b5f6; border-bottom:2px solid #64b5f6;
                                    background:#1e1e3a; }
            QTabBar::tab:hover { color:#ccc; background:#1e1e3a; }
        ''')
        content.addWidget(self._tabs, stretch=1)

        # ---- Safety sidebar ----
        self._safety_panel = SafetyPanel()
        content.addWidget(self._safety_panel)
        root.addLayout(content, stretch=1)

        # ---- Instantiate panels ----
        self._joint_panel = JointControlPanel(self._bridge, self._safety_panel)
        self._cart_panel  = CartesianPanel(self._bridge, self._safety_panel)
        self._ee_panel    = EndEffectorPanel(self._bridge, self._safety_panel)
        self._joy_panel   = JoystickPanel()
        self._pose_panel  = PoseManagerPanel(self._bridge)

        self._arm_3d_panel = ArmVisualizer3DPanel()

        self._tabs.addTab(self._joint_panel, '🦾  Joint Control')
        self._tabs.addTab(self._cart_panel,  '📍  Cartesian')
        self._tabs.addTab(self._ee_panel,    '🤏  End Effector')
        self._tabs.addTab(self._joy_panel,   '🎮  Joystick')
        self._tabs.addTab(self._pose_panel,  '📌  Poses')
        self._tabs.addTab(self._arm_3d_panel,'🌐  3D View')

        sb = self.statusBar()
        sb.setStyleSheet('background:#1a1a2e;color:#555;font-size:11px;')
        mode_str = '⚠ SIMULATION — no arm connected' if self._simulated else 'Ready'
        sb.showMessage(f'Kinova Jaco Gen2 Controller — {mode_str}')

    def _connect_signals(self):
        # Arm state → panels
        self._bridge.signals.arm_state_received.connect(self._status_panel.update_arm_state)
        self._bridge.signals.arm_state_received.connect(self._joint_panel.update_arm_state)
        self._bridge.signals.arm_state_received.connect(self._cart_panel.update_arm_state)
        self._bridge.signals.arm_state_received.connect(self._ee_panel.update_arm_state)
        self._bridge.signals.arm_state_received.connect(self._arm_3d_panel.update_arm_state)

        # Joystick → panels + global handlers
        self._bridge.signals.joy_received.connect(self._joy_panel.update_joy)
        self._bridge.signals.joy_received.connect(self._on_joy)

        # Safety panel → bridge
        self._safety_panel.estop_requested.connect(self._on_estop)
        self._safety_panel.stop_motion_requested.connect(self._bridge.publish_zero_velocity)
        self._safety_panel.speed_scale_changed.connect(
            lambda v: (self._bridge.publish_speed_scale(v/100.0),
                       self._status_panel.update_speed(v))
        )
        self._safety_panel.arm_enable_changed.connect(self._bridge.publish_enable)

        # Mode label
        self._tabs.currentChanged.connect(
            lambda i: self._status_panel.update_mode(self.MODE_NAMES[i])
        )
        self._tabs.currentChanged.connect(
            lambda _: self._bridge.publish_zero_velocity()  # stop on tab switch
        )
        self._status_panel.update_mode(self.MODE_NAMES[0])

        # Initial speed sync
        self._bridge.publish_speed_scale(self._safety_panel.get_speed_scale())
        self._status_panel.update_speed(int(self._safety_panel.get_speed_scale() * 100))

    # ------------------------------------------------------------------

    @pyqtSlot(bool)
    def _on_estop(self, active: bool):
        self._e_stop_active = active
        self._bridge.publish_estop(active)
        self._status_panel.update_estop(active)
        if active:
            self.statusBar().showMessage('⚠ EMERGENCY STOP ACTIVE — release before moving', 0)
        else:
            self.statusBar().showMessage('E-Stop cleared — motion re-enabled')

    @pyqtSlot(dict)
    def _on_joy(self, joy: dict):
        """Route joystick to active tab; handle global buttons with edge detection."""
        btns = joy.get('buttons', [])

        def _just_pressed(idx):
            """True only on the rising edge (was 0, now 1)."""
            prev = self._prev_btns[idx] if idx < len(self._prev_btns) else 0
            curr = btns[idx]            if idx < len(btns)           else 0
            return curr and not prev

        # X button (0): Toggle emergency stop
        if _just_pressed(0):
            self._safety_panel.set_estop(not self._e_stop_active)

        # Y button (3): Cycle between Joint Control (tab 0) and Cartesian (tab 1)
        if _just_pressed(3):
            current = self._tabs.currentIndex()
            if current == 0:
                self._tabs.setCurrentIndex(1)   # → Cartesian
            elif current == 1:
                self._tabs.setCurrentIndex(0)   # → Joint Control

        self._prev_btns = list(btns)

        # Route to active tab
        active = self._tabs.currentIndex()
        if active == 0:   self._joint_panel.update_joy(joy)
        elif active == 1: self._cart_panel.update_joy(joy)
        elif active == 2: self._ee_panel.update_joy(joy)

    def closeEvent(self, event):
        self._bridge.stop()
        event.accept()
