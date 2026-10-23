# StoryBox

## Orange Pi dependencies

Install the tools used by the Wi-Fi hotspot, offline audio player, GPIO buttons, QR generator, and device-info API:

```bash
sudo apt update
sudo apt install -y git python3 network-manager iw wireless-tools wpasupplicant hostapd dnsmasq mpv gpiod qrencode iproute2 curl alsa-utils
```

Check installed commands:

```bash
command -v git python3 nmcli iw wpa_supplicant hostapd dnsmasq mpv gpiomon qrencode ip curl aplay
gpiomon --version
```

On the current Armbian/Debian Orange Pi image, install `gpiod` (not `libgpiod-tools`). Python modules used by the current device scripts are from the standard library; no `pip install` is required. The player expects `gpiomon` with `-c`, `-b` and `-e` options, so confirm your installed version supports those options.

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

## QR device-info test

The QR opens the local device-info page (not backend pairing). Connect StoryBox and your phone to the same home Wi-Fi.

Terminal 1 — start the device-info server:

```bash
cd ~/storybox
PYTHONPATH=src python3 -u -m storybox.device_info
```

Terminal 2 — test the API and generate a QR using the current `wlan0` IP:

```bash
cd ~/storybox
curl http://127.0.0.1:8088/api/device-info
PYTHONPATH=src python3 -m storybox.pairing
```

QR file: `/home/admin/.local/share/storybox/pairing-draft.png`

Optional: copy the QR image to your laptop (replace `<DEVICE_IP>` with the QR URL's IP):

```bash
scp admin@<DEVICE_IP>:/home/admin/.local/share/storybox/pairing-draft.png .
```

Open the PNG on your laptop and scan it with your phone. Keep Terminal 1 running while testing.
