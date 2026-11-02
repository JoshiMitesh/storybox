#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0
pass() { printf 'PASS: %s\n' "$*"; }
fail_check() { printf 'FAIL: %s\n' "$*"; fail=1; }

echo "=== Required StoryBox files ==="
for f in \
    scripts/install.sh scripts/storybox_watcher.py \
    src/storybox/player/story_player.py \
    src/storybox/wifi/wifi_manager.py \
    src/storybox/wifi/portal.py src/storybox/wifi/connect_wifi.py \
    systemd/storybox-player.service systemd/storybox-watcher.service \
    systemd/storybox-wifi.service \
    config/examples/hostapd.conf.example config/examples/dnsmasq.conf.example \
    udev/99-storybox-gpio.rules; do
    [[ -f "$f" ]] && pass "$f" || fail_check "Missing $f"
done

echo
echo "=== Shell syntax ==="
if bash -n scripts/install.sh && bash -n scripts/verify.sh; then
    pass "Installer and verifier shell syntax"
else
    fail_check "Shell syntax"
fi

echo
echo "=== Python syntax ==="
if python3 -m py_compile \
    scripts/storybox_watcher.py \
    src/storybox/player/story_player.py \
    src/storybox/wifi/wifi_manager.py \
    src/storybox/wifi/portal.py \
    src/storybox/wifi/connect_wifi.py; then
    pass "All runtime Python files compile"
else
    fail_check "Python syntax"
fi

echo
echo "=== GPIO event format ==="
if grep -Fq -- '--format' src/storybox/player/story_player.py \
   && grep -Fq 'falling\s+gpiochip0' src/storybox/player/story_player.py; then
    pass "GPIO event output matches player parser"
else
    fail_check "GPIO event format/parser mismatch"
fi

echo
echo "=== Piper provisioning ==="
if grep -q 'piper_linux_armv7l.tar.gz' scripts/install.sh \
   && grep -q 'en_US-lessac-medium.onnx' scripts/install.sh \
   && grep -q 'sha256sum --check' scripts/install.sh; then
    pass "ARMv7 Piper, Lessac model and checksum verification configured"
else
    fail_check "Piper installation or model verification missing"
fi

echo
echo "=== Unique hotspot credentials ==="
if grep -q 'secrets.token_hex(9)' scripts/install.sh \
   && ! grep -q '^wpa_passphrase=12345678$' config/examples/hostapd.conf.example; then
    pass "Fresh installation generates a unique hotspot password"
else
    fail_check "Hotspot password is fixed or not generated"
fi

echo
echo "=== Captive portal network ==="
if grep -q '^interface=wlan1$' config/examples/dnsmasq.conf.example \
   && grep -Fq 'address=/#/192.168.4.1' config/examples/dnsmasq.conf.example \
   && grep -q 'GENERAL.NM-MANAGED' src/storybox/wifi/connect_wifi.py \
   && grep -q 'wlan1' scripts/install.sh; then
    pass "wlan1 AP and captive DNS configuration present"
else
    fail_check "Wi-Fi fallback configuration incomplete"
fi

echo
echo "=== Systemd deployment ==="
if grep -q 'storybox-player.service' scripts/install.sh \
   && grep -q 'storybox-watcher.service' scripts/install.sh \
   && grep -q 'storybox-wifi.service' scripts/install.sh \
   && grep -q 'systemctl enable --now storybox-player.service' scripts/install.sh \
   && grep -q 'systemctl enable --now storybox-watcher.service' scripts/install.sh \
   && grep -q 'systemctl enable --now storybox-wifi.service' scripts/install.sh; then
    pass "Player, watcher and Wi-Fi services are installed and enabled"
else
    fail_check "One or more services are not enabled by installer"
fi

echo
echo "=== Runtime data excluded from repository ==="
if find . -type f \( -name '*.mp3' -o -name '*.wav' \
    -o -name 'story-library.json' -o -name 'wpa_supplicant.conf' \
    -o -name '*.pem' -o -name '*.key' \) -print | grep .; then
    fail_check "Review runtime media, catalog or secret files listed above"
else
    pass "No obvious device-specific media, catalog or Wi-Fi secret files"
fi

echo
if [[ "$fail" -eq 0 ]]; then
    echo "All repository verification checks passed."
else
    echo "One or more verification checks failed."
fi
exit "$fail"
