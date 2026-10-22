#!/usr/bin/env bash
# One-command provisioning for a FRESH StoryBox Orange Pi PC Plus.
# Run from the repository root: sudo bash scripts/provision-device.sh
set -Eeuo pipefail
umask 077

REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DIR=/etc/storybox
INSTALL_DIR=/opt/storybox
UNIT_DIR=/etc/systemd/system
NETWORK_DIR=/etc/systemd/network
NETWORK_FILE="$NETWORK_DIR/25-storybox-wlan1.network"
HOSTAPD_FILE="$CONFIG_DIR/hostapd.conf"
DNSMASQ_FILE="$CONFIG_DIR/dnsmasq.conf"
WPA_FILE="$CONFIG_DIR/wpa_supplicant.conf"
PLAYER_UNIT=storybox-player.service
WIFI_UNIT=storybox-wifi.service
WPA_UNIT=storybox-wpa.service

log() { printf '\n[StoryBox setup] %s\n' "$*"; }
die() { printf '\n[StoryBox setup] ERROR: %s\n' "$*" >&2; exit 1; }
need_file() { [[ -f "$REPO_DIR/$1" ]] || die "Required repository file is missing: $1"; }

[[ "$EUID" -eq 0 ]] || die "Run with sudo: sudo bash scripts/provision-device.sh"
[[ -t 0 ]] || die "Interactive terminal required to securely set the StoryBox hotspot password."
[[ -t 1 ]] || die "Run this script from a terminal."
[[ -z "${SSH_CONNECTION:-}" ]] || die "Run locally on the device console, not over SSH. Network setup can interrupt remote access."

[[ -r /etc/os-release ]] || die "Cannot identify operating system."
# shellcheck disable=SC1091
source /etc/os-release
case "${ID:-}" in
  armbian|debian|ubuntu) ;;
  *) die "Unsupported OS ID '${ID:-unknown}'. Use a supported Armbian/Debian/Ubuntu image." ;;
esac
case "$(uname -m)" in
  armv7l|aarch64|armhf|arm64) ;;
  *) die "Unsupported architecture: $(uname -m). This setup targets ARM StoryBox hardware." ;;
esac

for file in \
  src/storybox/wifi/wifi_manager.py \
  src/storybox/wifi/portal.py \
  src/storybox/wifi/connect_wifi.py \
  src/storybox/player/story_player.py \
  config/examples/hostapd.conf.example \
  config/examples/dnsmasq.conf.example \
  config/examples/wpa_supplicant.conf.example \
  config/network/25-storybox-wlan1.network \
  systemd/storybox-wifi.service \
  systemd/storybox-wpa.service \
  systemd/storybox-player.service \
  scripts/verify.sh
do
  need_file "$file"
done

id admin >/dev/null 2>&1 || die "The current player code uses /home/admin. Create/use the 'admin' device account before provisioning."
[[ -d /home/admin ]] || die "Expected /home/admin is missing."
[[ ! -e "$INSTALL_DIR" ]] || die "$INSTALL_DIR already exists. This installer is for a fresh device; use scripts/install.sh for the separate migration workflow."
for unit in "$WIFI_UNIT" "$WPA_UNIT" "$PLAYER_UNIT"; do
  [[ ! -e "$UNIT_DIR/$unit" ]] || die "$UNIT_DIR/$unit already exists. Refusing to overwrite an existing installation."
done
[[ ! -e "$NETWORK_FILE" ]] || die "$NETWORK_FILE already exists. Review existing network configuration before provisioning."
[[ ! -e "$CONFIG_DIR" ]] || {
  [[ ! -e "$HOSTAPD_FILE" && ! -e "$DNSMASQ_FILE" && ! -e "$WPA_FILE" ]] ||
    die "$CONFIG_DIR already contains StoryBox configuration. Refusing to overwrite it."
}

for iface in wlan0 wlan1; do
  [[ -d "/sys/class/net/$iface" ]] || die "Required Wi-Fi interface $iface is missing. Check adapters/driver names; StoryBox needs wlan0 (hotspot) and wlan1 (station)."
