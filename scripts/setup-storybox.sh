#!/usr/bin/env bash
set -Eeuo pipefail
REPO_DIR="$(cd -- "$(dirname -- "\${BASH_SOURCE[0]}")/.." && pwd)"
CONFIGURE_WIFI=0
usage() {
  echo "Usage: sudo bash scripts/setup-storybox.sh [--configure-wifi]"
  echo "Wi-Fi changes are opt-in; --configure-wifi configures the wlan1 hotspot."
}
for arg in "$@"; do
  case "$arg" in
    --configure-wifi) CONFIGURE_WIFI=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: Unknown option: $arg"; usage; exit 2 ;;
  esac
done
if [[ "$EUID" -ne 0 ]]; then echo "Run with sudo: sudo bash scripts/setup-storybox.sh"; exit 1; fi

echo "=== StoryBox first-time setup ==="
[[ -x /usr/bin/apt-get ]] || { echo "ERROR: apt-get is required."; exit 1; }
[[ -r /etc/os-release ]] || { echo "ERROR: Cannot identify OS."; exit 1; }
. /etc/os-release
case "\${ID:-}" in debian|ubuntu|armbian) ;; *) echo "ERROR: Unsupported OS ID '\${ID:-unknown}'."; exit 1 ;; esac
MACHINE="$(uname -m)"
ARCH="$(dpkg --print-architecture)"
[[ "$MACHINE" == armv7l || "$MACHINE" == armv8l ]] || { echo "ERROR: Requires ARMv7/armv8; found $MACHINE."; exit 1; }
[[ "$ARCH" == armhf ]] || { echo "ERROR: Requires armhf userspace; found $ARCH."; exit 1; }
[[ -f /boot/armbianEnv.txt ]] || { echo "ERROR: Armbian boot configuration not found."; exit 1; }
for f in src/storybox/player/story_player.py src/storybox/local_api.py scripts/install-storybox.sh scripts/install-requirements.sh scripts/verify.sh scripts/install.sh systemd/storybox-player.service systemd/storybox-watcher.service systemd/storybox-wifi.service systemd/storybox-local-api.service; do
  [[ -f "$REPO_DIR/$f" ]] || { echo "ERROR: Missing repository file: $f"; exit 1; }
done

if id admin >/dev/null 2>&1; then
  ADMIN_HOME="$(getent passwd admin | cut -d: -f6)"
  [[ "$ADMIN_HOME" == /home/admin ]] || { echo "ERROR: Existing admin home is '$ADMIN_HOME'; expected /home/admin."; exit 1; }
  echo "Existing admin account found; preserving its password and home."
else
  [[ -t 0 && -t 1 ]] || { echo "ERROR: Creating admin requires an interactive terminal to set its password."; exit 1; }
  echo "Creating the required admin account."
  getent group sudo >/dev/null || groupadd sudo
  useradd --create-home --home-dir /home/admin --shell /bin/bash --groups sudo admin
  echo "Set a password for admin:"
  if ! passwd admin; then userdel --remove admin; echo "ERROR: Password setup failed."; exit 1; fi
fi
getent group sudo >/dev/null || groupadd sudo
usermod -aG sudo admin

echo "=== Installing StoryBox runtime, dependencies, services and permissions ==="
SUDO_USER=admin bash "$REPO_DIR/scripts/install-storybox.sh"

if [[ "$CONFIGURE_WIFI" -eq 1 ]]; then
  echo "=== Wi-Fi opt-in selected: configuring wlan1 hotspot ==="
  bash "$REPO_DIR/scripts/install.sh"
  systemctl enable storybox-wifi.service
  echo "Wi-Fi manager enabled; it will start after reboot."
else
  echo "=== Wi-Fi configuration left untouched ==="
  echo "No NetworkManager, wlan1, hostapd or dnsmasq configuration was changed."
  echo "To opt in later: sudo bash scripts/install.sh"
  echo "Then: sudo systemctl enable --now storybox-wifi.service"
fi

echo "=== Running repository verification ==="
bash "$REPO_DIR/scripts/verify.sh"
echo
echo "=== Installation stage complete ==="
echo "1. Reboot: sudo reboot"
echo "2. After reboot: cd ~/storybox && bash scripts/verify.sh --device"
echo "3. Connect the speaker and wire buttons, rotary encoder and ADS1115."
echo "4. Add stories under /home/admin/stories."
echo "5. Open http://<ORANGE-PI-IP>:8089/console on the same trusted LAN."
echo "I2C0 and supplementary group changes require reboot."
echo "Physical wiring, audio hardware and home Wi-Fi credentials remain manual."
