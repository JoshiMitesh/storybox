#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
DEVICE_USER="${SUDO_USER:-admin}"
if [[ "$EUID" -ne 0 ]]; then
  echo "Run with: sudo bash scripts/install-requirements.sh"
  exit 1
fi
if ! id "$DEVICE_USER" >/dev/null 2>&1; then
  echo "ERROR: Expected device user '$DEVICE_USER' does not exist."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
echo "=== Updating apt package lists ==="
apt-get update

echo "=== Installing StoryBox runtime and build/test requirements ==="
apt-get install -y --no-install-recommends \
  python3 python3-pip python3-venv python3-smbus python3-libgpiod \
  mpv gpiod ffmpeg alsa-utils i2c-tools \
  network-manager hostapd dnsmasq iw iproute2 \
  libatomic1 libstdc++6 libgcc-s1 libgomp1 \
  git curl ca-certificates tar gzip file binutils \
  udev

echo "=== Checking GPIO command support ==="
command -v gpiomon >/dev/null
if ! gpiomon --help 2>&1 | grep -- '-c' >/dev/null; then
  echo "ERROR: Installed gpiomon does not expose the required -c option."
  exit 1
fi

echo "=== Checking Python hardware modules ==="
/usr/bin/python3 -c 'import gpiod, smbus; print("gpiod and smbus imports OK")'

if [[ -f "$REPO_DIR/requirements-dev.txt" ]]; then
  DEVICE_HOME="$(getent passwd "$DEVICE_USER" | cut -d: -f6)"
  VENV="$REPO_DIR/.venv"
  if [[ ! -x "$VENV/bin/python" ]]; then
    echo "=== Creating project virtual environment for development requirements ==="
    runuser -u "$DEVICE_USER" -- python3 -m venv --system-site-packages "$VENV"
  fi
  chown -R "$DEVICE_USER:$DEVICE_USER" "$VENV"
  echo "=== Installing Python development requirements in .venv ==="
  runuser -u "$DEVICE_USER" -- env HOME="$DEVICE_HOME" \
    "$VENV/bin/python" -m pip install --disable-pip-version-check \
    -r "$REPO_DIR/requirements-dev.txt"
else
  echo "No requirements-dev.txt found; skipping the development virtual environment."
fi

echo
echo "Requirements installation completed."
echo "Runtime Python modules are installed through apt; pip is used only inside .venv."
