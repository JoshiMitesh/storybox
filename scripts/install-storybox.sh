#!/usr/bin/env bash
set -Eeuo pipefail
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE_USER="${SUDO_USER:-admin}"
DEVICE_HOME="/home/admin"
INSTALL_DIR="/opt/storybox"
PIPER_DIR="/opt/piper"
MODEL_NAME="en_US-lessac-medium"
PIPER_RELEASE="2023.11.14-2"
PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_RELEASE}/piper_linux_armv7l.tar.gz"
MODEL_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
MODEL_SHA256="5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f"
MODEL_MD5="2fc642b535197b6305c7c8f92dc8b24f"

if [[ "$EUID" -ne 0 ]]; then echo "Run: sudo bash scripts/install-storybox.sh"; exit 1; fi
if [[ "$DEVICE_USER" != "admin" ]] || ! id admin >/dev/null 2>&1; then
  echo "ERROR: This installer requires the existing 'admin' account."; exit 1
fi
for f in src/storybox/player/story_player.py src/storybox/local_api.py \
  src/storybox/wifi/wifi_manager.py src/storybox/wifi/portal.py \
  src/storybox/wifi/connect_wifi.py scripts/storybox_watcher.py \
  systemd/storybox-player.service systemd/storybox-watcher.service \
  systemd/storybox-wifi.service systemd/storybox-local-api.service \
  udev/99-storybox-gpio.rules; do
  [[ -f "$REPO_DIR/$f" ]] || { echo "ERROR: Missing repository file: $f"; exit 1; }
done

ARCH="$(dpkg --print-architecture)"
MACHINE="$(uname -m)"
if [[ "$MACHINE" != "armv7l" && "$MACHINE" != "armv8l" ]]; then
  echo "ERROR: This Piper package is for 32-bit ARMv7. Detected: $MACHINE"; exit 1
fi
if [[ "$ARCH" != "armhf" ]]; then
  echo "ERROR: Expected Armbian/Debian armhf userspace. Detected: $ARCH"; exit 1
fi

export DEBIAN_FRONTEND=noninteractive
echo "=== Installing OS and Python requirements ==="
bash "$REPO_DIR/scripts/install-requirements.sh"

echo "=== Configuring I2C0 overlay (preserving other overlays) ==="
BOOT_ENV="/boot/armbianEnv.txt"
OVERLAY="/boot/dtb-$(uname -r)/overlay/sun8i-h3-i2c0.dtbo"
[[ -f "$BOOT_ENV" ]] || { echo "ERROR: $BOOT_ENV not found; expected Armbian."; exit 1; }
[[ -f "$OVERLAY" ]] || { echo "ERROR: Matching H3 I2C0 overlay missing: $OVERLAY"; exit 1; }
grep -q '^overlays=' "$BOOT_ENV" || { echo "ERROR: no overlays= setting; refusing to guess."; exit 1; }
if ! grep '^overlays=' "$BOOT_ENV" | grep -Eq '(^|[[:space:]])i2c0([[:space:]]|$)'; then
  cp -a "$BOOT_ENV" "$BOOT_ENV.storybox-backup.$(date +%Y%m%d%H%M%S)"
  python3 - "$BOOT_ENV" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
lines = p.read_text().splitlines()
for i, line in enumerate(lines):
    if line.startswith("overlays="):
        values = line.split("=", 1)[1].split()
        if "i2c0" not in values:
            values.append("i2c0")
        lines[i] = "overlays=" + " ".join(values)
        break
p.write_text("\n".join(lines) + "\n")
PY
  echo "Added i2c0; reboot required."
else
  echo "I2C0 overlay already enabled."
fi

echo "=== Installing Piper ARMv7 and Lessac medium voice ==="
mkdir -p "$PIPER_DIR/models"
if [[ ! -x "$PIPER_DIR/piper" ]]; then
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  curl --fail --location --retry 3 --retry-delay 2 "$PIPER_URL" -o "$TMP_DIR/piper.tar.gz"
  tar -tzf "$TMP_DIR/piper.tar.gz" >/dev/null
  mkdir "$TMP_DIR/unpacked"
  tar -xzf "$TMP_DIR/piper.tar.gz" -C "$TMP_DIR/unpacked"
  PIPER_BIN="$(find "$TMP_DIR/unpacked" -type f -name piper -perm /111 -print -quit)"
  [[ -n "$PIPER_BIN" ]] || { echo "ERROR: Piper archive has no executable named piper."; exit 1; }
  cp -a "$(dirname "$PIPER_BIN")/." "$PIPER_DIR/"
  chmod 755 "$PIPER_DIR/piper"
  rm -rf "$TMP_DIR"
  trap - EXIT
else
  echo "Existing Piper executable found; retaining it."
fi

MODEL="$PIPER_DIR/models/${MODEL_NAME}.onnx"
MODEL_JSON="${MODEL}.json"
if [[ ! -s "$MODEL" ]] || [[ "$(sha256sum "$MODEL" | awk '{print $1}')" != "$MODEL_SHA256" ]]; then
  curl --fail --location --retry 3 --retry-delay 2 "$MODEL_BASE/${MODEL_NAME}.onnx" -o "${MODEL}.part"
  ACTUAL_SHA="$(sha256sum "${MODEL}.part" | awk '{print $1}')"
  if [[ "$ACTUAL_SHA" != "$MODEL_SHA256" ]]; then rm -f "${MODEL}.part"; echo "ERROR: model SHA-256 mismatch."; exit 1; fi
  mv "${MODEL}.part" "$MODEL"
