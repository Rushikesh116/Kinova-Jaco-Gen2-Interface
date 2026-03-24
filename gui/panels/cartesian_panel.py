#!/usr/bin/env python3
"""
cartesian_panel.py — Cartesian Control (KinovaBridge version)
Controls EE pose in task space, joystick → velocity commands in m/s & deg/s.
"""
import math
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QPushButton, QGroupBox, QComboBox
)
from PyQt5.QtCore import Qt, pyqtSlot, QTimer

DOFS = [
    {'name':'X',     'linear':True,  'joy_axis':0, 'inv':False},
    {'name':'Y',     'linear':True,  'joy_axis':1, 'inv':True },
    {'name':'Z',     'linear':True,  'joy_axis':4, 'inv':True },
    {'name':'Roll',  'linear':False, 'joy_axis':2, 'inv':False},
    {'name':'Pitch', 'linear':False, 'joy_axis':5, 'inv':False},
    {'name':'Yaw',   'linear':False, 'joy_axis':3, 'inv':False},
]
MAX_LINEAR  = 0.15   # m/s at 100% speed (bridge applies speed-scale)
MAX_ANGULAR = 40.0   # deg/s at 100% speed
STEP_LIN    = [0.001, 0.005, 0.01, 0.05]
STEP_ANG    = [0.5, 1.0, 5.0, 10.0]


