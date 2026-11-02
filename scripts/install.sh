#!/usr/bin/env bash
set -Eeuo pipefail

# Fresh-device installer for Orange Pi PC Plus / Armbian ARMv7.
# Run from the repository: sudo bash scripts/install.sh

REPO_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALL_DIR="/opt/storybox"
PIPER_DIR="/opt/piper"
MODEL_NAME="en_US-lessac-medium"
MODEL_DIR="$PIPER_DIR/models"
MODEL_PATH="$MODEL_DIR/$MODEL_NAME.onnx"
MODEL_JSON="$MODEL_PATH.json"
CONFIG_DIR="/etc/storybox"
UNIT_DIR="/etc/systemd/system"
ADMIN_USER="admin"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_armv7l.tar.gz"
PIPER_SIZE="25445955"
VOICE_REVISION="b145f2ac26522d6a2ccde0164b7b0e48b1e3199c"
VOICE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/$VOICE_REVISION/en/en_US/lessac/medium"
MODEL_SHA256="5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"

log() { printf '\n[StoryBox install] %s\n' "$*"; }
die() { printf '\n[StoryBox install] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Run with sudo: sudo bash scripts/install.sh"
for file in \
    src/storybox/player/story_player.py \
    src/storybox/wifi/wifi_manager.py \
    src/storybox/wifi/portal.py \
    src/storybox/wifi/connect_wifi.py \
    scripts/storybox_watcher.py \
    systemd/storybox-player.service \
    systemd/storybox-watcher.service \
    systemd/storybox-wifi.service \
    config/examples/hostapd.conf.example \
    config/examples/dnsmasq.conf.example \
    udev/99-storybox-gpio.rules; do
    [[ -f "$REPO_DIR/$file" ]] || die "Missing repository file: $file"
done

[[ "$(uname -m)" == "armv7l" ]] || die "Expected ARMv7 (armv7l); detected $(uname -m)."
[[ "$(dpkg --print-architecture)" == "armhf" ]] || die "Expected armhf userspace."
id "$ADMIN_USER" >/dev/null 2>&1 || die "The Linux account 'admin' must already exist."
for interface in wlan0 wlan1; do
    ip link show "$interface" >/dev/null 2>&1 || die "Required Wi-Fi interface $interface not found."
done

log "Installing operating-system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl ffmpeg gpiod hostapd iw iproute2 \
    alsa-utils mpv network-manager dnsmasq rfkill python3 qrencode
command -v nmcli >/dev/null || die "nmcli is unavailable."
command -v gpiomon >/dev/null || die "gpiomon is unavailable."
gpiomon --help 2>&1 | grep -q -- '-c' || die "gpiomon must support the -c option."

log "Preparing NetworkManager"
systemctl enable --now NetworkManager.service
nmcli radio wifi on
managed="$(nmcli -g GENERAL.NM-MANAGED device show wlan0 2>/dev/null || true)"
[[ "$managed" == "yes" ]] || die "wlan0 is not managed by NetworkManager (NM-MANAGED=$managed)."

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

log "Installing Piper 1.2.0 for ARMv7"
install -d -o root -g root -m 755 "$PIPER_DIR" "$MODEL_DIR"
if [[ ! -x "$PIPER_DIR/piper" ]]; then
    curl --fail --location --retry 3 --retry-delay 2 "$PIPER_URL" \
        -o "$TMP_DIR/piper.tar.gz"
    archive_size="$(stat -c '%s' "$TMP_DIR/piper.tar.gz")"
    [[ "$archive_size" == "$PIPER_SIZE" ]] || die "Unexpected Piper archive size: $archive_size."
    mkdir "$TMP_DIR/piper"
    tar -xzf "$TMP_DIR/piper.tar.gz" -C "$TMP_DIR/piper"
    piper_file="$(find "$TMP_DIR/piper" -type f -name piper -perm /111 -print -quit)"
    [[ -n "$piper_file" ]] || die "Piper executable not found in ARMv7 archive."
    piper_root="$(dirname "$piper_file")"
    cp -a "$piper_root/." "$PIPER_DIR/"
    chmod 755 "$PIPER_DIR/piper"
fi

if [[ ! -f "$MODEL_PATH" ]] || [[ "$(sha256sum "$MODEL_PATH" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
    curl --fail --location --retry 3 --retry-delay 2 \
        "$VOICE_URL/$MODEL_NAME.onnx" -o "$TMP_DIR/$MODEL_NAME.onnx"
    printf '%s  %s\n' "$MODEL_SHA256" "$TMP_DIR/$MODEL_NAME.onnx" \
        | sha256sum --check --status || die "Piper voice model SHA-256 verification failed."
    install -o root -g root -m 644 "$TMP_DIR/$MODEL_NAME.onnx" "$MODEL_PATH"
fi

if [[ ! -s "$MODEL_JSON" ]]; then
    curl --fail --location --retry 3 --retry-delay 2 \
        "$VOICE_URL/$MODEL_NAME.onnx.json" -o "$TMP_DIR/$MODEL_NAME.onnx.json"
    python3 -m json.tool "$TMP_DIR/$MODEL_NAME.onnx.json" >/dev/null \
        || die "Piper voice configuration is invalid JSON."
    install -o root -g root -m 644 "$TMP_DIR/$MODEL_NAME.onnx.json" "$MODEL_JSON"
fi
python3 -m json.tool "$MODEL_JSON" >/dev/null || die "Installed Piper voice configuration is invalid JSON."

[[ -d "$PIPER_DIR/espeak-ng-data" ]] || die "Piper archive is missing espeak-ng-data."
export LD_LIBRARY_PATH="$PIPER_DIR"
"$PIPER_DIR/piper" --help >/dev/null 2>&1 || die "Piper executable failed to start."

log "Preparing StoryBox runtime directories"
install -d -o "$ADMIN_USER" -g "$ADMIN_USER" -m 755 \
    "/home/$ADMIN_USER/stories" "/home/$ADMIN_USER/story-prompts"
if [[ ! -s "/home/$ADMIN_USER/story-library.json" ]]; then
    printf '[]\n' > "/home/$ADMIN_USER/story-library.json"
fi
chown "$ADMIN_USER:$ADMIN_USER" "/home/$ADMIN_USER/story-library.json"
if [[ ! -s "/home/$ADMIN_USER/story-prompts/welcome.wav" ]]; then
    printf 'Welcome to StoryBox.\n' | "$PIPER_DIR/piper" \
        --model "$MODEL_PATH" --output_file "$TMP_DIR/welcome.raw.wav"
    ffmpeg -y -loglevel error -i "$TMP_DIR/welcome.raw.wav" \
        -af 'adelay=600:all=1' -ac 1 -ar 22050 -c:a pcm_s16le \
        "$TMP_DIR/welcome.wav"
    install -o "$ADMIN_USER" -g "$ADMIN_USER" -m 644 \
        "$TMP_DIR/welcome.wav" "/home/$ADMIN_USER/story-prompts/welcome.wav"
fi

log "Deploying StoryBox application"
install -d -o root -g root -m 755 "$INSTALL_DIR" "$INSTALL_DIR/src" \
    "$INSTALL_DIR/scripts" "$INSTALL_DIR/config"
rm -rf "$INSTALL_DIR/src/storybox"
cp -a "$REPO_DIR/src/storybox" "$INSTALL_DIR/src/"
install -o root -g root -m 755 "$REPO_DIR/scripts/storybox_watcher.py" \
    "$INSTALL_DIR/scripts/storybox_watcher.py"
cp -a "$REPO_DIR/config/." "$INSTALL_DIR/config/"
find "$INSTALL_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$INSTALL_DIR" -type f -name '*.py[co]' -delete
chown -R root:root "$INSTALL_DIR"

log "Installing GPIO permissions"
getent group gpio >/dev/null || groupadd --system gpio
usermod -aG gpio,audio "$ADMIN_USER"
install -o root -g root -m 644 "$REPO_DIR/udev/99-storybox-gpio.rules" \
    /etc/udev/rules.d/99-storybox-gpio.rules
udevadm control --reload-rules
udevadm trigger --subsystem-match=gpio || true

log "Configuring the wlan1 fallback hotspot"
install -d -o root -g root -m 700 "$CONFIG_DIR"
if [[ ! -s "$CONFIG_DIR/hostapd.conf" ]]; then
    install -o root -g root -m 600 "$REPO_DIR/config/examples/hostapd.conf.example" \
        "$CONFIG_DIR/hostapd.conf"
fi

if ! grep -Eq '^wpa_passphrase=.{8,63}$' "$CONFIG_DIR/hostapd.conf" \
   || grep -q '^wpa_passphrase=12345678$' "$CONFIG_DIR/hostapd.conf"; then
    hotspot_password="$(python3 -c 'import secrets; print(secrets.token_hex(9))')"
    if grep -q '^wpa_passphrase=' "$CONFIG_DIR/hostapd.conf"; then
        sed -i "s/^wpa_passphrase=.*/wpa_passphrase=$hotspot_password/" "$CONFIG_DIR/hostapd.conf"
    else
        printf '\nwpa_passphrase=%s\n' "$hotspot_password" >> "$CONFIG_DIR/hostapd.conf"
    fi
else
    hotspot_password="$(sed -n 's/^wpa_passphrase=//p' "$CONFIG_DIR/hostapd.conf" | head -n1)"
fi
if grep -q '^interface=' "$CONFIG_DIR/hostapd.conf"; then
    sed -i 's/^interface=.*/interface=wlan1/' "$CONFIG_DIR/hostapd.conf"
else
    printf '\ninterface=wlan1\n' >> "$CONFIG_DIR/hostapd.conf"
fi
chown root:root "$CONFIG_DIR/hostapd.conf"
chmod 600 "$CONFIG_DIR/hostapd.conf"

if [[ ! -s "$CONFIG_DIR/dnsmasq.conf" ]]; then
    install -o root -g root -m 644 "$REPO_DIR/config/examples/dnsmasq.conf.example" \
        "$CONFIG_DIR/dnsmasq.conf"
fi
sed -i \
    -e '/^interface=/d' \
    -e '/^bind-interfaces$/d' \
    -e '/^listen-address=/d' \
    -e '/^dhcp-option=6,/d' \
    -e '/^address=\/#\//d' \
    -e '/^dhcp-range=/d' \
    "$CONFIG_DIR/dnsmasq.conf"
cat >> "$CONFIG_DIR/dnsmasq.conf" <<'EOF'
interface=wlan1
bind-interfaces
listen-address=192.168.4.1
dhcp-option=6,192.168.4.1
address=/#/192.168.4.1
dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,12h
EOF
chown root:root "$CONFIG_DIR/dnsmasq.conf"
chmod 644 "$CONFIG_DIR/dnsmasq.conf"

install -d -o root -g root -m 755 /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF
nmcli device set wlan1 managed no >/dev/null 2>&1 || true

# The manager launches hostapd/dnsmasq as foreground processes only during fallback.
systemctl disable --now hostapd.service dnsmasq.service >/dev/null 2>&1 || true

log "Installing systemd units"
for unit in storybox-player.service storybox-watcher.service storybox-wifi.service; do
    install -o root -g root -m 644 "$REPO_DIR/systemd/$unit" "$UNIT_DIR/$unit"
done
systemctl disable --now storybox-wpa.service >/dev/null 2>&1 || true
rm -f "$UNIT_DIR/storybox-wpa.service"
systemctl daemon-reload
systemd-analyze verify \
    "$UNIT_DIR/storybox-player.service" \
    "$UNIT_DIR/storybox-watcher.service" \
    "$UNIT_DIR/storybox-wifi.service"

log "Enabling StoryBox services"
systemctl enable --now storybox-player.service
systemctl enable --now storybox-watcher.service
systemctl enable --now storybox-wifi.service

log "Installation completed"
printf '\nHotspot SSID: StoryBox-Setup\n'
printf 'Hotspot password: %s\n' "$hotspot_password"
printf 'Portal address: http://192.168.4.1/\n'
printf '\nServices:\n'
systemctl --no-pager --full --lines=0 status \
    storybox-player.service storybox-watcher.service storybox-wifi.service || true
printf '\nCopy story audio files into /home/admin/stories/.\n'
printf 'A reboot is recommended to apply admin group membership and GPIO udev permissions.\n'
