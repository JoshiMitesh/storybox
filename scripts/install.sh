#!/usr/bin/env bash
set -Eeuo pipefail

# One-command installer for a fresh Orange Pi PC Plus / Armbian ARMv7 device.
# Run from the cloned repository with: sudo bash scripts/install.sh

REPO_DIR="$(cd -- "$(dirname -- "$0")/.." && pwd)"
INSTALL_DIR="/opt/storybox"
PIPER_DIR="/opt/piper"
CONFIG_DIR="/etc/storybox"
UNIT_DIR="/etc/systemd/system"
ADMIN_USER="admin"
MODEL_NAME="en_US-lessac-medium"
MODEL_DIR="$PIPER_DIR/models"
MODEL_PATH="$MODEL_DIR/$MODEL_NAME.onnx"
MODEL_JSON="$MODEL_PATH.json"
PIPER_ARCHIVE_URL="https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_armv7l.tar.gz"
PIPER_ARCHIVE_SIZE="25445955"
VOICE_REVISION="b145f2ac26522d6a2ccde0164b7b0e48b1e3199c"
VOICE_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/$VOICE_REVISION/en/en_US/lessac/medium"
MODEL_SHA256="5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"

log() { printf '\n[StoryBox install] %s\n' "$*"; }
die() { printf '\n[StoryBox install] ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$EUID" -eq 0 ]] || die "Run with sudo: sudo bash scripts/install.sh"
[[ -f "$REPO_DIR/src/storybox/player/story_player.py" ]] || die "Run this script from the StoryBox repository."
[[ -f "$REPO_DIR/src/storybox/wifi/wifi_manager.py" ]] || die "Missing Wi-Fi manager source."
[[ -f "$REPO_DIR/src/storybox/wifi/portal.py" ]] || die "Missing captive portal source."
[[ -f "$REPO_DIR/src/storybox/wifi/connect_wifi.py" ]] || die "Missing Wi-Fi connection helper."
[[ -f "$REPO_DIR/scripts/storybox_watcher.py" ]] || die "Missing story watcher."
[[ -f "$REPO_DIR/config/examples/hostapd.conf.example" ]] || die "Missing hostapd template."
[[ -f "$REPO_DIR/config/examples/dnsmasq.conf.example" ]] || die "Missing dnsmasq template."

[[ "$(uname -m)" == "armv7l" ]] || die "This Piper bundle targets 32-bit ARMv7 (armv7l). Detected: $(uname -m)"
[[ "$(dpkg --print-architecture)" == "armhf" ]] || die "Expected Debian armhf userspace. Detected: $(dpkg --print-architecture)"
id "$ADMIN_USER" >/dev/null 2>&1 || die "Linux account '$ADMIN_USER' must already exist."

for interface in wlan0 wlan1; do
    ip link show "$interface" >/dev/null 2>&1 || die "Required Wi-Fi interface $interface was not found. Check the Orange Pi Wi-Fi drivers/adapters."
done

log "Installing system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
    ca-certificates curl ffmpeg gpiod hostapd iw iproute2 alsa-utils \
    mpv network-manager dnsmasq rfkill python3 qrencode

command -v nmcli >/dev/null || die "NetworkManager installation did not provide nmcli."
command -v gpiomon >/dev/null || die "gpiod installation did not provide gpiomon."
gpiomon --help 2>&1 | grep -q -- '-c' || die "Installed gpiomon does not support the required -c option."

log "Starting NetworkManager and preparing Wi-Fi interfaces"
systemctl enable --now NetworkManager.service
nmcli radio wifi on
managed="$(nmcli -g GENERAL.NM-MANAGED device show wlan0 2>/dev/null || true)"
[[ "$managed" == "yes" ]] || die "wlan0 is not managed by NetworkManager (NM-MANAGED=$managed). No StoryBox services have been enabled."

log "Installing Piper 1.2.0 ARMv7 and the Lessac medium voice"
install -d -o root -g root -m 755 "$PIPER_DIR" "$MODEL_DIR"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

if [[ ! -x "$PIPER_DIR/piper" ]]; then
    curl --fail --location --retry 3 --retry-delay 2 \
        "$PIPER_ARCHIVE_URL" -o "$TMP_DIR/piper_linux_armv7l.tar.gz"
    actual_size="$(stat -c '%s' "$TMP_DIR/piper_linux_armv7l.tar.gz")"
    [[ "$actual_size" == "$PIPER_ARCHIVE_SIZE" ]] || die "Piper archive size mismatch (expected $PIPER_ARCHIVE_SIZE bytes, got $actual_size)."
    mkdir "$TMP_DIR/piper"
    tar -xzf "$TMP_DIR/piper_linux_armv7l.tar.gz" -C "$TMP_DIR/piper"
    PIPER_ROOT="$(dirname "$(find "$TMP_DIR/piper" -type f -name piper -perm /111 -print -quit)")"
    [[ -n "$PIPER_ROOT" && -x "$PIPER_ROOT/piper" ]] || die "Could not find the Piper executable in the official ARMv7 archive."
    cp -a "$PIPER_ROOT/." "$PIPER_DIR/"
    chmod 755 "$PIPER_DIR/piper"
fi

if [[ ! -f "$MODEL_PATH" ]] || [[ "$(sha256sum "$MODEL_PATH" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
    curl --fail --location --retry 3 --retry-delay 2 \
        "$VOICE_BASE_URL/$MODEL_NAME.onnx" -o "$TMP_DIR/$MODEL_NAME.onnx"
    echo "$MODEL_SHA256  $TMP_DIR/$MODEL_NAME.onnx" | sha256sum --check --status \
        || die "Downloaded Piper voice model failed SHA-256 verification."
    install -o root -g root -m 644 "$TMP_DIR/$MODEL_NAME.onnx" "$MODEL_PATH"
fi

if [[ ! -s "$MODEL_JSON" ]]; then
    curl --fail --location --retry 3 --retry-delay 2 \
        "$VOICE_BASE_URL/$MODEL_NAME.onnx.json" -o "$TMP_DIR/$MODEL_NAME.onnx.json"
    python3 -m json.tool "$TMP_DIR/$MODEL_NAME.onnx.json" >/dev/null \
        || die "Downloaded Piper voice configuration is not valid JSON."
    install -o root -g root -m 644 "$TMP_DIR/$MODEL_NAME.onnx.json" "$MODEL_JSON"
fi

[[ -d "$PIPER_DIR/espeak-ng-data" ]] || die "Piper archive is missing espeak-ng-data."
[[ -x "$PIPER_DIR/piper" ]] || die "Piper executable is missing."
export LD_LIBRARY_PATH="$PIPER_DIR"
"$PIPER_DIR/piper" --help >/dev/null 2>&1 || die "Piper executable could not start; check its bundled shared libraries."

log "Creating runtime directories and welcome prompt"
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

log "Installing StoryBox application files"
install -d -o root -g root -m 755 \
    "$INSTALL_DIR" "$INSTALL_DIR/src" "$INSTALL_DIR/scripts" \
    "$INSTALL_DIR/config" "$CONFIG_DIR"
rm -rf "$INSTALL_DIR/src/storybox"
cp -a "$REPO_DIR/src/storybox" "$INSTALL_DIR/src/"
install -o root -g root -m 755 \
    "$REPO_DIR/scripts/storybox_watcher.py" "$INSTALL_DIR/scripts/storybox_watcher.py"
cp -a "$REPO_DIR/config/." "$INSTALL_DIR/config/"
find "$INSTALL_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$INSTALL_DIR" -type f -name '*.py[co]' -delete
chown -R root:root "$INSTALL_DIR"

log "Configuring GPIO permissions"
getent group gpio >/dev/null || groupadd --system gpio
usermod -aG gpio,audio "$ADMIN_USER"
cat > /etc/udev/rules.d/99-storybox-gpio.rules <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
EOF
udevadm control --reload-rules
udevadm trigger --subsystem-match=gpio || true

log "Configuring the wlan1 setup hotspot"
if [[ ! -s "$CONFIG_DIR/hostapd.conf" ]]; then
    install -o root -g root -m 600 \
        "$REPO_DIR/config/examples/hostapd.conf.example" "$CONFIG_DIR/hostapd.conf"
fi
if ! grep -Eq '^wpa_passphrase=[A-Za-z0-9]{8,63}
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
    install -o root -g root -m 644 \
        "$REPO_DIR/config/examples/dnsmasq.conf.example" "$CONFIG_DIR/dnsmasq.conf"
fi
sed -i \
    -e '/^interface=/d' \
    -e '/^listen-address=/d' \
    -e '/^dhcp-option=6,/d' \
    -e '/^address=\/#\//d' \
    "$CONFIG_DIR/dnsmasq.conf"
grep -q '^bind-interfaces$' "$CONFIG_DIR/dnsmasq.conf" || printf 'bind-interfaces\n' >> "$CONFIG_DIR/dnsmasq.conf"
grep -q '^dhcp-range=' "$CONFIG_DIR/dnsmasq.conf" || \
    printf 'dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,12h\n' >> "$CONFIG_DIR/dnsmasq.conf"
cat >> "$CONFIG_DIR/dnsmasq.conf" <<'EOF'
interface=wlan1
listen-address=192.168.4.1
dhcp-option=6,192.168.4.1
address=/#/192.168.4.1
EOF
chown root:root "$CONFIG_DIR/dnsmasq.conf"
chmod 644 "$CONFIG_DIR/dnsmasq.conf"

install -d -o root -g root -m 755 /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF
nmcli device set wlan1 managed no >/dev/null 2>&1 || true

# The distro hostapd/dnsmasq units must not compete with the Wi-Fi manager,
# which starts and stops its own foreground processes during fallback.
systemctl disable --now hostapd.service dnsmasq.service >/dev/null 2>&1 || true

log "Installing systemd services"
cat > "$TMP_DIR/storybox-player.service" <<'EOF'
[Unit]
Description=StoryBox Offline Audio Player
After=multi-user.target sound.target
Wants=sound.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=gpio audio
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 -u /opt/storybox/src/storybox/player/story_player.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
KillMode=control-group
Environment=HOME=/home/admin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

cat > "$TMP_DIR/storybox-watcher.service" <<'EOF'
[Unit]
Description=StoryBox Automatic Story and Prompt Generator
After=local-fs.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=audio
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 -u /opt/storybox/scripts/storybox_watcher.py
Restart=always
RestartSec=3
Environment=HOME=/home/admin
Environment=LD_LIBRARY_PATH=/opt/piper
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

install -o root -g root -m 644 "$TMP_DIR/storybox-player.service" "$UNIT_DIR/storybox-player.service"
install -o root -g root -m 644 "$TMP_DIR/storybox-watcher.service" "$UNIT_DIR/storybox-watcher.service"
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-wifi.service" "$UNIT_DIR/storybox-wifi.service"

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
printf 'A reboot is recommended to apply the admin group membership and GPIO udev permissions.\n'
 "$CONFIG_DIR/hostapd.conf" || grep -q '^wpa_passphrase=12345678
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
    install -o root -g root -m 644 \
        "$REPO_DIR/config/examples/dnsmasq.conf.example" "$CONFIG_DIR/dnsmasq.conf"
fi
sed -i \
    -e '/^interface=/d' \
    -e '/^listen-address=/d' \
    -e '/^dhcp-option=6,/d' \
    -e '/^address=\/#\//d' \
    "$CONFIG_DIR/dnsmasq.conf"
grep -q '^bind-interfaces$' "$CONFIG_DIR/dnsmasq.conf" || printf 'bind-interfaces\n' >> "$CONFIG_DIR/dnsmasq.conf"
grep -q '^dhcp-range=' "$CONFIG_DIR/dnsmasq.conf" || \
    printf 'dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,12h\n' >> "$CONFIG_DIR/dnsmasq.conf"
cat >> "$CONFIG_DIR/dnsmasq.conf" <<'EOF'
interface=wlan1
listen-address=192.168.4.1
dhcp-option=6,192.168.4.1
address=/#/192.168.4.1
EOF
chown root:root "$CONFIG_DIR/dnsmasq.conf"
chmod 644 "$CONFIG_DIR/dnsmasq.conf"

install -d -o root -g root -m 755 /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF
nmcli device set wlan1 managed no >/dev/null 2>&1 || true

# The distro hostapd/dnsmasq units must not compete with the Wi-Fi manager,
# which starts and stops its own foreground processes during fallback.
systemctl disable --now hostapd.service dnsmasq.service >/dev/null 2>&1 || true

log "Installing systemd services"
cat > "$TMP_DIR/storybox-player.service" <<'EOF'
[Unit]
Description=StoryBox Offline Audio Player
After=multi-user.target sound.target
Wants=sound.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=gpio audio
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 -u /opt/storybox/src/storybox/player/story_player.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
KillMode=control-group
Environment=HOME=/home/admin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

cat > "$TMP_DIR/storybox-watcher.service" <<'EOF'
[Unit]
Description=StoryBox Automatic Story and Prompt Generator
After=local-fs.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=audio
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 -u /opt/storybox/scripts/storybox_watcher.py
Restart=always
RestartSec=3
Environment=HOME=/home/admin
Environment=LD_LIBRARY_PATH=/opt/piper
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

install -o root -g root -m 644 "$TMP_DIR/storybox-player.service" "$UNIT_DIR/storybox-player.service"
install -o root -g root -m 644 "$TMP_DIR/storybox-watcher.service" "$UNIT_DIR/storybox-watcher.service"
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-wifi.service" "$UNIT_DIR/storybox-wifi.service"

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
printf 'A reboot is recommended to apply the admin group membership and GPIO udev permissions.\n'
 "$CONFIG_DIR/hostapd.conf"; then
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
    install -o root -g root -m 644 \
        "$REPO_DIR/config/examples/dnsmasq.conf.example" "$CONFIG_DIR/dnsmasq.conf"
fi
sed -i \
    -e '/^interface=/d' \
    -e '/^listen-address=/d' \
    -e '/^dhcp-option=6,/d' \
    -e '/^address=\/#\//d' \
    "$CONFIG_DIR/dnsmasq.conf"
grep -q '^bind-interfaces$' "$CONFIG_DIR/dnsmasq.conf" || printf 'bind-interfaces\n' >> "$CONFIG_DIR/dnsmasq.conf"
grep -q '^dhcp-range=' "$CONFIG_DIR/dnsmasq.conf" || \
    printf 'dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,12h\n' >> "$CONFIG_DIR/dnsmasq.conf"
cat >> "$CONFIG_DIR/dnsmasq.conf" <<'EOF'
interface=wlan1
listen-address=192.168.4.1
dhcp-option=6,192.168.4.1
address=/#/192.168.4.1
EOF
chown root:root "$CONFIG_DIR/dnsmasq.conf"
chmod 644 "$CONFIG_DIR/dnsmasq.conf"

install -d -o root -g root -m 755 /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/30-storybox-wlan1-unmanaged.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan1
EOF
nmcli device set wlan1 managed no >/dev/null 2>&1 || true

# The distro hostapd/dnsmasq units must not compete with the Wi-Fi manager,
# which starts and stops its own foreground processes during fallback.
systemctl disable --now hostapd.service dnsmasq.service >/dev/null 2>&1 || true

log "Installing systemd services"
cat > "$TMP_DIR/storybox-player.service" <<'EOF'
[Unit]
Description=StoryBox Offline Audio Player
After=multi-user.target sound.target
Wants=sound.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=gpio audio
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 -u /opt/storybox/src/storybox/player/story_player.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=10
KillMode=control-group
Environment=HOME=/home/admin
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

cat > "$TMP_DIR/storybox-watcher.service" <<'EOF'
[Unit]
Description=StoryBox Automatic Story and Prompt Generator
After=local-fs.target

[Service]
Type=simple
User=admin
Group=admin
SupplementaryGroups=audio
WorkingDirectory=/home/admin
ExecStart=/usr/bin/python3 -u /opt/storybox/scripts/storybox_watcher.py
Restart=always
RestartSec=3
Environment=HOME=/home/admin
Environment=LD_LIBRARY_PATH=/opt/piper
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

install -o root -g root -m 644 "$TMP_DIR/storybox-player.service" "$UNIT_DIR/storybox-player.service"
install -o root -g root -m 644 "$TMP_DIR/storybox-watcher.service" "$UNIT_DIR/storybox-watcher.service"
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-wifi.service" "$UNIT_DIR/storybox-wifi.service"

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
printf 'A reboot is recommended to apply the admin group membership and GPIO udev permissions.\n'
