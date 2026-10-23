#!/usr/bin/env bash
set -Eeuo pipefail
REPO_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALL_DIR="/opt/storybox"
CONFIG_DIR="/etc/storybox"
UNIT_DIR="/etc/systemd/system"
if [[ "$EUID" -ne 0 ]]; then echo "Run with: sudo $0"; exit 1; fi
for file in src/storybox/wifi/wifi_manager.py src/storybox/wifi/portal.py src/storybox/wifi/connect_wifi.py src/storybox/player/story_player.py config/examples/hostapd.conf.example config/examples/dnsmasq.conf.example systemd/storybox-wifi.service; do
  [[ -f "$REPO_DIR/$file" ]] || { echo "ERROR: Missing repository file: $file"; exit 1; }
done
command -v nmcli >/dev/null || { echo "ERROR: NetworkManager/nmcli is required."; exit 1; }
command -v openssl >/dev/null || { echo "ERROR: openssl is required to generate a unique hotspot password."; exit 1; }
managed="$(nmcli -g GENERAL.MANAGED device show wlan0 2>/dev/null || true)"
if [[ "$managed" != "yes" ]]; then echo "ERROR: wlan0 is not managed by NetworkManager; no changes applied."; exit 1; fi
install -d -o root -g root -m 700 "$CONFIG_DIR"
install -d -o root -g root -m 755 "$INSTALL_DIR" "$INSTALL_DIR/src" "$INSTALL_DIR/config" "$INSTALL_DIR/systemd"
if [[ -f "$CONFIG_DIR/wpa_supplicant.conf" ]]; then chown root:root "$CONFIG_DIR/wpa_supplicant.conf"; chmod 600 "$CONFIG_DIR/wpa_supplicant.conf"; fi
if [[ ! -f "$CONFIG_DIR/hostapd.conf" ]]; then
  ap_password="$(openssl rand -hex 8)"
  sed "s/REPLACE_WITH_GENERATED_PASSWORD/$ap_password/" "$REPO_DIR/config/examples/hostapd.conf.example" > "$CONFIG_DIR/hostapd.conf"
  chown root:root "$CONFIG_DIR/hostapd.conf"; chmod 600 "$CONFIG_DIR/hostapd.conf"
  echo "Generated StoryBox-Setup password: $ap_password"
else
  sed -i "s/^interface=wlan0$/interface=wlan1/" "$CONFIG_DIR/hostapd.conf"
  echo "Preserving existing hostapd password and settings; enforcing interface=wlan1."
fi
if [[ ! -f "$CONFIG_DIR/dnsmasq.conf" ]]; then
  install -o root -g root -m 644 "$REPO_DIR/config/examples/dnsmasq.conf.example" "$CONFIG_DIR/dnsmasq.conf"
else
  sed -i "s/^interface=wlan0$/interface=wlan1/" "$CONFIG_DIR/dnsmasq.conf"
  echo "Preserving existing dnsmasq settings; enforcing interface=wlan1."
fi
rm -rf "$INSTALL_DIR/src/storybox"
cp -a "$REPO_DIR/src/storybox" "$INSTALL_DIR/src/"
cp -a "$REPO_DIR/config/." "$INSTALL_DIR/config/"
cp -a "$REPO_DIR/systemd/." "$INSTALL_DIR/systemd/"
find "$INSTALL_DIR/src/storybox" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$INSTALL_DIR/src/storybox" -type f -name '*.py[co]' -delete
chown -R root:root "$INSTALL_DIR"
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-wifi.service" "$UNIT_DIR/storybox-wifi.service"
# NetworkManager owns wlan0; wlan1 is the setup AP, not a station interface.
systemctl disable --now storybox-wpa.service >/dev/null 2>&1 || true
rm -f "$UNIT_DIR/storybox-wpa.service"
rm -f /etc/systemd/network/25-storybox-wlan1.network
install -d -o root -g root -m 755 /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf <<\x27EOF\x27
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF
nmcli device set wlan1 managed no >/dev/null 2>&1 || true
systemctl daemon-reload
echo
echo "StoryBox files installed without creating backups."
echo "wlan0 remains managed by NetworkManager; wlan1 is the fallback hotspot."
echo "The Wi-Fi manager was NOT restarted. Activate it when local access is available."
