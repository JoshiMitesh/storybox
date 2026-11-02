#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE_USER="${SUDO_USER:-admin}"
STORIES_DIR="/home/admin/stories"
PROMPTS_DIR="/home/admin/story-prompts"
CATALOG="/home/admin/story-library.json"
INSTALL_DIR="/opt/storybox"

if [[ "$EUID" -ne 0 ]]; then
  echo "Run: sudo bash scripts/setup-device.sh"
  exit 1
fi
if [[ "$DEVICE_USER" != "admin" ]] || ! id admin >/dev/null 2>&1; then
  echo "ERROR: This setup expects the 'admin' account."
  exit 1
fi

required_files=(
  src/storybox/player/story_player.py
  src/storybox/wifi/wifi_manager.py
  src/storybox/wifi/connect_wifi.py
  src/storybox/wifi/portal.py
  scripts/storybox_watcher.py
  systemd/storybox-player.service
  systemd/storybox-watcher.service
  systemd/storybox-wifi.service
  udev/99-storybox-gpio.rules
  config/examples/hostapd.conf.example
  config/examples/dnsmasq.conf.example
)
for file in "${required_files[@]}"; do
  [[ -f "$REPO_DIR/$file" ]] || {
    echo "ERROR: Missing repository file: $file"
    exit 1
  }
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  python3 mpv gpiod ffmpeg alsa-utils \
  network-manager hostapd dnsmasq iw rfkill

command -v gpiomon >/dev/null
gpiomon --help 2>&1 | grep -q -- '-c' || {
  echo "ERROR: gpiomon must support the -c option."
  exit 1
}

if [[ ! -x /opt/piper/piper || ! -f /opt/piper/models/en_US-lessac-medium.onnx ]]; then
  echo "ERROR: Piper/model missing."
  echo "Install ARMv7 Piper at /opt/piper/piper and the model at"
  echo "/opt/piper/models/en_US-lessac-medium.onnx before running setup."
  exit 1
fi

getent group gpio >/dev/null || groupadd --system gpio
usermod -aG gpio,audio admin

install -d -o root -g root -m 755 \
  "$INSTALL_DIR/src/storybox/player" \
  "$INSTALL_DIR/src/storybox/wifi" \
  "$INSTALL_DIR/scripts"
install -d -o admin -g admin -m 755 "$STORIES_DIR" "$PROMPTS_DIR"
install -d -o root -g root -m 755 /etc/storybox /etc/NetworkManager/conf.d

install -o root -g root -m 644 "$REPO_DIR/src/storybox/player/story_player.py" \
  "$INSTALL_DIR/src/storybox/player/story_player.py"
install -o root -g root -m 644 "$REPO_DIR/src/storybox/wifi/wifi_manager.py" \
  "$INSTALL_DIR/src/storybox/wifi/wifi_manager.py"
install -o root -g root -m 644 "$REPO_DIR/src/storybox/wifi/connect_wifi.py" \
  "$INSTALL_DIR/src/storybox/wifi/connect_wifi.py"
install -o root -g root -m 644 "$REPO_DIR/src/storybox/wifi/portal.py" \
  "$INSTALL_DIR/src/storybox/wifi/portal.py"
install -o root -g root -m 755 "$REPO_DIR/scripts/storybox_watcher.py" \
  "$INSTALL_DIR/scripts/storybox_watcher.py"

if [[ ! -f "$CATALOG" ]]; then
  printf '[]\n' > "$CATALOG"
fi
chown admin:admin "$CATALOG"
chmod 664 "$CATALOG"

# Keep wlan0 under NetworkManager for saved home Wi-Fi profiles.
# Reserve wlan1 for hostapd/dnsmasq; do not touch existing wlan0 credentials.
cat > /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf <<'NMCONF'
[keyfile]
unmanaged-devices=interface-name:wlan1
NMCONF
chmod 644 /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf

# Use a unique WPA2 password for this device's setup hotspot.
HOTSPOT_PASSWORD="$(python3 -c 'import secrets,string; print("".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(18)))')"
sed -E "s/^wpa_passphrase=.*/wpa_passphrase=${HOTSPOT_PASSWORD}/" \
  "$REPO_DIR/config/examples/hostapd.conf.example" > /etc/storybox/hostapd.conf
install -o root -g root -m 600 /etc/storybox/hostapd.conf /etc/storybox/hostapd.conf
install -o root -g root -m 644 "$REPO_DIR/config/examples/dnsmasq.conf.example" \
  /etc/storybox/dnsmasq.conf

# The manager launches its own hostapd/dnsmasq processes on demand.
# Disable package-wide daemons to avoid conflicts with the fallback manager.
systemctl disable --now hostapd.service dnsmasq.service >/dev/null 2>&1 || true
systemctl enable NetworkManager.service
nmcli radio wifi on || true

install -o root -g root -m 644 "$REPO_DIR/udev/99-storybox-gpio.rules" \
  /etc/udev/rules.d/99-storybox-gpio.rules
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-player.service" \
  /etc/systemd/system/storybox-player.service
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-watcher.service" \
  /etc/systemd/system/storybox-watcher.service
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-wifi.service" \
  /etc/systemd/system/storybox-wifi.service

udevadm control --reload-rules
udevadm trigger --subsystem-match=gpio || true
systemctl daemon-reload
systemctl enable storybox-player.service storybox-watcher.service storybox-wifi.service

echo
echo "StoryBox device setup completed."
echo "Wi-Fi: wlan0=home Wi-Fi (NetworkManager), wlan1=setup hotspot."
echo "Setup portal: http://192.168.4.1/"
echo "Hotspot SSID: StoryBox-Setup"
echo "Hotspot password (keep it safe): $HOTSPOT_PASSWORD"
echo
echo "Existing NetworkManager home Wi-Fi profiles were not deleted or changed."
echo "Reboot required: sudo reboot"
