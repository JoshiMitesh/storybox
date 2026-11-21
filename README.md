# StoryBox

Offline audio story player for the Orange Pi PC Plus. The device plays locally stored stories using physical buttons, MPV, and locally generated spoken prompts.

> **Branch note:** The stable player installer is on `main`. The local device API is under development on `feature/local-device-api`. The API branch is not a production deployment guide.

## Contents

- [Features](#features)
- [Device requirements](#device-requirements)
- [Install the player](#install-the-player)
- [Install Wi-Fi setup and fallback hotspot](#install-wi-fi-setup-and-fallback-hotspot)
- [Manage stories](#manage-stories)
- [Manage services](#manage-services)
- [Develop and test the local API](#develop-and-test-the-local-api)
- [Project layout](#project-layout)
- [Safety and current limitations](#safety-and-current-limitations)

## Features

- Offline playback of stories stored on the device.
- Physical-button control for playback, navigation, volume, and menu actions.
- Local Piper text-to-speech prompts.
- Automatic story catalog and prompt updates when audio files are added or removed.
- Optional Wi-Fi connection management and fallback setup hotspot.
- A development-only local HTTP API on `feature/local-device-api`.

## Device requirements

The player installer targets:

- Orange Pi PC Plus running Armbian/Debian (ARMv7/armhf).
- Linux user account named `admin`.
- Audio output available as ALSA `plughw:0,0`.
- GPIO buttons connected according to the mapping in `src/storybox/player/story_player.py`.
- ARMv7-compatible Piper executable at `/opt/piper/piper`.
- Piper voice model at `/opt/piper/models/en_US-lessac-medium.onnx`.

Piper and its voice model are external assets and are not included in this repository. Install both before running the player installer.

The optional Wi-Fi setup manager has additional requirements described in [Install Wi-Fi setup and fallback hotspot](#install-wi-fi-setup-and-fallback-hotspot).

## Install the player

On a fresh supported device:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/JoshiMitesh/storybox.git
cd storybox
git checkout main
```

Install the ARMv7 Piper binary and voice model at the paths above, then run:

```bash
sudo bash scripts/setup-device.sh
sudo reboot
```

The player installer installs `python3`, `mpv`, `gpiod`, `ffmpeg`, and `alsa-utils`; copies the player and watcher into `/opt/storybox`; installs the player and watcher systemd units and GPIO udev rule; creates the story directories; and enables the player and watcher services. It adds `admin` to the GPIO and audio groups. Reboot so the new group membership takes effect.

This script installs the player and story watcher only. It does **not** install the optional Wi-Fi setup manager or the development local API.

### Verify the player installation

After reboot:

```bash
systemctl status storybox-player.service storybox-watcher.service --no-pager
journalctl -u storybox-player.service -b --no-pager
journalctl -u storybox-watcher.service -b --no-pager
id admin
ls -l /dev/gpiochip*
```

## Install Wi-Fi setup and fallback hotspot

The Wi-Fi manager is a separate, optional installation. It uses:

- `wlan0` for the normal home Wi-Fi connection, managed by NetworkManager.
- `wlan1` for the temporary StoryBox setup hotspot.
- `hostapd` and `dnsmasq` to provide the hotspot and local portal at `http://192.168.4.1`.

Before running the installer, confirm that the device has both wireless interfaces and that NetworkManager manages `wlan0`. Install the required system packages if they are not already present: `network-manager`, `hostapd`, `dnsmasq`, `iw`, and `iproute2`.

From the repository root, run:

```bash
sudo bash scripts/install.sh
```

The script installs StoryBox Wi-Fi files and configuration under `/opt/storybox` and `/etc/storybox`, installs the `storybox-wifi.service` unit, and reloads systemd. It does **not** enable or start the service. Review the device's network configuration and confirm that `wlan1` is reserved for the StoryBox hotspot before activating it:

```bash
sudo systemctl enable --now storybox-wifi.service
sudo systemctl status storybox-wifi.service --no-pager
journalctl -u storybox-wifi.service -f
```

The manager starts the setup hotspot after it detects that `wlan0` has remained disconnected for approximately 30 seconds. It stops the hotspot when `wlan0` reconnects. Connect to the StoryBox setup Wi-Fi and open `http://192.168.4.1` to scan for and join a network.

> **Network-impact warning:** `scripts/install.sh` changes NetworkManager handling for `wlan1`, removes the legacy `storybox-wpa.service` unit and its networkd configuration, and writes hotspot configuration. Run it only when you understand the device's current network setup and have a recovery path. Keep local/HDMI access available while activating the Wi-Fi service.
>
> **Development security limitation:** The current installer enforces a fixed setup-hotspot passphrase (`12345678`). Do not treat this as a secure production credential or expose the setup hotspot beyond the intended setup process.

## Manage stories

Copy supported audio files into:

```text
/home/admin/stories/
```

Supported formats:

- MP3 (`.mp3`)
- WAV (`.wav`)
- M4A (`.m4a`)
- Ogg (`.ogg`)
- FLAC (`.flac`)

The watcher waits for file copying to finish, derives a readable title from each filename, generates a local WAV prompt with Piper, and updates the story catalog.

Examples:

| Audio filename | Spoken title |
|---|---|
| `The-Golden-Key.mp3` | The Golden Key |
| `clever_rabbit.mp3` | Clever Rabbit |
| `My__Little--Star.mp3` | My Little Star |

The catalog is stored at `/home/admin/story-library.json`; generated prompts are stored in `/home/admin/story-prompts/`. The welcome prompt is preserved when stories are removed.

## Manage services

Player and watcher:

```bash
sudo systemctl restart storybox-player.service
sudo systemctl restart storybox-watcher.service
sudo systemctl stop storybox-player.service
sudo systemctl start storybox-player.service
sudo journalctl -fu storybox-watcher.service
```

Optional Wi-Fi manager:

```bash
sudo systemctl status storybox-wifi.service --no-pager
sudo journalctl -fu storybox-wifi.service
```

## Develop and test the local API

The API is currently available on `feature/local-device-api`. It provides local device registration/authentication and device operations for future mobile-app integration. The API does not call the cloud backend. It is separate from the player and Wi-Fi manager and is not installed by either device installer.

### Get the development branch

```bash
git clone -b feature/local-device-api https://github.com/JoshiMitesh/storybox.git
cd storybox
```

### Set up the Python test environment

Python 3.10 or newer is required for the API source. On Debian/Armbian, install virtual-environment support if needed:

```bash
sudo apt update
sudo apt install -y python3-venv
```

Create and activate a virtual environment, then install the development test dependency:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

### Run checks

Run the full test suite from the repository root:

```bash
PYTHONPATH=src python -m pytest -q
```

Compile the API and Wi-Fi modules:

```bash
python -m py_compile src/storybox/local_api.py src/storybox/wifi/connect_wifi.py
```

### Run the API with isolated test data

Do not point a development API at the production StoryBox data. Start the API with a separate home directory and port:

```bash
export PYTHONPATH="$PWD/src"
export STORYBOX_HOME="$HOME/.storybox-api-test"
export STORYBOX_LIBRARY_DIR="$HOME/.storybox-api-test/library"
export STORYBOX_API_HOST=0.0.0.0
export STORYBOX_API_PORT=8090
unset STORYBOX_API_TOKEN

python -m storybox.local_api
```

From a browser on the same trusted local network, open:

```text
http://<ORANGE-PI-IP>:8090/console
```

Replace `<ORANGE-PI-IP>` with the device's current LAN IP address. Binding to `0.0.0.0` exposes the development server on network interfaces; use it only on a trusted network and stop it when testing is complete.

On first startup, the API opens a persisted ten-minute first-registration window. Register the fixed `admin` account with a password of at least ten characters and confirmation in the console. The window is not extended by restarting the API. Successful registration permanently closes it; later registration attempts are rejected. If the window expires before registration, use a fresh disposable test data directory for another registration test.

The API console signs in after registration and stores the returned bearer token for protected API requests. See [Local Device API documentation](docs/local-device-api.md) for endpoints, request formats, runtime settings, and current integration limitations.

> **Development status:** The local API is still under integration. Keep it separate from the production player installation. Do not enable the API systemd service or point it at production data as part of these tests. The API uses HTTP and bearer-token authentication; use it only on a trusted local network during development. Sync/download behavior is not covered by these setup instructions or routine smoke tests.

## Project layout

```text
src/storybox/
  device_identity.py        Persistent device identity
  device_info.py             Device information
  local_api.py               Local device API (development branch)
  pairing.py                 Pairing helpers
  player/
    story_player.py          Physical-button audio player
  web/
    api_console.html         Local API development console
  wifi/
    connect_wifi.py          Wi-Fi connection helper
    portal.py                Setup hotspot web portal
    wifi_manager.py          Fallback hotspot manager

scripts/
  install.sh                 Optional Wi-Fi setup installer
  setup-device.sh            Orange Pi player installer
  storybox_watcher.py        Story catalog and prompt watcher
  verify.sh                  Repository verification checks

systemd/
  storybox-local-api.service  API unit (not enabled by the player installer)
  storybox-player.service
  storybox-watcher.service
  storybox-wifi.service       Optional Wi-Fi manager unit

tests/                        Automated tests
docs/
  local-device-api.md         Local API details and integration notes
```

## Safety and current limitations

- Do not commit passwords, Wi-Fi credentials, bearer tokens, provisioning data, private keys, or device identity files.
- Do not commit story audio, generated prompts, or device-specific story catalogs.
- Keep API development data under a separate test directory; do not use production data under `/home/admin` or `/opt/storybox`.
- Do not run destructive reset operations against a real device.
- Keep the setup hotspot on a trusted setup network. The current installer uses a fixed hotspot passphrase; this must be addressed before production use.
- The local API is a development implementation. Its transport security, final mobile-app integration contract, and deployment model still need to be agreed.
