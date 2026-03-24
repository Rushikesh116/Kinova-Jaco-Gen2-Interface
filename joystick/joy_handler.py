#!/usr/bin/env python3
"""
joy_handler.py
===============
evdev-based joystick reader that runs in a background thread.
Bypasses Pygame entirely to avoid conflict with Qt5/Wayland event loops 
that produce black screens.

Returns dict identical to the old Pygame one.
"""

import threading
import time
import evdev
from evdev import ecodes

class JoystickHandler:
    POLL_HZ      = 100
    DEADZONE     = 0.08
    SMOOTH_ALPHA = 0.35

    def __init__(self, callback=None, deadzone: float = DEADZONE,
                 smooth_alpha: float = SMOOTH_ALPHA):
        self._callback     = callback
        self._deadzone     = deadzone
        self._alpha        = smooth_alpha
        self._thread       = threading.Thread(target=self._run, daemon=True)
        self._running      = False
        self._connected    = False
        self._dev          = None
        
        # 6 axes, 15 buttons to match Pygame mapped SHANWAN
        self._raw_axes     = [0.0] * 6
        self._smoothed     = [0.0] * 6
        self._buttons      = [0] * 16

        self.state = {'axes': self._smoothed, 'buttons': self._buttons, 'connected': False}
        self.invert_axes: dict[int, bool] = {}

    def start(self):
        self._running = True
        self._thread.start()

    def stop(self):
        self._running = False
        self._thread.join(timeout=2.0)

    def _run(self):
        while self._running:
            if not self._connected:
                self._try_connect()
                if not self._connected:
                    time.sleep(1.0)
                    continue

            try:
                # Non-blocking event read
                while True:
                    event = self._dev.read_one()
                    if event is None:
                        break
                    
                    if event.type == ecodes.EV_ABS:
                        self._handle_axis(event.code, event.value)
                    elif event.type == ecodes.EV_KEY:
                        self._handle_button(event.code, event.value)
                        
            except (OSError, evdev.device.EvdevError):
                self._disconnect()
            
            self._process_state()
            time.sleep(1.0 / self.POLL_HZ)

    def _handle_axis(self, code, val):
        # Map evdev standard EV_ABS to Pygame index pattern
        # ABS_X=0(LS_X), ABS_Y=1(LS_Y), ABS_Z=2(LT/L2), ABS_RX=3(RS_X), ABS_RY=4(RS_Y), ABS_RZ=5(RT/R2)
        # However, SHANWAN reports:
        # ABS_X=00, ABS_Y=01, ABS_Z=02(RS_X!), ABS_RZ=05(RS_Y!), ABS_BRAKE=0a(L2), ABS_GAS=09(R2)
        # So we map them to the 6 slots Pygame reported
        
        # Normalize -32768 to 32767 -> -1.0 to 1.0 (Sticks)
        # Normalize 0 to 255 -> -1.0 to 1.0 (Triggers)
        
        if code == ecodes.ABS_X:
            self._raw_axes[0] = val / 32768.0
        elif code == ecodes.ABS_Y:
            self._raw_axes[1] = val / 32768.0
        elif code == ecodes.ABS_Z:  # Right Stick X
            self._raw_axes[2] = val / 32768.0
        elif code == ecodes.ABS_RZ: # Right Stick Y
            self._raw_axes[3] = val / 32768.0
        elif code == ecodes.ABS_BRAKE: # L2 Trigger
            self._raw_axes[4] = (val / 127.5) - 1.0
        elif code == ecodes.ABS_GAS:   # R2 Trigger
            self._raw_axes[5] = (val / 127.5) - 1.0
            
    def _handle_button(self, code, val):
        # Map EV_KEY codes to Pygame indices (approximate mapping)
        # BTN_SOUTH=304(A), BTN_EAST=305(B), BTN_WEST=307(X=0), BTN_NORTH=308(Y=3)
        # BTN_TL=310(L1), BTN_TR=311(R1), BTN_SELECT=314(Back=6), BTN_START=315(Start=7)
        mapping = {
            ecodes.BTN_WEST: 0,   # X
            ecodes.BTN_SOUTH: 1,  # A (or 0 depending on Pygame mapping. 0=X, 3=Y in the earlier code)
            ecodes.BTN_EAST: 2,   # B
            ecodes.BTN_NORTH: 3,  # Y
            ecodes.BTN_TL: 4,     # L1
            ecodes.BTN_TR: 5,     # R1
            ecodes.BTN_SELECT: 6, # Back
            ecodes.BTN_START: 7,  # Start
            ecodes.BTN_MODE: 8,   # Guide
            ecodes.BTN_THUMBL: 9, # LS Click
            ecodes.BTN_THUMBR: 10 # RS Click
        }
        if code in mapping:
            self._buttons[mapping[code]] = val

    def _process_state(self):
        for i in range(6):
            v = self._raw_axes[i]
            if self.invert_axes.get(i, False):
                v = -v
            
            if abs(v) < self._deadzone:
                v = 0.0
            else:
                sign = 1 if v > 0 else -1
                v = sign * (abs(v) - self._deadzone) / (1.0 - self._deadzone)
                
            self._smoothed[i] = self._alpha * v + (1 - self._alpha) * self._smoothed[i]
            self._smoothed[i] = max(-1.0, min(1.0, self._smoothed[i]))

        state = {
            'axes': [round(x, 4) for x in self._smoothed],
            'buttons': list(self._buttons),
            'connected': True
        }
        self.state = state
        if self._callback:
             self._callback(state)

    def _try_connect(self):
        try:
            devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
            for dev in devices:
                if 'shanwan' in dev.name.lower() or 'gamepad' in dev.name.lower() or 'xbox' in dev.name.lower():
                    self._dev = dev
                    self._connected = True
                    print(f'[Joystick] Connected via evdev: "{dev.name}"')
                    return
        except Exception:
            pass

    def _disconnect(self):
        if self._connected:
            print('[Joystick] Disconnected (evdev)')
        self._dev = None
        self._connected = False
        self._smoothed = [0.0] * 6
        self.state = {'axes': [], 'buttons': [], 'connected': False}