class CartesianPanel(QWidget):
    def __init__(self, bridge, safety_panel, parent=None):
        super().__init__(parent)
        self._bridge    = bridge
        self._safety    = safety_panel
        self._joy_axes  = [0.0]*6
        self._build_ui()

        self._cmd_timer = QTimer(self)
        self._cmd_timer.setInterval(10)   # 100 Hz — matches kinova-ros driver
        self._cmd_timer.timeout.connect(self._send_velocity)
        self._cmd_timer.start()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12,12,12,12)
        layout.setSpacing(10)

        hdr = QLabel('📍  Cartesian Control Mode')
        hdr.setStyleSheet('color:#a5d6a7;font-size:16px;font-weight:bold;')
        layout.addWidget(hdr)

        hint = QLabel('Left stick→X/Y  |  Right stick Y→Z  |  Triggers→Roll/Pitch  |  Right stick X→Yaw')
        hint.setStyleSheet('color:#888;font-size:11px;')
        layout.addWidget(hint)

        cols = QHBoxLayout()
        cols.addWidget(self._build_feedback_group(), stretch=1)
        cols.addWidget(self._build_velocity_group(), stretch=1)
        layout.addLayout(cols)
        layout.addWidget(self._build_manual_group())

        joy_row = QHBoxLayout()
        jl = QLabel('Joystick:'); jl.setStyleSheet('color:#888;font-size:11px;')
        joy_row.addWidget(jl)
        self._joy_lbl = QLabel('—'); self._joy_lbl.setStyleSheet('color:#a5d6a7;font-size:11px;')
        joy_row.addWidget(self._joy_lbl); joy_row.addStretch()
        layout.addLayout(joy_row)
        layout.addStretch()

    def _build_feedback_group(self):
        g = QGroupBox('Current Pose (Feedback)'); g.setStyleSheet(self._grp())
        grid = QGridLayout(g)
        self._cur = {}
        for i,(n,u) in enumerate([('X','m'),('Y','m'),('Z','m'),('Roll','°'),('Pitch','°'),('Yaw','°')]):
            ll = QLabel(f'{n}:'); ll.setStyleSheet('color:#aaa;font-size:12px;')
            vl = QLabel('0.000'); vl.setStyleSheet('color:#80cbc4;font-size:13px;font-weight:bold;')
            vl.setAlignment(Qt.AlignRight)
            ul = QLabel(u); ul.setStyleSheet('color:#666;font-size:11px;')
            grid.addWidget(ll,i,0); grid.addWidget(vl,i,1); grid.addWidget(ul,i,2)
            self._cur[n] = vl
        return g

    def _build_velocity_group(self):
        g = QGroupBox('Velocity Preview'); g.setStyleSheet(self._grp())
        grid = QGridLayout(g)
        self._vel = {}
        for i,(n,u) in enumerate([('vX','m/s'),('vY','m/s'),('vZ','m/s'),('ωX','°/s'),('ωY','°/s'),('ωZ','°/s')]):
            ll = QLabel(f'{n}:'); ll.setStyleSheet('color:#aaa;font-size:12px;')
            vl = QLabel('0.000'); vl.setStyleSheet('color:#ffcc80;font-size:13px;font-weight:bold;')
            vl.setAlignment(Qt.AlignRight)
            ul = QLabel(u); ul.setStyleSheet('color:#666;font-size:11px;')
            grid.addWidget(ll,i,0); grid.addWidget(vl,i,1); grid.addWidget(ul,i,2)
            self._vel[n] = vl
        return g

    def _build_manual_group(self):
        g = QGroupBox('Manual Step'); g.setStyleSheet(self._grp())
        grid = QGridLayout(g); grid.setSpacing(4)

        sr = QHBoxLayout()
        sr.addWidget(QLabel('Linear:'))
        self._ls = QComboBox()
        [self._ls.addItem(f'{v*1000:.1f}mm',v) for v in STEP_LIN]; self._ls.setCurrentIndex(2)
        self._ls.setStyleSheet('background:#1a1a2e;color:#ccc;border:1px solid #444;')
        sr.addWidget(self._ls); sr.addSpacing(16); sr.addWidget(QLabel('Angular:'))
        self._as = QComboBox()
        [self._as.addItem(f'{v:.1f}°',v) for v in STEP_ANG]; self._as.setCurrentIndex(1)
        self._as.setStyleSheet('background:#1a1a2e;color:#ccc;border:1px solid #444;')
        sr.addWidget(self._as); sr.addStretch()
        sw = QWidget(); sw.setLayout(sr)
        grid.addWidget(sw, 0, 0, 1, 6)

        colours = ['#ef9a9a','#a5d6a7','#90caf9','#ce93d8','#ffcc80','#80deea']
        for col,(d,c) in enumerate(zip(DOFS, colours)):
            nl = QLabel(d['name']); nl.setAlignment(Qt.AlignCenter)
            nl.setStyleSheet(f'color:{c};font-size:12px;font-weight:bold;')
            grid.addWidget(nl, 1, col)
            pb = QPushButton('▲'); pb.setFixedHeight(26)
            pb.setStyleSheet(self._btn(c))
            pb.clicked.connect(lambda _, i=col: self._manual_step(i, +1))
            grid.addWidget(pb, 2, col)
            mb = QPushButton('▼'); mb.setFixedHeight(26)
            mb.setStyleSheet(self._btn(c))
            mb.clicked.connect(lambda _, i=col: self._manual_step(i, -1))
            grid.addWidget(mb, 3, col)
        return g

    @pyqtSlot(dict)
    def update_arm_state(self, state):
        pos = state.get('ee_position', [0,0,0])
        rpy = state.get('ee_orientation', [0,0,0])
        for n,v,f in zip(['X','Y','Z','Roll','Pitch','Yaw'], pos+rpy,
                          ['.4f','.4f','.4f','.1f','.1f','.1f']):
            self._cur[n].setText(f'{v:{f}}')

    @pyqtSlot(dict)
    def update_joy(self, joy):
        axes = joy.get('axes', [])
        for i,d in enumerate(DOFS):
            ax = d['joy_axis']
            v  = (axes[ax] if ax < len(axes) else 0.0) * (-1 if d['inv'] else 1)
            self._joy_axes[i] = v
        self._joy_lbl.setText('  '.join(f'{d["name"]}:{v:+.2f}' for d,v in zip(DOFS,self._joy_axes)))

    def _send_velocity(self):
        if not self.isVisible():
            return
            
        # Don't apply safety scale here — bridge applies it
        lin = [self._joy_axes[i] * MAX_LINEAR  for i in range(3)]
        ang = [self._joy_axes[i] * MAX_ANGULAR for i in range(3,6)]
        for n,v in zip(['vX','vY','vZ','ωX','ωY','ωZ'], lin+ang):
            self._vel[n].setText(f'{v:+.4f}')
        # Always send (zeros stop the arm immediately)
        self._bridge.publish_cartesian_velocity(lin, ang)

    def _manual_step(self, dof, direction):
        if dof < 3:
            lin = [0.0,0.0,0.0]; lin[dof] = direction*self._ls.currentData()/0.1
            self._bridge.publish_cartesian_velocity(lin, [0,0,0])
        else:
            ang = [0.0,0.0,0.0]; ang[dof-3] = direction*math.degrees(self._as.currentData()/0.1)
            self._bridge.publish_cartesian_velocity([0,0,0], ang)
        QTimer.singleShot(100, self._bridge.publish_zero_velocity)

    @staticmethod
    def _grp():
        return ('QGroupBox{color:#ccc;border:1px solid #444;border-radius:6px;'
                'margin-top:8px;font-size:13px;}'
                'QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}')

    @staticmethod
    def _btn(c):
        return (f'QPushButton{{background:#1e293b;color:{c};border:1px solid #444;'
                f'border-radius:4px;font-size:13px;}}'
                f'QPushButton:hover{{background:#263548;}}')
