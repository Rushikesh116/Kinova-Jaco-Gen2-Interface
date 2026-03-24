#!/usr/bin/env python3
"""
arm_3d_panel.py — Real-time 3D visualisation of the Kinova Jaco Gen2 arm.

Uses only PyQt5 (QPainter) — zero additional dependencies.
Renders the arm via forward kinematics from the live joint angles
received through the bridge's arm_state_received signal.

Camera: soft perspective projection.
Controls: left-click drag → orbit,  scroll wheel → zoom.
"""

import math
import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt5.QtCore import Qt, pyqtSlot, QPointF, QPoint
from PyQt5.QtGui import (QPainter, QColor, QPen, QBrush, QLinearGradient,
                          QRadialGradient, QPainterPath, QFont, QFontMetrics)

# ── Jaco Gen2 DH parameters (SI: metres, radians) ──────────────────────────
# Using classic DH convention:  T = Rz(θ) · Tz(d) · Tx(a) · Rx(α)
# Reference: Kinova Jaco2 Technical Specifications
_D1 = 0.2755   # base  → joint-1  (height of shoulder)
_A2 = 0.4100   # joint-1 → joint-2 shoulder link
_A3 = 0.2073   # joint-2 → joint-3 elbow link
_D4 = 0.3073   # joint-3 → joint-4 forearm length
_D6 = 0.1700   # joint-5 → end-effector

# (a,  d,    alpha,    theta_offset)
_DH = [
    (0,     _D1,  -math.pi/2,   0),          # joint 1
    (_A2,   0,     math.pi,     math.pi),    # joint 2
    (_A3,   0,     math.pi/2,   math.pi),    # joint 3
    (0,    -_D4,   math.pi/2,   0),          # joint 4
    (0,     0,    -math.pi/2,   math.pi),    # joint 5
    (0,    -_D6,   0,           math.pi/2),  # joint 6
]

# Colours for each link segment
_LINK_COLORS = [
    QColor(100, 181, 246),   # J1–J2  sky blue
    QColor(129, 199, 132),   # J2–J3  green
    QColor(255, 183, 77),    # J3–J4  amber
    QColor(240, 98,  146),   # J4–J5  pink
    QColor(179, 136, 255),   # J5–J6  purple
    QColor(77,  208, 225),   # J6–EE  cyan
]

_JOINT_COLOR   = QColor(255, 255, 255, 220)
_EE_COLOR      = QColor(255, 100, 100)
_BG_TOP        = QColor(12, 12, 24)
_BG_BOT        = QColor(20, 20, 40)
_GRID_COLOR    = QColor(50, 50, 80, 120)
_AXIS_X        = QColor(255, 80,  80)
_AXIS_Y        = QColor(80,  255, 80)
_AXIS_Z        = QColor(80,  80,  255)


def _dh_matrix(a, d, alpha, theta):
    """Homogeneous 4×4 DH transform."""
    ct, st = math.cos(theta), math.sin(theta)
    ca, sa = math.cos(alpha),  math.sin(alpha)
    return np.array([
        [ct, -st*ca,  st*sa,  a*ct],
        [st,  ct*ca, -ct*sa,  a*st],
        [0,   sa,     ca,     d   ],
        [0,   0,      0,      1   ],
    ], dtype=float)


def forward_kinematics(joint_angles_deg):
    """
    Compute 3D positions of all joints + end effector.
    joint_angles_deg: list of 6 floats (degrees).
    Returns list of 7 np.array([x,y,z]) points:
        [base, J1, J2, J3, J4, J5, EE]
    """
    angles_rad = [math.radians(a) for a in joint_angles_deg]
    T = np.eye(4)
    points = [np.array([0.0, 0.0, 0.0])]
    for i, (a, d, alpha, offset) in enumerate(_DH):
        T = T @ _dh_matrix(a, d, alpha, angles_rad[i] + offset)
        points.append(T[:3, 3].copy())
    return points


# ── Projection helpers ──────────────────────────────────────────────────────

def _rot_x(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[1,0,0],[0,c,-s],[0,s,c]], dtype=float)

def _rot_z(angle):
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c,-s,0],[s,c,0],[0,0,1]], dtype=float)


