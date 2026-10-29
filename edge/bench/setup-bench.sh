#!/bin/bash
# setup-bench.sh: turn a fresh Pi 5 (Raspberry Pi OS Lite, user `worm`, card prepared with
# edge/burrow/prep-card.sh) into the home BENCH: always on, plugged into the home router by
# Ethernet, not behind an Opal. Three jobs:
#   1. iperf3 server always on (port 5201): the fixed point every speed test can aim at.
#   2. A USB lab for microcontrollers: Picos (picotool + mpremote), ESP (esptool), Arduinos
#      (arduino-cli), serial consoles (picocom). Boards plug into the bench, not the laptop,
#      so the AI can flash and talk to them over ssh without the laptop's routing.
#   3. Reachable always: ssh on the LAN (bench.local / its DHCP reservation) and, with a
#      Cloudflare tunnel token, from anywhere (edge/burrow/install-cloudflared.sh <token>).
# Idempotent: re-run after a git pull. Run as root on the Pi:  sudo ./setup-bench.sh
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 2; }
BENCH_USER="${SUDO_USER:-worm}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
say() { echo; echo "== $*"; }

say "packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq chrony iperf3 avahi-daemon git curl ca-certificates usbutils picocom \
  python3 python3-venv python3-pip build-essential cmake pkg-config libusb-1.0-0-dev \
  gcc-arm-none-eabi libnewlib-arm-none-eabi libstdc++-arm-none-eabi-newlib >/dev/null
systemctl enable --now iperf3 >/dev/null 2>&1 || true
systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
apt-get purge -y -qq fake-hwclock >/dev/null 2>&1 || true   # the Pi 5 RTC + chrony cover it

say "hostname bench (bench.local on the LAN)"
if [ "$(hostname)" != "bench" ]; then
  hostnamectl set-hostname bench
  sed -i 's/^127\.0\.1\.1.*/127.0.1.1\tbench/' /etc/hosts || echo -e "127.0.1.1\tbench" >> /etc/hosts
fi

say "sudo without a password for $BENCH_USER (the AI drives this box over ssh)"
echo "$BENCH_USER ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/010-bench
chmod 440 /etc/sudoers.d/010-bench
usermod -aG dialout,plugdev,gpio,i2c,spi "$BENCH_USER" 2>/dev/null || usermod -aG dialout,plugdev "$BENCH_USER"

say "udev: microcontrollers usable without root"
cat > /etc/udev/rules.d/99-bench-boards.rules <<'RULES'
# Raspberry Pi Pico / Pico 2 (W): BOOTSEL (2e8a:0003 / 000f) and MicroPython serial (2e8a:0005)
SUBSYSTEM=="usb", ATTR{idVendor}=="2e8a", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="tty", ATTRS{idVendor}=="2e8a", MODE="0666", GROUP="dialout", SYMLINK+="pico%n"
# ESP32 / ESP8266 dev boards (CP210x, CH340, FTDI) and Arduinos (official VID 2341, clones)
SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="1a86", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", ATTRS{idVendor}=="2341", MODE="0666", GROUP="dialout"
SUBSYSTEM=="usb", ATTR{idVendor}=="2341", MODE="0666", GROUP="plugdev"
# ESP32-S2/S3/C3 native USB (Espressif VID 303a) incl. download mode
SUBSYSTEM=="usb", ATTR{idVendor}=="303a", MODE="0666", GROUP="plugdev"
SUBSYSTEM=="tty", ATTRS{idVendor}=="303a", MODE="0666", GROUP="dialout"
RULES
udevadm control --reload-rules && udevadm trigger || true

say "python tools: mpremote, esptool, pyserial (venv /opt/bench/venv)"
mkdir -p /opt/bench
[ -x /opt/bench/venv/bin/python ] || python3 -m venv /opt/bench/venv
/opt/bench/venv/bin/pip install -q --upgrade pip mpremote esptool pyserial adafruit-ampy >/dev/null
for t in mpremote esptool.py pyserial-miniterm ampy; do ln -sf "/opt/bench/venv/bin/$t" "/usr/local/bin/$t" 2>/dev/null || true; done

say "picotool (built from source; apt has none)"
if ! command -v picotool >/dev/null; then
  mkdir -p /opt/bench/src && cd /opt/bench/src
  [ -d pico-sdk ] || git clone -q --depth 1 https://github.com/raspberrypi/pico-sdk.git
  [ -d picotool ] || git clone -q --depth 1 https://github.com/raspberrypi/picotool.git
  cmake -S picotool -B picotool/build -DPICO_SDK_PATH="$PWD/pico-sdk" -DPICOTOOL_FLAT_INSTALL=1 >/dev/null
  cmake --build picotool/build -j"$(nproc)" >/dev/null
  install -m 755 picotool/build/picotool /usr/local/bin/picotool
  cd "$HERE"
fi

say "arduino-cli"
if ! command -v arduino-cli >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR=/usr/local/bin sh >/dev/null
fi
sudo -u "$BENCH_USER" arduino-cli config init --overwrite >/dev/null 2>&1 || true
sudo -u "$BENCH_USER" arduino-cli core update-index >/dev/null 2>&1 || true

say "the repo for $BENCH_USER (flash.py desk loop, hwfix, bench scripts run from here)"
if [ ! -d "/home/$BENCH_USER/wormhole/.git" ]; then
  [ -d "/home/$BENCH_USER/wormhole" ] || sudo -u "$BENCH_USER" git clone -q https://github.com/MakerLabKids/whs-wormhole.git "/home/$BENCH_USER/wormhole" || true
fi

say "done"
echo "bench: $(hostname) $(hostname -I | awk '{print $1}')  iperf3=$(systemctl is-active iperf3)  picotool=$(command -v picotool || echo missing)  arduino-cli=$(command -v arduino-cli || echo missing)"
echo "next: give it a DHCP reservation on the home router; for access from anywhere run"
echo "      sudo $REPO/edge/burrow/install-cloudflared.sh <tunnel token>   (tunnel 'bench': ssh + http hostnames)"
