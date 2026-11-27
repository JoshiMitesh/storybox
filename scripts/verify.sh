#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEVICE_MODE="${1:-}"
fail=0

pass() { echo "PASS: $*"; }
bad() { echo "FAIL: $*"; fail=1; }

echo "=== Required repository files ==="
for f in README.md requirements-dev.txt scripts/install-requirements.sh scripts/install-storybox.sh scripts/setup-device.sh scripts/install.sh scripts/storybox_watcher.py src/storybox/player/story_player.py src/storybox/local_api.py src/storybox/wifi/wifi_manager.py src/storybox/wifi/portal.py src/storybox/wifi/connect_wifi.py systemd/storybox-player.service systemd/storybox-watcher.service systemd/storybox-wifi.service systemd/storybox-local-api.service udev/99-storybox-gpio.rules config/local-api.env.example; do
  [[ -f "$f" ]] && pass "$f" || bad "Missing $f"
done

echo
echo "=== Shell syntax ==="
for f in scripts/*.sh; do
  if bash -n "$f"; then pass "$f"; else bad "Shell syntax: $f"; fi
done

echo
echo "=== Python syntax ==="
PY_FILES=(src/storybox/player/story_player.py src/storybox/local_api.py src/storybox/device_identity.py src/storybox/device_info.py src/storybox/pairing.py src/storybox/wifi/wifi_manager.py src/storybox/wifi/portal.py src/storybox/wifi/connect_wifi.py scripts/storybox_watcher.py)
if python3 -m py_compile "${PY_FILES[@]}"; then pass "Python modules compile"; else bad "Python compilation"; fi

echo
echo "=== Service unit structure ==="
for unit in storybox-player storybox-watcher storybox-wifi storybox-local-api; do
  file="systemd/${unit}.service"
  if grep -q '^\[Service\]$' "$file" && grep -q '^ExecStart=' "$file" && grep -q '^\[Install\]$' "$file"; then
    pass "$file"
  else
    bad "Invalid/incomplete service unit: $file"
  fi
done
grep -q '^SupplementaryGroups=.*i2c' systemd/storybox-player.service && pass "Player has I2C group access" || bad "Player unit lacks I2C group access"

echo
echo "=== Runtime safety checks ==="
if grep -RInE '/home/admin/storybox-wifi|/home/admin/storybox-hotspot\.conf|/home/admin/storybox-dnsmasq\.conf' src systemd; then
  bad "Legacy Wi-Fi paths remain"
else
  pass "No legacy Wi-Fi paths"
fi
if find . -type f \( -name 'wpa_supplicant.conf' -o -name '*.pem' -o -name '*.key' -o -name '*.mp3' -o -name '*.wav' -o -name 'story-library.json' -o -name 'auth.json' \) -print | grep .; then
  bad "Review private/device runtime files listed above"
else
  pass "No obvious private/device runtime files"
fi
grep -q 'GENERAL.NM-MANAGED device show wlan0' scripts/install.sh && pass "Wi-Fi installer checks NetworkManager ownership" || bad "Wi-Fi NetworkManager safety check missing"

if [[ "$DEVICE_MODE" == "--device" ]]; then
  echo
  echo "=== Live device checks ==="
  [[ "$(uname -m)" == "armv7l" || "$(uname -m)" == "armv8l" ]] && pass "ARMv7/armv8 machine" || bad "Unexpected CPU architecture"
  [[ -x /opt/piper/piper ]] && pass "Piper executable exists" || bad "Piper executable missing"
  [[ -s /opt/piper/models/en_US-lessac-medium.onnx ]] && pass "Piper voice model exists" || bad "Piper voice model missing"
  [[ -s /opt/piper/models/en_US-lessac-medium.onnx.json ]] && pass "Piper voice config exists" || bad "Piper voice config missing"
  [[ -e /dev/i2c-0 ]] && pass "/dev/i2c-0 exists" || bad "/dev/i2c-0 missing; check Armbian overlay and reboot"
  id admin | grep -qE '(^|[,(])gpio([,)]|$)' && pass "admin belongs to gpio" || bad "admin missing gpio group"
  id admin | grep -qE '(^|[,(])i2c([,)]|$)' && pass "admin belongs to i2c" || bad "admin missing i2c group"
  for unit in storybox-player storybox-watcher storybox-local-api; do
    systemctl is-enabled --quiet "$unit.service" && pass "$unit enabled" || bad "$unit is not enabled"
  done
  for unit in storybox-player storybox-watcher storybox-local-api; do
    systemctl is-active --quiet "$unit.service" && pass "$unit active" || bad "$unit is not active"
  done
  [[ -f /etc/storybox/local-api.env ]] && pass "API environment file exists" || bad "API environment file missing"
fi

echo
if [[ "$fail" -eq 0 ]]; then
  echo "All requested verification checks passed."
else
  echo "One or more verification checks failed."
fi
exit "$fail"
