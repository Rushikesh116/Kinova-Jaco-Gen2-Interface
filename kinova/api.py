#!/usr/bin/env python3
"""
kinova_api.py
==============
ctypes wrapper around the Kinova Jaco Gen2 SDK library (libkinovadrv.so).

If the library is not found, falls back to a **MockKinovaAPI** that simulates
arm state — allowing the GUI to run and be tested without physical hardware.

Installation of real SDK:
  1. Clone: git clone https://github.com/Kinovarobotics/kinova-sdk
  2. Run:   sudo bash kinova-sdk/API/32_64-bit/Ubuntu_16_04/installudev.sh
  3. Copy:  sudo cp kinova-sdk/API/32_64-bit/Ubuntu_16_04/64bit/libkinovadrv.so /usr/lib/
  4. sudo ldconfig

Alternatively, if you have kinova-ros installed:
  sudo cp /opt/ros/noetic/lib/libkinovadrv.so /usr/lib/ && sudo ldconfig
"""

import ctypes
import math
import time
import threading
import os

# ── Library search paths ───────────────────────────────────────────────────────
_LIB_SEARCH = [
    '/usr/lib/libkinovadrv.so',
    '/usr/local/lib/libkinovadrv.so',
    '/opt/kinova/lib/libkinovadrv.so',
    os.path.expanduser('~/kinova/lib/libkinovadrv.so'),
]

# ══════════════════════════════════════════════════════════════════════════════
# C struct definitions (from KinovaTypes.h)
# ══════════════════════════════════════════════════════════════════════════════

class AngularInfo(ctypes.Structure):
    """7-DOF joint values (positions, velocities, or efforts). Jaco Gen2 has 6 used + 1 padding."""
    _fields_ = [
        ('Actuator1', ctypes.c_float),
        ('Actuator2', ctypes.c_float),
        ('Actuator3', ctypes.c_float),
        ('Actuator4', ctypes.c_float),
        ('Actuator5', ctypes.c_float),
        ('Actuator6', ctypes.c_float),
        ('Actuator7', ctypes.c_float),  # Jaco Gen2 is 6-DOF, but SDK struct has 7 slots
    ]

    def to_list(self) -> list[float]:
        return [self.Actuator1, self.Actuator2, self.Actuator3,
                self.Actuator4, self.Actuator5, self.Actuator6]

    def from_list(self, vals: list[float]):
        self.Actuator1 = vals[0]; self.Actuator2 = vals[1]
        self.Actuator3 = vals[2]; self.Actuator4 = vals[3]
        self.Actuator5 = vals[4]; self.Actuator6 = vals[5]
        self.Actuator7 = 0.0


class FingersPosition(ctypes.Structure):
    """Gripper finger positions (0 = open, 6800 = closed for Jaco)."""
    _fields_ = [
        ('Finger1', ctypes.c_float),
        ('Finger2', ctypes.c_float),
        ('Finger3', ctypes.c_float),
    ]


class AngularPosition(ctypes.Structure):
    """Full joint position readback including fingers."""
    _fields_ = [
        ('Actuators', AngularInfo),
        ('Fingers',   FingersPosition),
    ]


class CartesianInfo(ctypes.Structure):
    """End-effector Cartesian pose [m, rad]."""
    _fields_ = [
        ('X',      ctypes.c_float),
        ('Y',      ctypes.c_float),
        ('Z',      ctypes.c_float),
        ('ThetaX', ctypes.c_float),   # Roll [rad]
        ('ThetaY', ctypes.c_float),   # Pitch [rad]
        ('ThetaZ', ctypes.c_float),   # Yaw [rad]
    ]


class CartesianPosition(ctypes.Structure):
    """Full cartesian position readback including fingers."""
    _fields_ = [
        ('Coordinates', CartesianInfo),
        ('Fingers',     FingersPosition),
    ]


