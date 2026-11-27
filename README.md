# StoryBox — Orange Pi PC Plus

Offline audio story player for the Orange Pi PC Plus. StoryBox uses physical controls, MPV/ALSA playback, an ADS1115-based volume control, local Piper speech prompts, a story watcher, and optional Wi-Fi setup and local device API services.

This branch is the consolidated device setup branch: `final_working_storybox`.

## Features

- Offline playback of locally stored stories.
- Physical buttons for Home, OK/select, Next, Previous, and Play/Pause.
- Rotary encoder story browsing.
- ADS1115 potentiometer volume control over I²C0.
- Piper text-to-speech announcements and generated story prompts.
- Automatic catalog and prompt maintenance when stories are added or removed.
- Optional NetworkManager-based home Wi-Fi and fallback setup hotspot.
- Local HTTP device API with first-time registration and bearer-token authentication.

## Hardware and OS

Supported target:

- Orange Pi PC Plus (Allwinner H3), Armbian/Debian 32-bit ARM hard-float (`armhf`).
- Linux machine architecture `armv7l`.
- Existing Linux user account `admin`.
- Audio output supported by ALSA; the current player configuration uses `plughw:0,0`.
- GPIO controls and ADS1115 wired according to the configuration in `src/storybox/player/story_player.py`.

The installer checks the machine architecture and required H3 I²C0 overlay before changing the boot configuration. It adds `i2c0` to `/boot/armbianEnv.txt` only when missing and creates a timestamped backup first.

## Fresh installation

Connect the Orange Pi to the internet for package and Piper downloads. From a terminal on the Orange Pi:

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates
git clone -b final_working_storybox https://github.com/JoshiMitesh/storybox.git
cd storybox
sudo bash scripts/install-storybox.sh
sudo reboot
```

The main installer automatically runs `scripts/install-requirements.sh`, which installs the required apt packages and creates a project-local `.venv` for development/test dependencies. It does not use global pip to modify Debian's system Python.

### What the installer does

1. Installs Python, GPIO/I²C, audio, MPV, NetworkManager, hotspot, and system utilities through apt.
2. Verifies the installed `gpiomon` supports the command-line interface expected by StoryBox.
3. Enables the H3 I²C0 overlay safely, preserving other Armbian overlays and backing up the boot file before a change.
4. Downloads the official Piper ARMv7 Linux release and the Lessac medium voice model plus its matching JSON configuration.
5. Verifies the ONNX model with SHA-256 and the matching voice JSON with the upstream MD5 metadata, then runs a local speech synthesis test.
6. Creates the `gpio` and `i2c` groups if missing and adds `admin` to `gpio`, `audio`, and `i2c`.
7. Installs the application under `/opt/storybox`, the GPIO udev rule, and all four systemd unit files.
8. Preserves an existing `/etc/storybox/local-api.env`; creates a loopback-only default only if it does not exist.
9. Enables the player, watcher, and local API for boot. It installs but deliberately does not enable the Wi-Fi manager.

The installer does **not** overwrite story audio, generated prompts, the story catalog, API authentication/state files, existing API environment settings, saved NetworkManager Wi-Fi profiles, or existing hotspot configuration files.

**A reboot is required** after the first install so the I²C overlay and supplementary group memberships take effect.

## Verify the installation

After reboot, from the repository root:

```bash
bash scripts/verify.sh
bash scripts/verify.sh --device
```

Check the four service units:

```bash
systemctl status storybox-player.service storybox-watcher.service storybox-local-api.service --no-pager
systemctl status storybox-wifi.service --no-pager
```

Check I²C, GPIO, and user groups:

```bash
ls -l /dev/i2c-*
i2cdetect -y 0
gpioinfo /dev/gpiochip0
id admin
```

Check Piper:

```bash
LD_LIBRARY_PATH=/opt/piper /opt/piper/piper --help
```

View logs:

```bash
sudo journalctl -u storybox-player.service -b --no-pager
sudo journalctl -u storybox-watcher.service -b --no-pager
sudo journalctl -u storybox-local-api.service -b --no-pager
```

## Services

| Unit | Purpose | Installer behavior |
|---|---|---|
| `storybox-player.service` | Physical controls and audio playback | Installed and enabled |
| `storybox-watcher.service` | Story catalog and Piper prompt generation | Installed and enabled |
| `storybox-local-api.service` | Local device HTTP API | Installed and enabled |
| `storybox-wifi.service` | Home Wi-Fi monitor and fallback setup hotspot | Installed, left disabled |

The Wi-Fi manager is intentionally not enabled automatically. Its separate configuration script changes NetworkManager handling for `wlan1`, installs hotspot configuration, removes legacy networking files, and enforces the current fixed setup-hotspot password. Keep local/HDMI access available and review the current wireless setup before using it.

If you intentionally want to configure the fallback hotspot, first review `scripts/install.sh` and then run:

```bash
sudo bash scripts/install.sh
sudo systemctl enable --now storybox-wifi.service
sudo systemctl status storybox-wifi.service --no-pager
sudo journalctl -fu storybox-wifi.service
```

The current hotspot template uses the fixed passphrase `12345678`. This is a development/setup credential, not suitable for an exposed production network. Do not run the Wi-Fi configuration script over a remote connection unless you have a recovery path.

## Local API

The API runs as the `admin` account on port `8089`. The installer creates `/etc/storybox/local-api.env` with a safe loopback default only if the file is absent. If an existing environment file is present, it is preserved.

For access from another device on a trusted LAN, deliberately edit the environment file and set:

```ini
STORYBOX_API_HOST=0.0.0.0
STORYBOX_API_PORT=8089
```

Then restart the API:

```bash
sudo systemctl restart storybox-local-api.service
sudo systemctl status storybox-local-api.service --no-pager
```

Open `http://<ORANGE-PI-IP>:8089/console` from a device on the same trusted network. On first startup, the API opens a one-time ten-minute registration window. Register the admin account with a password of at least ten characters. The API stores authentication state under `/home/admin/.local/share/storybox`; do not delete this directory unless you intentionally want to reset device authentication.

