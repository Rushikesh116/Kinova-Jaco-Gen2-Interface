import evdev
try:
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    for d in devices:
        print(f"PATH: {d.path} | NAME: {d.name}")
except Exception as e:
    print(f"Error reading devices: {e}")