class UserPosition(ctypes.Structure):
    """Abstract position builder."""
    _fields_ = [
        ('Type',              ctypes.c_int),
        ('Delay',             ctypes.c_float),
        ('CartesianPosition', CartesianInfo),
        ('Actuators',         AngularInfo),
        ('HandMode',          ctypes.c_int),
        ('Fingers',           FingersPosition),
    ]

class Limitation(ctypes.Structure):
    """Velocity/Force limitation parameters."""
    _fields_ = [
        ('speedParameter1', ctypes.c_float),
        ('speedParameter2', ctypes.c_float),
        ('speedParameter3', ctypes.c_float),
        ('forceParameter1', ctypes.c_float),
        ('forceParameter2', ctypes.c_float),
        ('forceParameter3', ctypes.c_float),
        ('accelerationParameter1', ctypes.c_float),
        ('accelerationParameter2', ctypes.c_float),
        ('accelerationParameter3', ctypes.c_float),
    ]

class TrajectoryPoint(ctypes.Structure):
    """Used for both Cartesian and Angular position commands."""
    _fields_ = [
        ('Position',          UserPosition),
        ('LimitationsActive', ctypes.c_int),
        ('SynchroType',       ctypes.c_int),
        ('Limitations',       Limitation),
    ]

# Internal Enums
POSITION_TYPE_CARTESIAN_POSITION = 1
POSITION_TYPE_CARTESIAN_VELOCITY = 7
POSITION_TYPE_ANGULAR_VELOCITY   = 8


# ══════════════════════════════════════════════════════════════════════════════
# Real SDK wrapper
# ══════════════════════════════════════════════════════════════════════════════

