#!/usr/bin/env bash
# install_sdk.sh — Install the Kinova Jaco Gen2 SDK (libkinovadrv.so)
# Run as: sudo bash install_sdk.sh
# Requires internet connection.
set -e

# Disable any git interactive prompts that cause hanging
export GIT_TERMINAL_PROMPT=0

echo "=== Kinova Jaco Gen2 SDK Installer ==="
WORK=/tmp/kinova_sdk_install
mkdir -p "$WORK"
cd "$WORK"

echo "[1/4] Downloading Kinova SDK (safe non-interactive clone)..."
if [ -d kinova-ros ]; then
    rm -rf kinova-ros
fi
# Use kinova-ros which we know is public and contains the SDK binaries
git clone --depth 1 https://github.com/Kinovarobotics/kinova-ros.git || {
    echo "ERROR: Failed to clone kinova-ros. Ensure internet connection is active."
    exit 1
}

echo "[2/4] Copying 64-bit library..."
SDK_LIB="kinova-ros/kinova_driver/lib/x86_64-linux-gnu/USBCommandLayerUbuntu.so"
if [ ! -f "$SDK_LIB" ]; then
    echo "ERROR: Library not found in cloned repo."
    exit 1
fi
sudo cp "$SDK_LIB" /usr/lib/libkinovadrv.so
sudo ldconfig

echo "[3/4] Installing udev rules (USB access)..."
RULES="kinova-ros/kinova_driver/udev/10-kinova-arm.rules"
if [ -f "$RULES" ]; then
    sudo cp "$RULES" /etc/udev/rules.d/
    sudo udevadm control --reload-rules && sudo udevadm trigger
else
    # Fallback: write rule manually
    echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="22cd", MODE="0666"' \
        | sudo tee /etc/udev/rules.d/99-kinova.rules > /dev/null
    sudo udevadm control --reload-rules && sudo udevadm trigger
fi

echo "[4/4] Verifying installation..."
if ldconfig -p | grep -q libkinovadrv; then
    echo "✅ libkinovadrv.so installed successfully!"
else
    echo "⚠ Library not found in ldconfig cache — may need to reconnect USB."
fi

echo ""
echo "Next steps:"
echo "  1. Plug in the Kinova arm via USB"
echo "  2. cd ~/kinova_ws/kinova_controller && python3 main.py"