done

if systemctl is-active --quiet storybox-wifi.service ||
   systemctl is-active --quiet storybox-wpa.service ||
   systemctl is-active --quiet storybox-player.service; then
  die "A StoryBox service is already running. This script only provisions a fresh device."
fi

log "Preflight passed for $PRETTY_NAME / $(uname -m)."
log "Installing system packages. This may take several minutes."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates git python3 \
  mpv gpiod alsa-utils \
  hostapd dnsmasq wpasupplicant iw iproute2 \
  systemd

# Make sure the expected libgpiod CLI exists; package names vary between images.
command -v gpiomon >/dev/null 2>&1 || die "The installed GPIO package did not provide gpiomon. Check the libgpiod package for this Armbian release."

log "Checking network services and configuration."
# StoryBox's Wi-Fi manager owns hostapd and dnsmasq as child processes. Avoid
# having the package-managed daemons compete for the same interfaces/ports.
systemctl disable --now hostapd.service >/dev/null 2>&1 || true
systemctl disable --now dnsmasq.service >/dev/null 2>&1 || true

# StoryBox uses systemd-networkd for DHCP on wlan1. NetworkManager can conflict
# with this configuration, so this clean-device installer switches to networkd.
if systemctl is-active --quiet NetworkManager.service; then
  systemctl disable --now NetworkManager.service
fi
if systemctl is-active --quiet NetworkManager; then
  systemctl disable --now NetworkManager
fi

log "Configuring the StoryBox hotspot."
HOTSPOT_PASSWORD="${STORYBOX_HOTSPOT_PASSWORD:-}"
if [[ -z "$HOTSPOT_PASSWORD" ]]; then
  read -r -s -p "Set a unique StoryBox hotspot password (8-63 characters): " HOTSPOT_PASSWORD
  printf '\n'
fi
[[ "${#HOTSPOT_PASSWORD}" -ge 8 && "${#HOTSPOT_PASSWORD}" -le 63 ]] ||
  die "Hotspot password must be 8-63 characters."
[[ "$HOTSPOT_PASSWORD" != *$'\n'* && "$HOTSPOT_PASSWORD" != *$'\r'* ]] ||
  die "Hotspot password must be a single line."

install -d -o root -g root -m 755 "$CONFIG_DIR" "$NETWORK_DIR"
install -o root -g root -m 600 "$REPO_DIR/config/examples/hostapd.conf.example" "$HOSTAPD_FILE"
# Replace the placeholder literally (no sed metacharacter surprises); config stays root-only.
STORYBOX_HOTSPOT_PASSWORD="$HOTSPOT_PASSWORD" python3 - "$HOSTAPD_FILE" <<'PY'
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text()
password = os.environ["STORYBOX_HOTSPOT_PASSWORD"]
if "wpa_passphrase=REPLACE_WITH_A_UNIQUE_PASSWORD" not in text:
    raise SystemExit("Expected hotspot password placeholder was not found.")
path.write_text(text.replace(
    "wpa_passphrase=REPLACE_WITH_A_UNIQUE_PASSWORD",
    "wpa_passphrase=" + password,
))
PY
chmod 600 "$HOSTAPD_FILE"
unset HOTSPOT_PASSWORD

install -o root -g root -m 644 "$REPO_DIR/config/examples/dnsmasq.conf.example" "$DNSMASQ_FILE"
install -o root -g root -m 600 "$REPO_DIR/config/examples/wpa_supplicant.conf.example" "$WPA_FILE"

log "Installing application and runtime directories."
install -d -o root -g root -m 755 "$INSTALL_DIR" "$INSTALL_DIR/src" "$INSTALL_DIR/config" "$INSTALL_DIR/systemd"
cp -a "$REPO_DIR/src/storybox" "$INSTALL_DIR/src/"
cp -a "$REPO_DIR/config/." "$INSTALL_DIR/config/"
cp -a "$REPO_DIR/systemd/." "$INSTALL_DIR/systemd/"
find "$INSTALL_DIR/src/storybox" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$INSTALL_DIR/src/storybox" -type f -name '*.py[co]' -delete
chown -R root:root "$INSTALL_DIR"
chmod 755 "$INSTALL_DIR/src/storybox/wifi/"*.py "$INSTALL_DIR/src/storybox/player/story_player.py"