class RealKinovaAPI:
    """
    Thin ctypes wrapper around the Kinova SDK shared library.
    All physical units follow the SDK convention:
      • Joint angles  — degrees
      • Cartesian pos — meters
      • Cartesian rot — radians (displayed as degrees in GUI)
      • Gripper       — 0 (open) → 6800 (closed)
    """

    GRIPPER_MAX = 6800.0    # fully closed raw value for Jaco 3-finger

    def __init__(self, lib_path: str):
        self._lib = ctypes.CDLL(lib_path)
        self._setup_signatures()
        # Try once; if we get 1015 (device locked from previous crash), close and retry
        rc = self._lib.InitAPI()
        if rc != 1:
            if rc == 1015:
                print(f'[KinovaAPI] USB device locked (previous crash?) — retrying...')
                self._lib.CloseAPI()
                time.sleep(1.0)
                rc = self._lib.InitAPI()
            if rc != 1:
                raise RuntimeError(f'Kinova InitAPI failed with code {rc}')
        # Take control of the arm so it accepts our commands
        self._lib.StartControlAPI()
        self._lib.SetAngularControl()
        # Always call CloseAPI on exit, even on Ctrl+C
        import atexit
        atexit.register(self._lib.CloseAPI)
        print(f'[KinovaAPI] Connected via {lib_path}')

    def _setup_signatures(self):
        lib = self._lib
        lib.InitAPI.restype           = ctypes.c_int
        lib.CloseAPI.restype          = ctypes.c_int
        lib.StartControlAPI.restype   = ctypes.c_int
        lib.StopControlAPI.restype    = ctypes.c_int
        lib.MoveHome.restype          = ctypes.c_int
        lib.InitFingers.restype       = ctypes.c_int
        lib.SetAngularControl.restype  = ctypes.c_int
        lib.SetCartesianControl.restype = ctypes.c_int
        lib.EraseAllTrajectories.restype = ctypes.c_int

        lib.GetAngularPosition.restype     = ctypes.c_int
        lib.GetAngularPosition.argtypes    = [ctypes.POINTER(AngularPosition)]
        lib.GetCartesianPosition.restype   = ctypes.c_int
        lib.GetCartesianPosition.argtypes  = [ctypes.POINTER(CartesianPosition)]

        lib.SendAdvanceTrajectory.restype    = ctypes.c_int
        lib.SendAdvanceTrajectory.argtypes   = [TrajectoryPoint]
        lib.SendBasicTrajectory.restype      = ctypes.c_int
        lib.SendBasicTrajectory.argtypes     = [TrajectoryPoint]

    # ── State readback ─────────────────────────────────────────────────────

    def get_joint_angles(self) -> list[float]:
        """Return list of 6 joint angles in degrees."""
        pos = AngularPosition()
        self._lib.GetAngularPosition(ctypes.byref(pos))
        return pos.Actuators.to_list()

    def get_cartesian_pose(self) -> dict:
        """Return {x, y, z, roll, pitch, yaw} — pos in m, rot in deg."""
        cp = CartesianPosition()
        self._lib.GetCartesianPosition(ctypes.byref(cp))
        c = cp.Coordinates
        return {
            'x': c.X, 'y': c.Y, 'z': c.Z,
            'roll':  math.degrees(c.ThetaX),
            'pitch': math.degrees(c.ThetaY),
            'yaw':   math.degrees(c.ThetaZ),
        }

    def get_gripper_position(self) -> float:
        """Return normalised gripper position 0.0 (open) – 1.0 (closed)."""
        cp = CartesianPosition()
        self._lib.GetCartesianPosition(ctypes.byref(cp))
        raw = (cp.Fingers.Finger1 + cp.Fingers.Finger2 + cp.Fingers.Finger3) / 3.0
        return min(1.0, raw / self.GRIPPER_MAX)

    # ── Motion commands ────────────────────────────────────────────────────

    def send_joint_velocity(self, velocities_dps: list[float]):
        """Send joint velocity. velocities_dps: 6-element list [deg/s]."""
        point = TrajectoryPoint()
        point.Position.Type = POSITION_TYPE_ANGULAR_VELOCITY
        point.Position.Actuators.from_list(velocities_dps)
        self._lib.SendAdvanceTrajectory(point)

    def send_cartesian_velocity(self, linear: list[float], angular_dps: list[float]):
        """
        Send Cartesian velocity.
        linear      [m/s]   = [vx, vy, vz]
        angular_dps [deg/s] = [wx, wy, wz]
        """
        point = TrajectoryPoint()
        point.Position.Type = POSITION_TYPE_CARTESIAN_VELOCITY
        point.Position.CartesianPosition.X = linear[0]
        point.Position.CartesianPosition.Y = linear[1]
        point.Position.CartesianPosition.Z = linear[2]
        point.Position.CartesianPosition.ThetaX = angular_dps[0]
        point.Position.CartesianPosition.ThetaY = angular_dps[1]
        point.Position.CartesianPosition.ThetaZ = angular_dps[2]
        self._lib.SendAdvanceTrajectory(point)

    def send_gripper(self, position_norm: float):
        """Move gripper. position_norm: 0.0 = open, 1.0 = fully closed."""
        raw   = position_norm * self.GRIPPER_MAX
        point = TrajectoryPoint()
        point.Position.Type = POSITION_TYPE_CARTESIAN_POSITION
        point.Position.HandMode = 1 # POSITION_MODE
        point.Position.Fingers.Finger1 = raw
        point.Position.Fingers.Finger2 = raw
        point.Position.Fingers.Finger3 = raw
        self._lib.SendBasicTrajectory(point)

    def stop(self):
        """Send zero velocity to stop all motion."""
        self.send_joint_velocity([0.0] * 6)

    def home(self):
        """Move arm to home position."""
        self._lib.MoveHome()

    def close(self):
        """Release SDK connection."""
        self.stop()
        self._lib.CloseAPI()
        print('[KinovaAPI] Disconnected')


# ══════════════════════════════════════════════════════════════════════════════
# Mock SDK (simulation — used when library is not installed)
# ══════════════════════════════════════════════════════════════════════════════

