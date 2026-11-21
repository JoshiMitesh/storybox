# StoryBox

Offline audio story player for the Orange Pi PC Plus. The device plays locally stored stories using physical buttons, MPV, and locally generated spoken prompts.

> **Branch note:** The stable device installer is on `main`. The local device API is under active development on `feature/local-device-api`. The API branch is not a production deployment guide.

## Contents

- [Features](#features)
- [Device requirements](#device-requirements)
- [Install the player](#install-the-player)
- [Manage stories](#manage-stories)
- [Manage services](#manage-services)
- [Develop and test the local API](#develop-and-test-the-local-api)
- [Project layout](#project-layout)
- [Safety and data](#safety-and-data)

## Features

- Offline playback of stories stored on the device.
- Physical-button control for playback, navigation, volume, and menu actions.
- Local Piper text-to-speech prompts.
- Automatic story catalog and prompt updates when audio files are added or removed.
- Separate Wi-Fi management and setup portal.
- A development-only local HTTP API on `feature/local-device-api`.

## Device requirements

The one-command installer targets:

- Orange Pi PC Plus running Armbian/Debian (ARMv7/armhf).
- Linux user account named `admin`.
- Audio output available as ALSA `plughw:0,0`.
- GPIO buttons connected according to the mapping in `src/storybox/player/story_player.py`.
- ARMv7-compatible Piper executable at `/opt/piper/piper`.
- Piper voice model at `/opt/piper/models/en_US-lessac-medium.onnx`.

Piper and its voice model are external assets and are not included in this repository. Install both before running the device installer.

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

The installer installs the player and watcher dependencies, copies the player files into `/opt/storybox`, installs the systemd units and GPIO udev rule, creates story directories, and enables the player and watcher services. It adds `admin` to the GPIO and audio groups; reboot so the new group membership takes effect.

The installer does **not** configure Wi-Fi or install the development local API.

### Verify the installation

After reboot:

```bash
systemctl status storybox-player.service storybox-watcher.service --no-pager
journalctl -u storybox-player.service -b --no-pager
journalctl -u storybox-watcher.service -b --no-pager
id admin
ls -l /dev/gpiochip*
```

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

```bash
sudo systemctl restart storybox-player.service
sudo systemctl restart storybox-watcher.service
sudo systemctl stop storybox-player.service
sudo systemctl start storybox-player.service
sudo journalctl -fu storybox-watcher.service
```

## Develop and test the local API

The API is currently available on the `feature/local-device-api` branch. It provides local device registration/authentication and device operations for future mobile-app integration. It does not call the cloud backend.

### Get the development branch

```bash
git clone -b feature/local-device-api https://github.com/JoshiMitesh/storybox.git
cd storybox
```

### Set up the Python test environment

Python 3.10 or newer is recommended.

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

On first startup, the API opens a persisted ten-minute first-registration window. Register the fixed `admin` account with a password and confirmation in the console. The window is not extended by restarting the API. Successful registration permanently closes it; later registration attempts are rejected. If the window expires before registration, use a fresh disposable test data directory for another registration test.

The API console signs in after registration and stores the returned bearer token for protected API requests. See [Local Device API documentation](docs/local-device-api.md) for endpoints, request formats, runtime settings, and current integration limitations.

> **Development status:** The local API is still under integration. Keep it separate from the production player installation. Do not enable an API systemd service or point it at production data as part of these tests. Sync/download behavior is not covered by the setup instructions here; do not run sync operations as part of routine smoke tests.

## Project layout

```text
src/storybox/
  local_api.py             Local device API (development branch)
  player/
    story_player.py        Physical-button audio player
  wifi/
    connect_wifi.py        Wi-Fi connection helper

scripts/
  setup-device.sh          Orange Pi player installer
  storybox_watcher.py      Story catalog and prompt watcher

systemd/
  storybox-player.service
  storybox-watcher.service

udev/
  99-storybox-gpio.rules

tests/                      Automated tests
docs/
  local-device-api.md       Local API details and integration notes
```

## Safety and data

- Do not commit passwords, Wi-Fi credentials, bearer tokens, provisioning data, private keys, or device identity files.
- Do not commit story audio, generated prompts, or device-specific story catalogs.
- Keep API development data under a separate test directory; do not use `/home/admin` or `/opt/storybox` as test data locations.
- Do not run destructive reset operations against a real device.
- The API uses bearer-token authentication after registration. Use it only on a trusted local network during development; production transport security and the final mobile-app integration contract still need to be agreed.
