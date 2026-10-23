# StoryBox

Device-side software for the StoryBox offline audiobook player, targeting Orange Pi PC Plus / Armbian. This README is the setup guide for both the device owner and a new developer.

> **Network design warning:** Current code expects wlan0 to be the temporary StoryBox setup hotspot and wlan1 to connect to home Wi-Fi. When wlan1 connects, the hotspot stops; after about 30 seconds without a station connection, the hotspot starts again. If your board currently uses wlan0 for home Wi-Fi, do not apply this network setup unchanged: it repurposes wlan0 as the hotspot. Move home Wi-Fi to wlan1 first, or update and test code/config consistently. Do not run two network managers on the same interface.

## Features and scope
- Offline MP3 playback and WAV prompts; GPIO playback/menu/volume controls.
- Wi-Fi setup hotspot, captive portal, saved Wi-Fi and reconnection.
- Local device identity, device-info API, and a development-only QR.
- Not included: Story Manager, mobile app, backend APIs, real device registration/pairing, or cloud story sync. The QR only opens a local info page.

## Repository layout
```text
config/examples/       hostapd, dnsmasq and wpa_supplicant templates
config/network/        systemd-networkd template for wlan1
scripts/install.sh     migration helper, NOT a clean installer
scripts/verify.sh      basic repository/syntax checks
src/storybox/player/   offline story player
src/storybox/wifi/     Wi-Fi manager, portal and connection helper
src/storybox/          device identity, device info and QR draft
systemd/               Wi-Fi units and a player-service draft
```

## 1. Requirements and packages
Recommended target: Armbian/Debian-based Orange Pi PC Plus, user admin, two usable wireless interfaces (wlan0 hotspot and wlan1 home Wi-Fi), working audio output and GPIO wiring.
```bash
ip -br addr
iw dev
rfkill list
```
Install packages:
```bash
sudo apt update
sudo apt install -y git python3 iw wireless-tools wpasupplicant hostapd dnsmasq mpv libgpiod-tools qrencode iproute2
command -v python3 iw wpa_supplicant wpa_cli hostapd dnsmasq mpv gpiomon qrencode
```
Resolve missing commands for your OS before continuing. Wireless AP support and GPIO command compatibility vary by image.

## 2. Clone and verify
Fresh device:
```bash
cd /home/admin
git clone https://github.com/JoshiMitesh/storybox.git
cd /home/admin/storybox
git switch main
```
Existing clone:
```bash
cd /home/admin/storybox
git status --short --branch
git pull --ff-only
```
Run checks:
```bash
bash -n scripts/install.sh
bash -n scripts/verify.sh
python3 -m compileall -q src/storybox
bash scripts/verify.sh
```
These checks do not prove the hardware, Wi-Fi, captive portal, audio or GPIO works.

## 3. Configure Wi-Fi provisioning
### 3.1 Confirm the interface plan
Current code uses wlan0 as hotspot and wlan1 as station. Confirm both exist and wlan0 supports AP mode before proceeding. If home Wi-Fi currently runs on wlan0, stop until you move it or consistently change/test the interface plan.

### 3.2 Create configuration files
Set a unique hotspot password before use; do not use the placeholder on a deployed device.
```bash
sudo install -d -o root -g root -m 755 /etc/storybox
sudo install -o root -g root -m 600 config/examples/wpa_supplicant.conf.example /etc/storybox/wpa_supplicant.conf
sudo tee /etc/storybox/hostapd.conf >/dev/null <<'EOF'
interface=wlan0
driver=nl80211
country_code=IN
ssid=StoryBox-Setup
hw_mode=g
channel=6
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=CHANGE_THIS_TO_A_UNIQUE_PASSWORD
EOF
sudo chmod 600 /etc/storybox/hostapd.conf
sudo tee /etc/storybox/dnsmasq.conf >/dev/null <<'EOF'
interface=wlan0
bind-interfaces
listen-address=192.168.4.1
dhcp-range=192.168.4.10,192.168.4.100,255.255.255.0,12h
EOF
sudo chmod 644 /etc/storybox/dnsmasq.conf
sudo chown root:root /etc/storybox/wpa_supplicant.conf /etc/storybox/hostapd.conf /etc/storybox/dnsmasq.conf
sudo chmod 600 /etc/storybox/wpa_supplicant.conf /etc/storybox/hostapd.conf
sudo nano /etc/storybox/hostapd.conf
```
In nano, replace CHANGE_THIS_TO_A_UNIQUE_PASSWORD, save and exit. Never commit populated configs or passwords.

