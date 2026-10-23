# StoryBox

## Wi-Fi setup

- `wlan0`: saved home Wi-Fi, managed by NetworkManager.
- `wlan1`: StoryBox-Setup hotspot.
- Hotspot password: `12345678`.
- Portal: `http://192.168.4.1/`.

### Install / update

```bash
cd ~/storybox
git pull --ff-only origin fix/wlan0-client-wlan1-fallback-hotspot
bash -n scripts/install.sh
bash -n scripts/verify.sh
bash scripts/verify.sh
sudo bash scripts/install.sh
```

### Start hotspot manager

```bash
sudo systemctl enable --now storybox-wifi.service
systemctl --no-pager --full status storybox-wifi.service
journalctl -u storybox-wifi.service -n 80 --no-pager
```

### Connect phone to StoryBox

1. Connect phone to `StoryBox-Setup` with password `12345678`.
2. Open `http://192.168.4.1/` manually if the portal does not open automatically.
3. Select home Wi-Fi and enter its password.

### Diagnose portal / hotspot

Run on the StoryBox device:

```bash
nmcli -f DEVICE,STATE,CONNECTION device status
ip -4 addr show wlan1
sudo grep -E '^(interface|listen-address|dhcp-range|dhcp-option|address)=' /etc/storybox/dnsmasq.conf
sudo grep -E '^(interface|ssid|wpa_passphrase)=' /etc/storybox/hostapd.conf
systemctl --no-pager --full status storybox-wifi.service
sudo journalctl -u storybox-wifi.service -n 100 --no-pager
pgrep -a 'hostapd|dnsmasq|portal.py' || true
curl -i --max-time 3 http://192.168.4.1/
```

### Check required packages

```bash
sudo apt update
sudo apt install -y iw wpasupplicant hostapd dnsmasq
command -v iw wpa_supplicant wpa_cli hostapd dnsmasq
```

### Other device commands

```bash
ip -br addr
nmcli connection show --active
bash -n scripts/install.sh
bash -n scripts/verify.sh
bash scripts/verify.sh
```

## Offline player paths

- Stories: `/home/admin/stories/`
- Catalog: `/home/admin/story-library.json`
- Prompts: `/home/admin/story-prompts/`
- MPV IPC socket: `/tmp/lunii-player.sock`

Manual player run:

```bash
sudo -u admin /usr/bin/python3 /opt/storybox/src/storybox/player/story_player.py
```