The API uses HTTP and bearer-token authentication. Expose it only on a trusted local network; do not forward the port to the public internet.

## Manage stories

Copy supported audio files into:

```text
/home/admin/stories/
```

Supported formats: MP3, WAV, M4A, OGG, and FLAC.

The watcher detects completed file copies, derives a readable title from the filename, generates a spoken prompt with Piper, and updates:

- Catalog: `/home/admin/story-library.json`
- Generated prompts: `/home/admin/story-prompts/`

Examples:

| Audio filename | Spoken title |
|---|---|
| `The-Golden-Key.mp3` | The Golden Key |
| `clever_rabbit.mp3` | Clever Rabbit |
| `My__Little--Star.mp3` | My Little Star |

Do not manually delete the welcome prompt or catalog while the watcher is running.

## Service management

```bash
sudo systemctl restart storybox-player.service
sudo systemctl restart storybox-watcher.service
sudo systemctl restart storybox-local-api.service
sudo systemctl stop storybox-player.service
sudo systemctl start storybox-player.service
sudo journalctl -fu storybox-player.service
```

## Development and tests

The installer creates `.venv` and installs the development dependencies from `requirements-dev.txt`. On the Orange Pi:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m pytest -q
```

For development on another machine, install Python 3, Git, and venv support, then run:

```bash
bash scripts/install-requirements.sh
source .venv/bin/activate
PYTHONPATH=src python -m pytest -q
```

The development dependencies are isolated in `.venv`; runtime GPIO and I²C modules are installed from the OS package manager.

## Piper voice assets and attribution

The installer uses the ARMv7 asset from the archived official `rhasspy/piper` release `2023.11.14-2` and the `en_US-lessac-medium` voice from `rhasspy/piper-voices`. The ONNX model is SHA-256 checked before installation. Voice files are downloaded at installation time and are not committed to this repository.

- Piper source/release: https://github.com/rhasspy/piper/releases/tag/2023.11.14-2
- Voice model: https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/lessac/medium

The voice repository identifies its model files as MIT licensed. Keep the upstream license and attribution information with any redistributed voice assets.

## Repository layout

```text
src/storybox/                 Player, local API, Wi-Fi modules
scripts/install-storybox.sh   Main Orange Pi installer
scripts/install-requirements.sh OS and Python dependency installer
scripts/setup-device.sh       Compatibility wrapper for main installer
scripts/install.sh            Optional Wi-Fi configuration installer
scripts/storybox_watcher.py   Story catalog and prompt watcher
scripts/verify.sh             Static and live-device checks
systemd/                      Four systemd unit files
udev/                         GPIO udev rule
config/                       Example configuration files
tests/                        Automated tests
docs/                         API and integration documentation
```

## Safety notes

- Never commit Wi-Fi passwords, bearer tokens, private keys, device identity files, or API authentication state.
- Never commit story audio, generated WAV prompts, or the device-specific story catalog.
- Keep `/etc/storybox/local-api.env` and `/home/admin/.local/share/storybox/` private.
- The unified installer is intended for a fresh/supported Orange Pi PC Plus installation and requires the `admin` account.
- The Wi-Fi configuration script is intentionally separate because it can affect connectivity.
