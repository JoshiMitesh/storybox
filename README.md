# StoryBox

Device-side software for the StoryBox offline audiobook player, targeting Orange Pi PC Plus / Armbian. This README is the setup guide for both the device owner and a new developer.

> **Network design:** `wlan0` is the NetworkManager-managed home Wi-Fi client. `wlan1` is the temporary StoryBox-Setup access point. The manager starts the AP after three 10-second checks without a client connection and stops it after `wlan0` reconnects. The installer does not create backups or automatically restart the Wi-Fi manager.

## Features and scope
- Offline MP3 playback and WAV prompts; GPIO playback/menu/volume controls.
- Wi-Fi setup hotspot, captive portal, saved Wi-Fi and reconnection.
- Local device identity, device-info API, and a development-only QR.
- Not included: Story Manager, mobile app, backend APIs, real device registration/pairing, or cloud story sync. The QR only opens a local info page.

## Repository layout
```text
config/examples/       hostapd, dnsmasq and wpa_supplicant templates
config/network/        optional network templates
scripts/install.sh     backup-free installer
scripts/verify.sh      basic repository/syntax checks
src/storybox/player/   offline story player
src/storybox/wifi/     Wi-Fi manager, portal and connection helper
src/storybox/          device identity, device info and QR draft
systemd/               Wi-Fi units and a player-service draft
```

## 1. Requirements and packages
Recommended target: Armbian/Debian-based Orange Pi PC Plus, user admin, two usable wireless interfaces (wlan0 home Wi-Fi and wlan1 setup hotspot), working audio output and GPIO wiring.
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
The intended mapping is `wlan0` = home Wi-Fi client managed by NetworkManager and `wlan1` = fallback AP. Confirm both interfaces exist and `wlan1` supports AP mode. Do not run a separate `wpa_supplicant` service on `wlan0`.

### 3.2 Install Wi-Fi configuration

Run the repository installer. It creates missing hotspot/DHCP configuration, generates a unique AP password, and prints that password. Existing hotspot settings and passwords are preserved, while the AP interface is normalized to wlan1.

```bash
sudo bash scripts/install.sh
```

The installer is backup-free. It preserves NetworkManager's saved home Wi-Fi profiles and does not restart the Wi-Fi manager automatically.

### 3.3 Install and activate

The installer installs the source and service files under `/opt/storybox`. It uses NetworkManager for wlan0 and removes the obsolete standalone StoryBox WPA unit.

When you have local access or a safe recovery route, activate the manager:

```bash
sudo systemctl enable --now storybox-wifi.service
systemctl --no-pager --full status storybox-wifi.service
journalctl -u storybox-wifi.service -n 100 --no-pager
```


Only after confirming interface layout and config:
```bash
sudo systemctl enable --now storybox-wifi.service
systemctl --no-pager --full status storybox-wifi.service
journalctl -u storybox-wifi.service -n 100 --no-pager
```
NetworkManager connects `wlan0`. The manager starts the setup AP on `wlan1` after about 30 seconds without a client connection.

## 4. First-time phone Wi-Fi setup
1. Join Wi-Fi network StoryBox-Setup using the password in /etc/storybox/hostapd.conf.
2. If the setup page does not open automatically, browse to **http://192.168.4.1/**.
3. Select home Wi-Fi, enter its password and press Connect to Wi-Fi.
4. The portal asks NetworkManager to connect `wlan0` and persist the selected network.
5. When connected, the setup hotspot stops and the phone may disconnect. This is expected.
6. Confirm connection:
```bash
ip -4 -br addr
nmcli -f DEVICE,STATE,CONNECTION device status
nmcli connection show --active
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
nmcli -f DEVICE,STATE,CONNECTION device status
systemctl --no-pager --full status storybox-wpa.service storybox-wifi.service
journalctl -u storybox-wpa.service -u storybox-wifi.service -n 100 --no-pager
pgrep -a 'hostapd|dnsmasq|portal.py' || true
curl -sS --max-time 5 http://127.0.0.1:8088/api/device-info
```
- **No wlan1:** check adapter, driver and rfkill; not every board has two interfaces.
- **Hotspot not visible:** inspect service logs, AP-mode support, and hostapd config/password.
- **Portal won't open:** browse to http://192.168.4.1/; check dnsmasq, portal process and wlan1 address.
- **Credentials not saved:** inspect logs and ensure /etc/storybox/wpa_supplicant.conf is root-owned with mode 600.
- **No sound:** test ALSA/MPV and verify story paths.
- **Buttons fail:** check wiring, GPIO numbering, gpiomon and libgpiod version.

## 8. Installer behavior
`scripts/install.sh` is backup-free. It preserves existing device-specific hotspot/DNS configuration and NetworkManager connection profiles, creates missing hotspot configuration with a generated unique password, removes the obsolete standalone StoryBox WPA unit and wlan1 DHCP-client networkd file, and does not restart the Wi-Fi manager automatically.

## 9. Security and development status
Never commit populated Wi-Fi configs, passwords, keys, tokens, private MP3/WAV files, story catalogs, logs, backups, device identity or generated pairing drafts. Keep Wi-Fi credentials root-owned with mode 600 and replace development passwords before deployment.

Repository checks cover required files, Python syntax, legacy paths and basic credential hygiene only. Clean-device provisioning and hardware behavior still require testing on each target image. Mobile app/backend integration, production registration and cloud synchronization remain out of scope.
