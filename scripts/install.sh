#!/usr/bin/env bash
set -Eeuo pipefail

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_DIR="/opt/storybox"
CONFIG_DIR="/etc/storybox"
UNIT_DIR="/etc/systemd/system"
BACKUP_DIR="/var/backups/storybox-install-$(date +%Y%m%d-%H%M%S)"

if [[ "$EUID" -ne 0 ]]; then
    echo "Run with: sudo $0"
    exit 1
fi

# Check all required repository files before making system changes.
for file in \
    src/storybox/wifi/wifi_manager.py \
    src/storybox/wifi/portal.py \
    src/storybox/wifi/connect_wifi.py \
    src/storybox/player/story_player.py \
    config/examples/hostapd.conf.example \
    config/examples/dnsmasq.conf.example \
    systemd/storybox-wifi.service \
    systemd/storybox-wpa.service
do
    [[ -f "$REPO_DIR/$file" ]] || {
        echo "ERROR: Missing repository file: $file"
        exit 1
    }
done

# Ensure we can preserve the current working device configuration.
if [[ ! -f "$CONFIG_DIR/wpa_supplicant.conf" ]]; then
    echo "ERROR: Missing $CONFIG_DIR/wpa_supplicant.conf"
    echo "Refusing to replace or regenerate saved Wi-Fi credentials."
    exit 1
fi

if [[ ! -f "$CONFIG_DIR/hostapd.conf" &&
      ! -f /home/admin/storybox-hotspot.conf ]]; then
    echo "ERROR: No existing hotspot configuration to preserve."
    exit 1
fi

if [[ ! -f "$CONFIG_DIR/dnsmasq.conf" &&
      ! -f /home/admin/storybox-dnsmasq.conf ]]; then
    echo "ERROR: No existing dnsmasq configuration to preserve."
    exit 1
fi

echo "Preflight checks passed."
echo "Repository: $REPO_DIR"
echo "Install path: $INSTALL_DIR"
echo "No services will be restarted."

install -d -o root -g root -m 700 "$BACKUP_DIR"

# Back up the existing application before changing it.
if [[ -d "$INSTALL_DIR" ]]; then
    cp -a "$INSTALL_DIR" "$BACKUP_DIR/opt-storybox"
fi

# Back up the existing service unit definitions.
for unit in storybox-wifi.service storybox-wpa.service; do
    if [[ -f "$UNIT_DIR/$unit" ]]; then
        cp -a "$UNIT_DIR/$unit" "$BACKUP_DIR/$unit"
    fi
done

install -d -o root -g root -m 755 "$CONFIG_DIR"

# Preserve existing device-specific configuration; never overwrite it.
if [[ ! -e "$CONFIG_DIR/hostapd.conf" ]]; then
    install -o root -g root -m 600 \
        /home/admin/storybox-hotspot.conf \
        "$CONFIG_DIR/hostapd.conf"
fi

if [[ ! -e "$CONFIG_DIR/dnsmasq.conf" ]]; then
    install -o root -g root -m 644 \
        /home/admin/storybox-dnsmasq.conf \
        "$CONFIG_DIR/dnsmasq.conf"
fi

chown root:root "$CONFIG_DIR/wpa_supplicant.conf"
chmod 600 "$CONFIG_DIR/wpa_supplicant.conf"

# Replace only the application source tree, preserving other installation
# contents. The previous installation has already been backed up.
install -d -o root -g root -m 755 \
    "$INSTALL_DIR" "$INSTALL_DIR/src" \
    "$INSTALL_DIR/config" "$INSTALL_DIR/systemd"

rm -rf "$INSTALL_DIR/src/storybox"
cp -a "$REPO_DIR/src/storybox" "$INSTALL_DIR/src/"

# Remove generated Python cache files from the installed source.
find "$INSTALL_DIR/src/storybox" \
    -type d -name __pycache__ -prune -exec rm -rf {} +
find "$INSTALL_DIR/src/storybox" \
    -type f -name '*.py[co]' -delete

cp -a "$REPO_DIR/config/." "$INSTALL_DIR/config/"
cp -a "$REPO_DIR/systemd/." "$INSTALL_DIR/systemd/"
chown -R root:root "$INSTALL_DIR"

install -o root -g root -m 644 \
    "$REPO_DIR/systemd/storybox-wifi.service" \
    "$UNIT_DIR/storybox-wifi.service"

install -o root -g root -m 644 \
    "$REPO_DIR/systemd/storybox-wpa.service" \
    "$UNIT_DIR/storybox-wpa.service"

systemctl daemon-reload

echo
echo "Installation files prepared successfully."
echo "Backup location: $BACKUP_DIR"
echo "Services were NOT restarted."
echo "Verify service definitions before scheduling any restart."
