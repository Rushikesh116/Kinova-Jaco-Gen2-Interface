#!/usr/bin/env python3
"""
kinova_bridge.py
=================
Central controller that connects the Kinova SDK, joystick handler,
and GUI together.

Responsibilities:
  • Polls arm state at 20 Hz → emits Qt signals to update GUI
  • Polls joystick at 50 Hz → forwards to active GUI tab
  • Applies global speed scale and e-stop gate on all motion
  • Provides a clean publish API for all GUI panels

This replaces ros_bridge.py from the ROS2 version.
No ROS required.
"""

import math
import threading
import time
from PyQt5.QtCore import QObject, QThread, pyqtSignal, QTimer


# ══════════════════════════════════════════════════════════════════════════════
# Background polling worker
# ══════════════════════════════════════════════════════════════════════════════

class ArmStateWorker(QThread):
    """Polls the Kinova API at 20 Hz and emits the state as a dict signal."""

    state_ready = pyqtSignal(dict)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self._api     = api
        self._active  = True

    def run(self):
        interval = 1.0 / 20   # 20 Hz
        while self._active:
            t0 = time.monotonic()
            try:
                joints  = self._api.get_joint_angles()       # [deg × 6]
                cart    = self._api.get_cartesian_pose()      # dict
                gripper = self._api.get_gripper_position()    # 0–1

                state = {
                    'connected':       True,
                    'joint_positions': joints,
                    'ee_position':     [cart['x'], cart['y'], cart['z']],
                    'ee_orientation':  [cart['roll'], cart['pitch'], cart['yaw']],
                    'gripper':         gripper,
                }
            except Exception as e:
                state = {'connected': False,
                         'error': str(e),
                         'joint_positions': [0.0]*6,
                         'ee_position': [0.0]*3,
                         'ee_orientation': [0.0]*3,
                         'gripper': 0.0}

            self.state_ready.emit(state)
            elapsed = time.monotonic() - t0
            sleep_t = interval - elapsed
            if sleep_t > 0:
                time.sleep(sleep_t)

    def stop(self):
        self._active = False


# ══════════════════════════════════════════════════════════════════════════════
# KinovaBridge — the main interface class
# ══════════════════════════════════════════════════════════════════════════════

class KinovaBridgeSignals(QObject):
    """Qt signal container (must be QObject for cross-thread delivery)."""
    arm_state_received = pyqtSignal(dict)   # polls at 20 Hz
    joy_received       = pyqtSignal(dict)   # polls at 50 Hz


class KinovaBridge:
    """
    Facade used by all GUI panels.

    Usage:
        bridge = KinovaBridge(api, joy_handler)
        bridge.start()
        bridge.signals.arm_state_received.connect(my_slot)
        bridge.publish_joint_velocity([10.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    """

    def __init__(self, api, joy_handler):
        self._api         = api
        self._joy         = joy_handler
        self.signals      = KinovaBridgeSignals()

        # Safety state
        self._e_stop      = False
        self._arm_enabled = True
        self._speed_scale = 0.3    # default 30%

        # Arm state poller
        self._state_worker = ArmStateWorker(api)
        self._state_worker.state_ready.connect(self.signals.arm_state_received)

        # Joystick relay timer (polls joy_handler.state at 50 Hz)
        self._joy_timer = QTimer()
        self._joy_timer.setInterval(20)   # 50 Hz
        self._joy_timer.timeout.connect(self._relay_joy)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """Start arm state polling and joystick relay."""
        self._state_worker.start()
        self._joy_timer.start()

    def stop(self):
        """Gracefully stop arm, poller, and joystick relay."""
        self.publish_zero_velocity()
        self._state_worker.stop()
        self._state_worker.wait(2000)
        self._joy_timer.stop()
        try:
            self._api.close()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Joystick relay
    # ------------------------------------------------------------------

    def _relay_joy(self):
        """Forward current joystick state to GUI via signal."""
        self.signals.joy_received.emit(self._joy.state)

    # ------------------------------------------------------------------
    # Motion commands — all gated by e-stop and arm_enabled
    # ------------------------------------------------------------------

    def publish_joint_velocity(self, velocities_dps: list[float]):
        """
        Send joint velocity command.
        velocities_dps: 6 values in deg/s (already scaled to real units).
        Speed scale is applied here.
        """
        if self._e_stop or not self._arm_enabled:
            return
        scaled = [v * self._speed_scale for v in velocities_dps]
        self._api.send_joint_velocity(scaled)

    def publish_cartesian_velocity(self, linear_mps: list[float],
                                   angular_dps: list[float]):
        """
        Send Cartesian velocity command.
        linear_mps  = [vx, vy, vz] m/s
        angular_dps = [wx, wy, wz] deg/s
        Speed scale applied.
        """
        if self._e_stop or not self._arm_enabled:
            return
        s   = self._speed_scale
        lin = [v * s for v in linear_mps]
        ang = [v * s for v in angular_dps]
        self._api.send_cartesian_velocity(lin, ang)

    def publish_gripper(self, position: float):
        """Send gripper target (0.0=open, 1.0=closed)."""
        if self._e_stop or not self._arm_enabled:
            return
        self._api.send_gripper(position)

    def publish_zero_velocity(self):
        """Immediately stop all arm motion."""
        try:
            self._api.stop()
        except Exception:
            pass

    def publish_estop(self, active: bool):
        """Activate or clear emergency stop."""
        self._e_stop = active
        if active:
            self.publish_zero_velocity()

    def publish_speed_scale(self, scale: float):
        """Set global speed scale (0.0–1.0)."""
        self._speed_scale = max(0.0, min(1.0, scale))

    def publish_enable(self, enabled: bool):
        """Enable or disable arm motion."""
        self._arm_enabled = enabled
        if not enabled:
            self.publish_zero_velocity()

    def home(self):
        """Send arm to home position."""
        if not self._e_stop and self._arm_enabled:
            self._api.home()

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_simulated(self) -> bool:
        """True if running in MockKinovaAPI mode (no real hardware)."""
        from kinova.api import MockKinovaAPI
        return isinstance(self._api, MockKinovaAPI)
