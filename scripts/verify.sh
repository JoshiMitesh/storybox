#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
fail=0

echo "=== Required files ==="
for f in README.md src/storybox/wifi/wifi_manager.py src/storybox/wifi/portal.py src/storybox/wifi/connect_wifi.py src/storybox/player/story_player.py systemd/storybox-wifi.service config/examples/hostapd.conf.example config/examples/dnsmasq.conf.example config/examples/wpa_supplicant.conf.example; do
    if [[ -f "$f" ]]; then echo "PASS: $f"; else echo "FAIL: Missing $f"; fail=1; fi
done

echo
echo "=== Shell syntax ==="
if bash -n scripts/install.sh && bash -n scripts/verify.sh; then echo "PASS: Shell syntax"; else echo "FAIL: Shell syntax"; fail=1; fi

echo
echo "=== Python syntax ==="
if python3 -m py_compile src/storybox/wifi/wifi_manager.py src/storybox/wifi/portal.py src/storybox/wifi/connect_wifi.py src/storybox/player/story_player.py; then echo "PASS: Python syntax"; else echo "FAIL: Python syntax"; fail=1; fi

echo
echo "=== Legacy paths ==="
if grep -RInE '/home/admin/storybox-wifi|/home/admin/storybox-hotspot\.conf|/home/admin/storybox-dnsmasq\.conf' src systemd; then echo "FAIL: Old paths remain"; fail=1; else echo "PASS: No old Wi-Fi code paths"; fi

echo
echo "=== Private runtime files ==="
if find . -type f \( -name 'wpa_supplicant.conf' -o -name '*.pem' -o -name '*.key' -o -name '*.mp3' -o -name '*.wav' -o -name 'story-library.json' \) -print | grep .; then echo "FAIL: Review private files listed above"; fail=1; else echo "PASS: No obvious private runtime files"; fi

echo
echo "=== NetworkManager property ==="
if grep -q 'GENERAL.NM-MANAGED device show wlan0' scripts/install.sh && ! grep -q 'GENERAL.MANAGED device show wlan0' scripts/install.sh; then echo "PASS: Installer uses GENERAL.NM-MANAGED"; else echo "FAIL: Incorrect NetworkManager property"; fail=1; fi

echo
echo "=== Fixed hotspot password ==="
if grep -q '^wpa_passphrase=12345678$' config/examples/hostapd.conf.example && grep -q 'wpa_passphrase=12345678' scripts/install.sh; then echo "PASS: Fixed hotspot password configured"; else echo "FAIL: Fixed hotspot password missing"; fail=1; fi

echo
echo "=== Captive portal DNS ==="
if grep -q '^dhcp-option=6,192.168.4.1$' config/examples/dnsmasq.conf.example && grep -Fq 'address=/#/192.168.4.1' config/examples/dnsmasq.conf.example && grep -q 'GENERAL.NM-MANAGED' src/storybox/wifi/connect_wifi.py; then echo "PASS: Captive DNS and NetworkManager helper configured"; else echo "FAIL: Captive DNS or NetworkManager helper missing"; fail=1; fi

echo
if [[ "$fail" -eq 0 ]]; then echo "Verification checks passed."; else echo "One or more checks failed."; fi
exit "$fail"
