#!/usr/bin/env python3
"""
main.py — Entry point for the pure-Python Kinova Jaco Gen2 controller.

Usage:
    python3 main.py              # Auto-detect arm (falls back to simulation)
    python3 main.py --sim        # Force simulation mode
    python3 main.py --lib /path/to/libkinovadrv.so
"""

import sys
import os
import signal

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont, QPalette, QColor
from PyQt5.QtCore import Qt

# Ensure project root is on the path regardless of working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kinova.api         import create_api, MockKinovaAPI
from joystick.joy_handler import JoystickHandler
from gui.kinova_bridge  import KinovaBridge
from gui.main_window    import MainWindow


def apply_dark_theme(app: QApplication):
    app.setStyle('Fusion')
    p = QPalette()
    dark   = QColor(18, 18, 31)
    mid    = QColor(30, 30, 46)
    light  = QColor(55, 55, 80)
    text   = QColor(220, 220, 220)
    accent = QColor(100, 181, 246)
    p.setColor(QPalette.Window,         dark)
    p.setColor(QPalette.WindowText,     text)
    p.setColor(QPalette.Base,           QColor(13, 17, 23))
    p.setColor(QPalette.AlternateBase,  mid)
    p.setColor(QPalette.ToolTipBase,    dark)
    p.setColor(QPalette.ToolTipText,    text)
    p.setColor(QPalette.Text,           text)
    p.setColor(QPalette.Button,         mid)
    p.setColor(QPalette.ButtonText,     text)
    p.setColor(QPalette.BrightText,     Qt.red)
    p.setColor(QPalette.Highlight,      accent)
    p.setColor(QPalette.HighlightedText,QColor(0,0,0))
    p.setColor(QPalette.Link,           accent)
    p.setColor(QPalette.Midlight,       light)
    p.setColor(QPalette.Mid,            light)
    p.setColor(QPalette.Dark,           dark)
    app.setPalette(p)
    app.setStyleSheet('''
        QToolTip{background:#1e1e2e;color:#ccc;border:1px solid #444;}
        QScrollBar:vertical{background:#1a1a2e;width:8px;border-radius:4px;}
        QScrollBar::handle:vertical{background:#444;border-radius:4px;min-height:20px;}
        QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
        QScrollBar:horizontal{background:#1a1a2e;height:8px;border-radius:4px;}
        QScrollBar::handle:horizontal{background:#444;border-radius:4px;min-width:20px;}
        QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}
        QLabel{color:#ccc;} QGroupBox{color:#ccc;}
    ''')


def parse_args():
    import argparse
    p = argparse.ArgumentParser(description='Kinova Jaco Gen2 Controller')
    p.add_argument('--sim', action='store_true', help='Force simulation mode')
    p.add_argument('--lib', default=None,        help='Path to libkinovadrv.so')
    return p.parse_args()


def fix_usb_permissions():
    """
    Automatically find the Kinova USB device and ensure the user has access.
    Uses pkexec (graphical sudo prompt) or falls back to terminal sudo.
    Returns True if permissions are already OK or were successfully set.
    """
    import glob, subprocess, stat

    # Find the Kinova device (vendor ID 22cd)
    kinova_path = None
    for bus_dir in glob.glob('/dev/bus/usb/*/*'):
        try:
            # Read idVendor via sysfs
            dev_num = os.path.basename(bus_dir)
            bus_num = os.path.basename(os.path.dirname(bus_dir))
            sysfs = f'/sys/bus/usb/devices'
            vendor_files = glob.glob(f'{sysfs}/*/idVendor')
            for vf in vendor_files:
                try:
                    vendor = open(vf).read().strip()
                    if vendor == '22cd':
                        # Found Kinova — get the devnum and busnum
                        dev_dir = os.path.dirname(vf)
                        try:
                            bnum = int(open(f'{dev_dir}/busnum').read().strip())
                            dnum = int(open(f'{dev_dir}/devnum').read().strip())
                            kinova_path = f'/dev/bus/usb/{bnum:03d}/{dnum:03d}'
                            break
                        except Exception:
                            pass
                except Exception:
                    pass
            if kinova_path:
                break
        except Exception:
            pass

    if not kinova_path:
        print('[USB] Kinova arm not detected on USB — skipping permission fix')
        return False

    # Check if we already have access
    try:
        mode = os.stat(kinova_path).st_mode
        if mode & 0o006:  # world read+write already set
            print(f'[USB] Already have access to {kinova_path}')
            return True
    except Exception:
        pass

    print(f'[USB] Requesting access to {kinova_path} ...')

    # Try pkexec (graphical sudo popup — works on desktop)
    try:
        result = subprocess.run(
            ['pkexec', 'chmod', '666', kinova_path],
            timeout=30
        )
        if result.returncode == 0:
            print(f'[USB] Permission granted via pkexec!')
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: terminal sudo (works in terminal launches)
    try:
        result = subprocess.run(
            ['sudo', '-n', 'chmod', '666', kinova_path],
            timeout=5
        )
        if result.returncode == 0:
            print(f'[USB] Permission granted via sudo (cached)!')
            return True
    except Exception:
        pass

    # Last resort: ask in terminal
    print(f'[USB] Could not set USB permissions automatically.')
    print(f'[USB] Please run: sudo chmod 666 {kinova_path}')
    import getpass, subprocess as sp
    try:
        pw = getpass.getpass('[USB] Enter sudo password to grant USB access: ')
        proc = sp.run(['sudo', '-S', 'chmod', '666', kinova_path],
                      input=pw + '\n', text=True, timeout=10)
        if proc.returncode == 0:
            print('[USB] Permission granted!')
            return True
    except Exception:
        pass

    print('[USB] WARNING: Could not grant USB permissions — arm may not connect.')
    return False


def main():
    args  = parse_args()

    # ---- Qt application ----
    app = QApplication(sys.argv[:1])
    app.setApplicationName('Kinova Jaco Gen2 Controller')
    app.setApplicationVersion('1.0.0')
    app.setFont(QFont('Segoe UI', 10))
    apply_dark_theme(app)

    # ---- USB Permissions ----
    if not args.sim:
        fix_usb_permissions()

    # ---- Kinova SDK ----
    if args.sim:
        api = MockKinovaAPI()
    else:
        api = create_api(args.lib)   # returns Mock if SDK not found

    simulated = isinstance(api, MockKinovaAPI)

    # ---- Joystick ----
    joy = JoystickHandler()
    joy.start()

    # ---- Bridge ----
    bridge = KinovaBridge(api, joy)
    bridge.start()

    # ---- Main window ----
    window = MainWindow(bridge, simulated=simulated)
    window.show()

    # Allow Ctrl+C in terminal
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    exit_code = app.exec_()

    # ---- Cleanup (bridge.stop() called by window.closeEvent) ----
    joy.stop()
    
    # Hard exit to bypass Python's thread/mutex destruction exceptions that
    # occasionally occur when libusb unloads in the background.
    os._exit(exit_code)


if __name__ == '__main__':
    main()