class MockKinovaAPI:
    """
    Software simulation of the Kinova Jaco Gen2 arm.
    Integrates commanded velocities to animate joint positions.
    Used for GUI development and testing without hardware.
    """

    GRIPPER_MAX = 6800.0

    def __init__(self):
        # Simulated arm state
        self._joints   = [275.31, 167.36, 57.23, 241.09, 82.63, 75.74]  # home
        self._cart     = {'x': 0.3, 'y': 0.0, 'z': 0.5,
                          'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0}
        self._gripper  = 0.0    # 0=open, 1=closed
        self._j_vel    = [0.0] * 6   # current commanded joint velocities
        self._c_vel    = {'vx':0.0,'vy':0.0,'vz':0.0,'wx':0.0,'wy':0.0,'wz':0.0}
        self._lock     = threading.Lock()
        self._running  = True

        # Integration thread (50 Hz)
        self._thread = threading.Thread(target=self._integrate, daemon=True)
        self._thread.start()
        print('[MockKinovaAPI] Running in simulation mode — no hardware connected')

    def _integrate(self):
        dt = 0.02  # 50 Hz
        joint_limits = [(-180,180),(47,313),(19,341),(-180,180),(-180,180),(-180,180)]
        while self._running:
            with self._lock:
                for i in range(6):
                    new = self._joints[i] + self._j_vel[i] * dt
                    lo, hi = joint_limits[i]
                    self._joints[i] = max(lo, min(hi, new))
                self._cart['x']     += self._c_vel['vx'] * dt
                self._cart['y']     += self._c_vel['vy'] * dt
                self._cart['z']     += self._c_vel['vz'] * dt
                self._cart['roll']  += self._c_vel['wx'] * dt
                self._cart['pitch'] += self._c_vel['wy'] * dt
                self._cart['yaw']   += self._c_vel['wz'] * dt
            time.sleep(dt)

    # ── State readback ─────────────────────────────────────────────────────

    def get_joint_angles(self) -> list[float]:
        with self._lock:
            return list(self._joints)

    def get_cartesian_pose(self) -> dict:
        with self._lock:
            return dict(self._cart)

    def get_gripper_position(self) -> float:
        with self._lock:
            return self._gripper

    # ── Motion commands ────────────────────────────────────────────────────

    def send_joint_velocity(self, velocities_dps: list[float]):
        with self._lock:
            self._j_vel = list(velocities_dps[:6])

    def send_cartesian_velocity(self, linear: list[float], angular_dps: list[float]):
        with self._lock:
            self._c_vel = {
                'vx': linear[0], 'vy': linear[1], 'vz': linear[2],
                'wx': angular_dps[0], 'wy': angular_dps[1], 'wz': angular_dps[2],
            }
            self._j_vel = [0.0] * 6

    def send_gripper(self, position_norm: float):
        with self._lock:
            self._gripper = max(0.0, min(1.0, position_norm))

    def stop(self):
        with self._lock:
            self._j_vel = [0.0] * 6
            self._c_vel = {k: 0.0 for k in self._c_vel}

    def home(self):
        with self._lock:
            self._joints = [275.31, 167.36, 57.23, 241.09, 82.63, 75.74]
            self._j_vel  = [0.0] * 6

    def close(self):
        self._running = False
        print('[MockKinovaAPI] Simulation stopped')


# ══════════════════════════════════════════════════════════════════════════════
# Factory function — auto-selects real or mock
# ══════════════════════════════════════════════════════════════════════════════

def create_api(lib_path: str | None = None):
    """
    Create and return the best available Kinova API instance.
    Tries each search path for libkinovadrv.so; falls back to MockKinovaAPI.
    """
    paths = ([lib_path] if lib_path else []) + _LIB_SEARCH
    for path in paths:
        if path and os.path.exists(path):
            try:
                return RealKinovaAPI(path)
            except Exception as e:
                print(f'[KinovaAPI] Failed to load {path}: {e}')
    print('[KinovaAPI] SDK library not found — using simulation mode')
    return MockKinovaAPI()