class ArmVisualizer3DPanel(QWidget):
    """
    3D visualisation of the Kinova Jaco Gen2 arm.
    Subscribe to: bridge.signals.arm_state_received → update_arm_state
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(400, 400)

        # Camera state
        self._azimuth  = -45.0   # degrees around Z
        self._elevation = 25.0   # degrees above horizontal
        self._zoom      = 360.0  # pixels per metre
        self._last_pos  = None

        # Arm state
        self._joints = [0.0] * 6   # degrees — updated by signal
        self._points = forward_kinematics(self._joints)

        # Build a minimal inner layout (info bar)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        info_bar = QHBoxLayout()
        info_bar.setContentsMargins(8, 4, 8, 4)

        title = QLabel('🦾  3D Arm Visualizer — Kinova Jaco Gen2')
        title.setStyleSheet('color:#64b5f6;font-size:13px;font-weight:bold;')
        info_bar.addWidget(title)
        info_bar.addStretch()

        self._info_lbl = QLabel('Drag to rotate  •  Scroll to zoom')
        self._info_lbl.setStyleSheet('color:#555;font-size:11px;')
        info_bar.addWidget(self._info_lbl)

        reset_btn = QPushButton('⟳ Reset View')
        reset_btn.setFixedHeight(24)
        reset_btn.setStyleSheet('QPushButton{background:#1e1e3a;color:#888;border:1px solid #333;'
                                 'border-radius:4px;font-size:11px;padding:0 8px;}'
                                 'QPushButton:hover{color:#ccc;}')
        reset_btn.clicked.connect(self._reset_view)
        info_bar.addWidget(reset_btn)

        outer.addLayout(info_bar)
        # The rest is drawn in paintEvent

        self.setMouseTracking(True)

    # ── Public slot ─────────────────────────────────────────────────────────

    @pyqtSlot(dict)
    def update_arm_state(self, state):
        joints = state.get('joint_positions', [0.0]*6)
        if len(joints) >= 6:
            self._joints = list(joints[:6])
            self._points = forward_kinematics(self._joints)
            self.update()

    # ── Camera controls ─────────────────────────────────────────────────────

    def _reset_view(self):
        self._azimuth, self._elevation, self._zoom = -45.0, 25.0, 360.0
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._last_pos = e.pos()

    def mouseMoveEvent(self, e):
        if self._last_pos and (e.buttons() & Qt.LeftButton):
            dx = e.x() - self._last_pos.x()
            dy = e.y() - self._last_pos.y()
            self._azimuth   += dx * 0.4
            self._elevation -= dy * 0.4
            self._elevation  = max(-89, min(89, self._elevation))
            self._last_pos   = e.pos()
            self.update()

    def mouseReleaseEvent(self, e):
        self._last_pos = None

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        self._zoom *= 1.0 + delta / 1200.0
        self._zoom  = max(80, min(1200, self._zoom))
        self.update()

    # ── 3D → 2D projection ──────────────────────────────────────────────────

    def _project(self, pt3, cx, cy):
        """Project world-space 3D point to screen 2D."""
        az  = math.radians(self._azimuth)
        el  = math.radians(self._elevation)
        R   = _rot_x(-el) @ _rot_z(az)
        p   = R @ np.array(pt3)
        # simple perspective (focal = zoom, camera at z=3m)
        z_cam = p[2] + 3.0
        if z_cam < 0.01:
            z_cam = 0.01
        fov   = self._zoom
        sx    = cx + fov * p[0] / z_cam * 1.4
        sy    = cy - fov * p[1] / z_cam * 1.4
        depth = p[2]
        return QPointF(sx, sy), depth

    # ── Rendering ───────────────────────────────────────────────────────────

    def paintEvent(self, _):
        w, h  = self.width(), self.height()
        cx    = w / 2
        cy    = h / 2 + 40   # shift centre down a bit for better framing

        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)

        # ── Background gradient ──────────────────────────────────────────
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, _BG_TOP)
        grad.setColorAt(1, _BG_BOT)
        qp.fillRect(0, 0, w, h, grad)

        # ── Grid floor (z = 0 plane) ─────────────────────────────────────
        self._draw_grid(qp, cx, cy)

        # ── Coordinate axes ──────────────────────────────────────────────
        self._draw_axes(qp, cx, cy)

        # ── Arm ──────────────────────────────────────────────────────────
        pts_2d = [(self._project(p, cx, cy)) for p in self._points]

        # Draw link tubes (with depth-sorted painter's trick)
        for i in range(len(self._points) - 1):
            p0, d0 = pts_2d[i]
            p1, d1 = pts_2d[i + 1]
            depth = (d0 + d1) / 2
            col   = _LINK_COLORS[i] if i < len(_LINK_COLORS) else QColor(200, 200, 200)
            self._draw_link(qp, p0, p1, col, width=11 - i, depth=depth)

        # Draw joint spheres
        for i, (p2d, depth) in enumerate(pts_2d):
            if i == len(pts_2d) - 1:
                # End effector
                self._draw_sphere(qp, p2d, 9, _EE_COLOR, label='EE')
            elif i == 0:
                self._draw_sphere(qp, p2d, 12, QColor(180, 180, 180), label='Base')
            else:
                self._draw_sphere(qp, p2d, 9, _JOINT_COLOR, label=f'J{i}')

        # ── Joint angle readout ──────────────────────────────────────────
        self._draw_joint_readout(qp, w, h)

        qp.end()

    def _draw_grid(self, qp, cx, cy):
        pen = QPen(_GRID_COLOR, 1)
        qp.setPen(pen)
        n, step = 8, 0.15
        for i in range(-n, n+1):
            # lines along X
            p0, _ = self._project([i*step, -n*step, 0], cx, cy)
            p1, _ = self._project([i*step,  n*step, 0], cx, cy)
            qp.drawLine(p0, p1)
            # lines along Y
            p0, _ = self._project([-n*step, i*step, 0], cx, cy)
            p1, _ = self._project([ n*step, i*step, 0], cx, cy)
            qp.drawLine(p0, p1)

    def _draw_axes(self, qp, cx, cy):
        origin = [0, 0, 0]
        ax_len = 0.18
        for vec, col, lbl in [([ax_len,0,0], _AXIS_X, 'X'),
                                ([0,ax_len,0], _AXIS_Y, 'Y'),
                                ([0,0,ax_len], _AXIS_Z, 'Z')]:
            p0, _ = self._project(origin, cx, cy)
            p1, _ = self._project(vec, cx, cy)
            qp.setPen(QPen(col, 2))
            qp.drawLine(p0, p1)
            qp.setPen(QPen(col, 1))
            qp.setFont(QFont('', 9, QFont.Bold))
            qp.drawText(p1 + QPointF(4, 0), lbl)

    def _draw_link(self, qp, p0, p1, color, width=8, depth=0.0):
        """Draw a thick coloured line representing an arm link."""
        # Shadow
        shadow = QPen(QColor(0, 0, 0, 60), width + 4, Qt.SolidLine, Qt.RoundCap)
        qp.setPen(shadow)
        qp.drawLine(p0 + QPointF(2, 2), p1 + QPointF(2, 2))
        # Main
        bright = color.lighter(130)
        pen = QPen(bright, width, Qt.SolidLine, Qt.RoundCap)
        qp.setPen(pen)
        qp.drawLine(p0, p1)
        # Highlight (thinner, lighter line offset slightly)
        hi = QPen(QColor(255, 255, 255, 60), max(1, width // 3), Qt.SolidLine, Qt.RoundCap)
        qp.setPen(hi)
        off = QPointF(-1, -1)
        qp.drawLine(p0 + off, p1 + off)

    def _draw_sphere(self, qp, pos, radius, color, label=''):
        """Draw a glowing sphere at pos."""
        # Outer glow
        glow = QRadialGradient(pos, radius * 2.5)
        glow.setColorAt(0, QColor(color.red(), color.green(), color.blue(), 80))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        qp.setPen(Qt.NoPen)
        qp.setBrush(QBrush(glow))
        qp.drawEllipse(pos, radius * 2.5, radius * 2.5)

        # Main sphere
        grad = QRadialGradient(pos + QPointF(-radius*0.3, -radius*0.3), radius)
        grad.setColorAt(0, color.lighter(160))
        grad.setColorAt(0.6, color)
        grad.setColorAt(1, color.darker(160))
        qp.setBrush(QBrush(grad))
        qp.setPen(QPen(color.darker(120), 1))
        qp.drawEllipse(pos, radius, radius)

        # Label
        if label:
            qp.setFont(QFont('', 8))
            qp.setPen(QPen(QColor(200, 200, 200, 180), 1))
            qp.drawText(pos + QPointF(radius + 3, 4), label)

    def _draw_joint_readout(self, qp, w, h):
        """Draw the 6 joint angle values in the corner."""
        qp.setFont(QFont('Courier', 9))
        x0, y0 = 12, 36
        qp.setPen(QPen(QColor(40, 40, 60, 180), 1))
        qp.setBrush(QBrush(QColor(10, 10, 20, 160)))
        qp.drawRoundedRect(x0 - 6, y0 - 16, 160, len(self._joints)*16 + 10, 6, 6)
        for i, ang in enumerate(self._joints):
            col = _LINK_COLORS[i] if i < len(_LINK_COLORS) else QColor(200, 200, 200)
            qp.setPen(QPen(col, 1))
            qp.drawText(x0, y0 + i * 16, f'J{i+1}: {ang:+7.2f}°')
