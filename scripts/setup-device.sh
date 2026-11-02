#!/usr/bin/env bash
set -Eeuo pipefail
REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DEVICE_USER="${SUDO_USER:-admin}"
INSTALL_DIR="/opt/storybox"
STORIES_DIR="/home/admin/stories"
PROMPTS_DIR="/home/admin/story-prompts"
CATALOG="/home/admin/story-library.json"

if [[ "$EUID" -ne 0 ]]; then echo "Run: sudo bash scripts/setup-device.sh"; exit 1; fi
if [[ "$DEVICE_USER" != "admin" ]] || ! id admin >/dev/null 2>&1; then
  echo "ERROR: This setup expects the 'admin' account."; exit 1
fi
for f in src/storybox/player/story_player.py scripts/storybox_watcher.py systemd/storybox-player.service systemd/storybox-watcher.service udev/99-storybox-gpio.rules; do
  [[ -f "$REPO_DIR/$f" ]] || { echo "Missing repository file: $f"; exit 1; }
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y python3 mpv gpiod ffmpeg alsa-utils
command -v gpiomon >/dev/null
gpiomon --help 2>&1 | grep -q -- '-c' || { echo "ERROR: gpiomon must support -c."; exit 1; }

if [[ ! -x /opt/piper/piper || ! -f /opt/piper/models/en_US-lessac-medium.onnx ]]; then
  echo "ERROR: Piper/model missing. Install ARMv7 Piper at /opt/piper/piper and model at /opt/piper/models/en_US-lessac-medium.onnx."
  echo "See README.md. Setup stopped before enabling services."; exit 1
fi

getent group gpio >/dev/null || groupadd --system gpio
usermod -aG gpio,audio admin
install -d -o root -g root -m 755 /opt/storybox/src/storybox/player /opt/storybox/scripts
install -d -o admin -g admin -m 755 "$STORIES_DIR" "$PROMPTS_DIR"
install -o root -g root -m 644 "$REPO_DIR/src/storybox/player/story_player.py" /opt/storybox/src/storybox/player/story_player.py
install -o root -g root -m 755 "$REPO_DIR/scripts/storybox_watcher.py" /opt/storybox/scripts/storybox_watcher.py

if [[ ! -f "$CATALOG" ]]; then printf '[]\n' > "$CATALOG"; fi
chown admin:admin "$CATALOG"
chmod 664 "$CATALOG"
install -o root -g root -m 644 "$REPO_DIR/udev/99-storybox-gpio.rules" /etc/udev/rules.d/99-storybox-gpio.rules
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-player.service" /etc/systemd/system/storybox-player.service
install -o root -g root -m 644 "$REPO_DIR/systemd/storybox-watcher.service" /etc/systemd/system/storybox-watcher.service
udevadm control --reload-rules
udevadm trigger --subsystem-match=gpio || true
systemctl daemon-reload
systemctl enable storybox-player.service storybox-watcher.service
echo "Setup complete. Reboot required for group membership: sudo reboot"