### 3.3 Configure DHCP for wlan1
```bash
sudo install -o root -g root -m 644 config/network/25-storybox-wlan1.network /etc/systemd/network/25-storybox-wlan1.network
```
The service template expects systemd-networkd. Check which service currently manages wlan1 before enabling it. Do not enable/restart network managers blindly, especially remotely. If NetworkManager owns wlan1, configure DHCP there instead and avoid competing management.

### 3.4 Install application and service files
The units expect source under /opt/storybox:
```bash
sudo install -d -o root -g root -m 755 /opt/storybox/src /opt/storybox/config /opt/storybox/systemd
sudo cp -a src/storybox /opt/storybox/src/
sudo cp -a config/. /opt/storybox/config/
sudo cp -a systemd/. /opt/storybox/systemd/
sudo chown -R root:root /opt/storybox
sudo find /opt/storybox/src/storybox -type d -name __pycache__ -prune -exec rm -rf {} +
sudo find /opt/storybox/src/storybox -type f -name '*.py[co]' -delete
sudo install -o root -g root -m 644 systemd/storybox-wpa.service /etc/systemd/system/storybox-wpa.service
sudo install -o root -g root -m 644 systemd/storybox-wifi.service /etc/systemd/system/storybox-wifi.service
sudo systemctl daemon-reload
```
The StoryBox Wi-Fi manager starts hostapd, dnsmasq and the portal itself. Do not separately enable stock hostapd.service or dnsmasq.service at the same time; duplicate processes may conflict.

### 3.5 Start the Wi-Fi services
Only after confirming interface layout and config:
```bash
sudo systemctl enable --now storybox-wpa.service
sudo systemctl enable --now storybox-wifi.service
systemctl --no-pager --full status storybox-wpa.service storybox-wifi.service
journalctl -u storybox-wpa.service -u storybox-wifi.service -n 100 --no-pager
```
The station service connects wlan1. The manager starts the setup AP on wlan0 after about 30 seconds without a station connection.

## 4. First-time phone Wi-Fi setup
1. Join Wi-Fi network StoryBox-Setup using the password in /etc/storybox/hostapd.conf.
2. If the setup page does not open automatically, browse to **http://192.168.4.1/**.
3. Select home Wi-Fi, enter its password and press Connect to Wi-Fi.
4. The portal connects wlan1 with wpa_cli and saves credentials in /etc/storybox/wpa_supplicant.conf.
5. When connected, the setup hotspot stops and the phone may disconnect. This is expected.
6. Confirm connection:
```bash
ip -4 -br addr
sudo wpa_cli -i wlan1 status
sudo wpa_cli -i wlan1 list_networks
```
When the saved network is unavailable, the setup hotspot should return after three manager checks.

## 5. Offline story player and audio data
Paths used by the current player:
- MP3 stories: /home/admin/stories/
- Catalog: /home/admin/story-library.json
- Voice prompts: /home/admin/story-prompts/
- Welcome prompt: /home/admin/story-prompts/welcome.wav
- MPV IPC socket: /tmp/lunii-player.sock
```bash
mkdir -p /home/admin/stories /home/admin/story-prompts
```
The catalog is a JSON array; each entry needs filename and prompt values matching existing files:
```json
[
  {
    "filename": "story-01.mp3",
    "prompt": "story-01.wav"
  }
]
```
Save this as /home/admin/story-library.json, put the MP3 in stories/ and matching prompt WAV in story-prompts/. Ensure files are readable by admin. The welcome WAV is optional.
```bash
aplay -l
command -v mpv gpiomon
ls -l /dev/gpiochip*
```
Current assumptions: ALSA device plughw:0,0 and GPIO chip gpiochip0. Confirm actual wiring and numbering:

