# StoryBox

Standalone offline audio story player for Orange Pi PC Plus.

## One-command installation (fresh device)

### Supported hardware

- Orange Pi PC Plus running Armbian/Debian 32-bit ARMv7 (armv7l, armhf).
- Existing Linux user account named **admin**.
- Two Wi-Fi interfaces: **wlan0** for home Wi-Fi and **wlan1** for the temporary setup hotspot.
- StoryBox buttons wired to the GPIO lines configured in **src/storybox/player/story_player.py**.
- ALSA audio output available as **plughw:0,0**.
- Internet access during installation to install OS packages and download Piper plus its voice model.

> Run this installer on a **new/fresh StoryBox device**, not on an existing working StoryBox without reviewing its current network and service configuration. It installs packages, configures NetworkManager, writes system files, and enables services.

### Install

Run these commands on the new Orange Pi:

~~~bash
sudo apt update
sudo apt install -y git
git clone https://github.com/JoshiMitesh/storybox.git
cd storybox
git checkout main
sudo bash scripts/install.sh
~~~

The installer:

1. Checks the board architecture, **admin** account, and both Wi-Fi interfaces.
2. Installs MPV, gpiod, ffmpeg, ALSA tools, NetworkManager, hostapd, dnsmasq, iw, iproute2, curl and other required packages.
3. Downloads the official Piper 1.2.0 ARMv7 release and the English Lessac medium voice model. The model download is checked against its pinned SHA-256 digest.
4. Generates the welcome prompt locally with Piper.
5. Installs the offline player, story watcher, Wi-Fi manager and captive portal under **/opt/storybox**.
6. Adds the admin user to the gpio and audio groups and installs the GPIO udev rule.
7. Configures NetworkManager to own **wlan0** and leave **wlan1** for the setup hotspot.
8. Generates a unique WPA2 password for the **StoryBox-Setup** hotspot on a fresh install.
9. Installs and enables the player, watcher and Wi-Fi manager services.

At the end, the installer prints the hotspot SSID, password and portal address. Save the password.

### First Wi-Fi connection

1. Wait approximately 30 seconds after installation if the device has no saved home Wi-Fi connection.
2. Connect your phone to the **StoryBox-Setup** Wi-Fi network using the password printed by the installer.
3. Open **http://192.168.4.1/** in your phone browser if the setup page does not open automatically.
4. Select your home Wi-Fi network and enter its password.
5. After the connection succeeds, the setup hotspot stops automatically. The device uses the saved home Wi-Fi connection on subsequent boots.

The fallback hotspot starts only after the Wi-Fi manager detects that wlan0 has remained disconnected for three checks (10 seconds apart). The portal is therefore not expected to be available while the device is already connected to home Wi-Fi.

### Verify installation

~~~bash
sudo systemctl status storybox-player.service storybox-watcher.service storybox-wifi.service --no-pager
sudo journalctl -u storybox-player.service -b --no-pager
sudo journalctl -u storybox-watcher.service -b --no-pager
sudo journalctl -u storybox-wifi.service -b --no-pager
id admin
ls -l /dev/gpiochip*
~~~

A reboot is recommended after installation so the new group membership and GPIO udev permissions are applied to all login sessions.

## Offline player

The player starts MPV with ALSA output **plughw:0,0** and listens for the seven configured GPIO buttons. The GPIO event output format is matched to the event parser in the player source.

### Story library

Copy supported audio files into:

**/home/admin/stories/**

Supported extensions:

- .mp3
- .wav
- .m4a
- .ogg
- .flac

The watcher waits for each file copy to finish, derives a clean title from the filename, generates a spoken WAV prompt using local Piper, and synchronizes **/home/admin/story-library.json**.

| Filename | Spoken prompt |
|---|---|
| The-Golden-Key.mp3 | The Golden Key |
| clever_rabbit.mp3 | Clever Rabbit |
| My__Little--Star.mp3 | My Little Star |

Deleting a story removes its catalog entry and deletes its generated prompt only when no remaining story uses that prompt. The welcome prompt is preserved.

## Services

~~~bash
sudo systemctl status storybox-player.service --no-pager
sudo systemctl status storybox-watcher.service --no-pager
sudo systemctl status storybox-wifi.service --no-pager

sudo systemctl restart storybox-player.service
sudo systemctl restart storybox-watcher.service
sudo systemctl restart storybox-wifi.service

sudo journalctl -fu storybox-watcher.service
sudo journalctl -fu storybox-wifi.service
~~~

The Wi-Fi manager starts and stops its own foreground hostapd, dnsmasq and portal processes during fallback. Do not separately enable the distribution hostapd or dnsmasq services.

## Device paths

- Player: **/opt/storybox/src/storybox/player/story_player.py**
- Watcher: **/opt/storybox/scripts/storybox_watcher.py**
- Wi-Fi manager: **/opt/storybox/src/storybox/wifi/wifi_manager.py**
- Captive portal: **/opt/storybox/src/storybox/wifi/portal.py**
- Stories: **/home/admin/stories/**
- Prompts: **/home/admin/story-prompts/**
- Catalog: **/home/admin/story-library.json**
- Piper: **/opt/piper/piper**
- Piper voice: **/opt/piper/models/en_US-lessac-medium.onnx**
- Wi-Fi configuration: **/etc/storybox/**
- MPV IPC socket: **/tmp/lunii-player.sock**

## Repository checks

Run these checks from the repository before deployment:

~~~bash
bash -n scripts/install.sh
bash -n scripts/verify.sh
python3 -m py_compile \
  scripts/storybox_watcher.py \
  src/storybox/player/story_player.py \
  src/storybox/wifi/wifi_manager.py \
  src/storybox/wifi/portal.py \
  src/storybox/wifi/connect_wifi.py
bash scripts/verify.sh
~~~

Do not commit story audio, generated prompts, catalog data, Piper model files, Wi-Fi credentials, or device-specific secrets.