# Preserve existing story content; only create defaults when absent.
install -d -o admin -g admin -m 755 /home/admin/stories /home/admin/story-prompts
if [[ ! -e /home/admin/story-library.json ]]; then
  install -o admin -g admin -m 644 /dev/null /home/admin/story-library.json
  printf '[]\n' > /home/admin/story-library.json
fi
chown admin:admin /home/admin/story-library.json
chmod 644 /home/admin/story-library.json

# Allow the player account to read GPIO/audio devices where these groups exist.
for group in gpio audio; do
  if getent group "$group" >/dev/null 2>&1; then
    usermod -aG "$group" admin
  fi
done
if getent group netdev >/dev/null 2>&1; then
  usermod -aG netdev admin
fi

install -o root -g root -m 644 "$REPO_DIR/config/network/25-storybox-wlan1.network" "$NETWORK_FILE"
install -o root -g root -m 644 "$REPO_DIR/systemd/$WIFI_UNIT" "$UNIT_DIR/$WIFI_UNIT"
install -o root -g root -m 644 "$REPO_DIR/systemd/$WPA_UNIT" "$UNIT_DIR/$WPA_UNIT"
install -o root -g root -m 644 "$REPO_DIR/systemd/$PLAYER_UNIT" "$UNIT_DIR/$PLAYER_UNIT"

log "Validating configuration and enabling services."
systemctl enable systemd-networkd.service
systemctl daemon-reload
systemd-analyze verify "$UNIT_DIR/$WPA_UNIT" "$UNIT_DIR/$WIFI_UNIT" "$UNIT_DIR/$PLAYER_UNIT"
bash "$REPO_DIR/scripts/verify.sh"

# The station wpa_supplicant starts first; networkd obtains DHCP; the manager
# falls back to the setup hotspot when no saved Wi-Fi connection exists.
systemctl enable "$WPA_UNIT" "$WIFI_UNIT" "$PLAYER_UNIT"
systemctl restart systemd-networkd.service
systemctl start "$WPA_UNIT"
sleep 2
systemctl start "$WIFI_UNIT"
systemctl start "$PLAYER_UNIT"

log "Checking service state."
failed=0
for unit in systemd-networkd.service "$WPA_UNIT" "$WIFI_UNIT" "$PLAYER_UNIT"; do
  state="$(systemctl is-active "$unit" 2>/dev/null || true)"
  printf '  %-32s %s\n' "$unit" "${state:-unknown}"
  [[ "$state" == active ]] || failed=1
done

printf '\n'
if [[ "$failed" -ne 0 ]]; then
  echo "Provisioning completed with one or more services not active."
  echo "Inspect logs with: sudo journalctl -b -u $WPA_UNIT -u $WIFI_UNIT -u $PLAYER_UNIT --no-pager"
  echo "Check hardware, interface names, audio device, and GPIO permissions before rebooting."
  exit 1
fi

cat <<'EOF'
StoryBox provisioning finished.

Next steps:
  1. Connect a phone/laptop to the StoryBox hotspot using the password you set.
  2. Open http://192.168.4.1 to configure the device's Wi-Fi connection.
  3. Add licensed story audio files under /home/admin/stories.
  4. Add matching entries to /home/admin/story-library.json and prompt WAV files
     under /home/admin/story-prompts if required by your catalog.
  5. Check playback and buttons on the actual hardware.

Useful diagnostics:
  sudo systemctl status storybox-wpa storybox-wifi storybox-player
  sudo journalctl -b -u storybox-wpa -u storybox-wifi -u storybox-player
  aplay -l
  gpiodetect

This installer does not download story content or create welcome.wav.
EOF
