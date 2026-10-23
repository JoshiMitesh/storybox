#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0

check() {
    if "$@"; then
        echo "PASS: $*"
    else
        echo "FAIL: $*"
        fail=1
    fi
}

echo "=== Required repository files ==="
for f in \
    README.md \
    src/storybox/wifi/wifi_manager.py \
    src/storybox/wifi/portal.py \
    src/storybox/wifi/connect_wifi.py \
    src/storybox/player/story_player.py \
    systemd/storybox-wifi.service \
    config/examples/hostapd.conf.example \
    config/examples/dnsmasq.conf.example \
    config/examples/wpa_supplicant.conf.example
do
    if [[ -f "$f" ]]; then
        echo "PASS: $f"
    else
        echo "FAIL: Missing $f"
        fail=1
    fi
done

echo
echo "=== Python syntax ==="
if python3 -m py_compile \
    src/storybox/wifi/wifi_manager.py \
    src/storybox/wifi/portal.py \
    src/storybox/wifi/connect_wifi.py \
    src/storybox/player/story_player.py
then
    echo "PASS: Python syntax"
else
    echo "FAIL: Python syntax"
    fail=1
fi

echo
echo "=== Old Wi-Fi code paths ==="
if grep -RInE \
    '/home/admin/storybox-wifi|/home/admin/storybox-hotspot\.conf|/home/admin/storybox-dnsmasq\.conf' \
    src systemd
then
    echo "FAIL: Old paths remain in source or service templates"
    fail=1
else
    echo "PASS: No old Wi-Fi code paths"
fi

echo
echo "=== Basic credential hygiene ==="
if find . -type f \( \
    -name 'wpa_supplicant.conf' -o \
    -name '*.pem' -o \
    -name '*.key' -o \
    -name '*.mp3' -o \
    -name '*.wav' -o \
    -name 'story-library.json' \
\) -print | grep .
then
    echo "FAIL: Review the listed local/private files before committing"
    fail=1
else
    echo "PASS: No obvious private runtime files found"
fi

echo
echo "=== NetworkManager CLI compatibility ==="
if grep -q 'GENERAL.NM-MANAGED device show wlan0' scripts/install.sh && ! grep -q 'GENERAL.MANAGED device show wlan0' scripts/install.sh; then
    echo "PASS: Installer uses GENERAL.NM-MANAGED"
else
    echo "FAIL: Installer NetworkManager managed-status property is incorrect"
    fail=1
fi

echo
echo "=== Fixed StoryBox hotspot password ==="
if grep -q '^wpa_passphrase=12345678
    echo "Verification checks passed."
else
    echo "One or more checks failed. Do not commit yet."
fi

exit "$fail"
 config/examples/hostapd.conf.example && grep -q "wpa_passphrase=12345678" scripts/install.sh; then
    echo "PASS: Setup hotspot password is fixed to 12345678"
else
    echo "FAIL: Setup hotspot password is not fixed to 12345678"
    fail=1
fi

echo
if [[ "$fail" -eq 0 ]]; then
    echo "Verification checks passed."
else
    echo "One or more checks failed. Do not commit yet."
fi

exit "$fail"