| GPIO line | Action |
|---:|---|
| 6 | Play/pause |
| 1 | Next |
| 0 | Previous |
| 3 | OK/select |
| 7 | Volume down |
| 8 | Home |
| 9 | Volume up |

Manual player test:
```bash
sudo -u admin /usr/bin/python3 /opt/storybox/src/storybox/player/story_player.py
```
Stop with Ctrl+C. systemd/storybox-player.service.draft is not installed/enabled and contains a legacy path. Create and review a correct service with valid paths and audio/GPIO permissions before enabling boot playback.

## 6. Device ID, info API and development QR
Device ID is generated once and stored at /home/admin/.local/share/storybox/device.json.
```bash
cd /opt/storybox
PYTHONPATH=/opt/storybox/src /usr/bin/python3 -m storybox.device_identity
```
Run the development info server in a terminal:
```bash
PYTHONPATH=/opt/storybox/src /usr/bin/python3 -u -m storybox.device_info
```
The server listens on port 8088. Test the API:
```bash
curl -sS http://127.0.0.1:8088/api/device-info
echo
```
Open the page using an IP reachable from the phone, e.g. http://192.168.1.25:8088/ on the same LAN or http://192.168.4.1:8088/ while the hotspot is active.

**QR limitation:** src/storybox/pairing.py currently hard-codes http://192.168.1.25:8088/. Edit DEVICE_INFO_URL in that file to the URL reachable from the phone before generating:
```bash
PYTHONPATH=/opt/storybox/src /usr/bin/python3 -m storybox.pairing
```
QR PNG and draft JSON are stored under /home/admin/.local/share/storybox/. This is a development QR that opens a local page only; it does not register/pair with an app or backend. Do not expose the development server to untrusted networks.

## 7. Troubleshooting
```bash
ip -br addr
iw dev
sudo wpa_cli -i wlan1 status
systemctl --no-pager --full status storybox-wpa.service storybox-wifi.service
journalctl -u storybox-wpa.service -u storybox-wifi.service -n 100 --no-pager
pgrep -a 'hostapd|dnsmasq|portal.py' || true
curl -sS --max-time 5 http://127.0.0.1:8088/api/device-info
```
- **No wlan1:** check adapter, driver and rfkill; not every board has two interfaces.
- **Hotspot not visible:** inspect service logs, AP-mode support, and hostapd config/password.
- **Portal won't open:** browse to http://192.168.4.1/; check dnsmasq, portal process and wlan0 address.
- **Credentials not saved:** inspect logs and ensure /etc/storybox/wpa_supplicant.conf is root-owned with mode 600.
- **No sound:** test ALSA/MPV and verify story paths.
- **Buttons fail:** check wiring, GPIO numbering, gpiomon and libgpiod version.

## 8. Migration helper
scripts/install.sh is a migration helper, not a clean-device installer. It requires an existing saved Wi-Fi config and existing hotspot/dnsmasq configs to preserve. It backs up files, installs source under /opt/storybox, prepares Wi-Fi units and reloads systemd; it does not restart services. Review it and take a backup before using on an already-configured device.

## 9. Security and development status
Never commit populated Wi-Fi configs, passwords, keys, tokens, private MP3/WAV files, story catalogs, logs, backups, device identity or generated pairing drafts. Keep Wi-Fi credentials root-owned with mode 600 and replace development passwords before deployment.

Repository checks cover required files, Python syntax, legacy paths and basic credential hygiene only. Clean-device provisioning and hardware behavior still require testing on each target image. Mobile app/backend integration, production registration and cloud synchronization remain out of scope.