fi
if [[ ! -s "$MODEL_JSON" ]] || [[ "$(md5sum "$MODEL_JSON" | awk '{print $1}')" != "$MODEL_MD5" ]]; then
  curl --fail --location --retry 3 --retry-delay 2 "$MODEL_BASE/${MODEL_NAME}.onnx.json" -o "${MODEL_JSON}.part"
  ACTUAL_MD5="$(md5sum "${MODEL_JSON}.part" | awk '{print $1}')"
  if [[ "$ACTUAL_MD5" != "$MODEL_MD5" ]]; then rm -f "${MODEL_JSON}.part"; echo "ERROR: model JSON checksum mismatch."; exit 1; fi
  mv "${MODEL_JSON}.part" "$MODEL_JSON"
fi
chown -R root:root "$PIPER_DIR"
chmod -R a+rX "$PIPER_DIR"
LD_LIBRARY_PATH="$PIPER_DIR" "$PIPER_DIR/piper" --help >/dev/null 2>&1 || { echo "ERROR: Piper executable cannot run."; exit 1; }
printf 'StoryBox Piper validation\n' | LD_LIBRARY_PATH="$PIPER_DIR" "$PIPER_DIR/piper" --model "$MODEL" --output_file /tmp/storybox-piper-test.wav
[[ -s /tmp/storybox-piper-test.wav ]] || { echo "ERROR: Piper synthesis test failed."; exit 1; }
rm -f /tmp/storybox-piper-test.wav
echo "Piper and voice synthesis validated."

echo "=== Preparing groups and directories ==="
getent group gpio >/dev/null || groupadd --system gpio
getent group i2c >/dev/null || groupadd --system i2c
usermod -aG gpio,audio,i2c admin
install -d -o admin -g admin -m 755 "$DEVICE_HOME/stories" "$DEVICE_HOME/story-prompts"
install -d -o admin -g admin -m 755 "$DEVICE_HOME/.local/share/storybox" "$DEVICE_HOME/storybox-library"
if [[ ! -f "$DEVICE_HOME/story-library.json" ]]; then
  printf '[]\n' > "$DEVICE_HOME/story-library.json"
  chown admin:admin "$DEVICE_HOME/story-library.json"
  chmod 664 "$DEVICE_HOME/story-library.json"
fi

echo "=== Installing application files and udev rule ==="
install -d -o root -g root -m 755 "$INSTALL_DIR"
rm -rf "$INSTALL_DIR/src/storybox" "$INSTALL_DIR/scripts" "$INSTALL_DIR/config" "$INSTALL_DIR/systemd"
install -d -o root -g root -m 755 "$INSTALL_DIR/src" "$INSTALL_DIR/scripts" "$INSTALL_DIR/config" "$INSTALL_DIR/systemd"
cp -a "$REPO_DIR/src/storybox" "$INSTALL_DIR/src/"
cp -a "$REPO_DIR/scripts/." "$INSTALL_DIR/scripts/"
cp -a "$REPO_DIR/config/." "$INSTALL_DIR/config/"
cp -a "$REPO_DIR/systemd/." "$INSTALL_DIR/systemd/"
find "$INSTALL_DIR" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$INSTALL_DIR" -type f -name '*.py[co]' -delete
chown -R root:root "$INSTALL_DIR"
install -o root -g root -m 644 "$REPO_DIR/udev/99-storybox-gpio.rules" /etc/udev/rules.d/99-storybox-gpio.rules

echo "=== Preserving API environment ==="
install -d -o root -g root -m 700 /etc/storybox
if [[ ! -f /etc/storybox/local-api.env ]]; then
  cat > /etc/storybox/local-api.env <<'EOF'
STORYBOX_API_HOST=127.0.0.1
STORYBOX_API_PORT=8089
STORYBOX_FIRMWARE_VERSION=0.1.0
EOF
  chown root:admin /etc/storybox/local-api.env
  chmod 640 /etc/storybox/local-api.env
else
  echo "Existing /etc/storybox/local-api.env preserved."
fi

echo "=== Installing four systemd unit files ==="
for unit in storybox-player storybox-watcher storybox-wifi storybox-local-api; do
  install -o root -g root -m 644 "$REPO_DIR/systemd/${unit}.service" "/etc/systemd/system/${unit}.service"
done
udevadm control --reload-rules
udevadm trigger --subsystem-match=gpio || true
systemctl daemon-reload
systemctl enable storybox-player.service storybox-watcher.service storybox-local-api.service

echo
echo "Installation complete."
echo "Enabled: player, watcher, local API. Installed but disabled: Wi-Fi manager."
echo "Preserved: existing Wi-Fi profiles/configuration, API env/auth, stories, prompts and catalog."
echo "Reboot required for I2C0 and admin group membership."
echo "After reboot: bash scripts/verify.sh --device"
echo "Enable Wi-Fi fallback only after reviewing interfaces: sudo systemctl enable --now storybox-wifi.service"
