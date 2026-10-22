# StoryBox Device Software

Device-side software for the StoryBox offline audiobook device. This repository
contains the local audio player and Wi-Fi provisioning components for an
Orange Pi PC Plus running Armbian.

## Features

- Offline playback of locally stored stories
- GPIO-based playback and menu controls
- Wi-Fi provisioning through a captive portal
- Saved Wi-Fi network configuration and reconnection
- Automatic management of the device's Wi-Fi hotspot

## Repository layout

```text
config/
  examples/          Example configuration templates
  network/           Network configuration template
scripts/
  install.sh         Migration helper for an already-configured device
  provision-device.sh Fresh-device provisioning (interactive, root required)
  verify.sh          Repository and Python syntax checks
src/storybox/
  player/            Local story player
  wifi/              Wi-Fi manager, captive portal, connection helper
systemd/              Systemd service templates
```

## Target hardware

The current development target is an Orange Pi PC Plus running Armbian.

The existing development device uses:
- `wlan0` for the StoryBox hotspot
- `wlan1` for connecting to a saved Wi-Fi network
- `/etc/storybox/wpa_supplicant.conf` for saved Wi-Fi configuration
- `/etc/storybox/hostapd.conf` for hotspot configuration
- `/etc/storybox/dnsmasq.conf` for hotspot DHCP and DNS configuration

Network interface names and system configuration may differ on other devices.
Verify the target hardware and network setup before installation.

## Software requirements

The current device uses:
- Python 3
- `mpv` for audio playback
- `gpiomon` from libgpiod for GPIO button events
- `wpa_supplicant` for station-mode Wi-Fi
- `hostapd` for the Wi-Fi hotspot
- `dnsmasq` for hotspot DHCP and DNS
- systemd for service management

Install the required packages using the package manager appropriate for the
target operating system. Package availability and GPIO command compatibility
must be checked on the target image.

## Verify the repository

From the repository directory:

```bash
bash -n scripts/install.sh
bash -n scripts/verify.sh
./scripts/verify.sh
```

The verification script checks required files, Python syntax, obsolete
development paths, and the presence of common private runtime files. Passing
these checks does not prove that all hardware, Wi-Fi, audio, or GPIO behavior
works on a clean device.

## One-command fresh-device provisioning

On a supported, freshly installed Armbian/Debian/Ubuntu ARM device with both
Wi-Fi interfaces (`wlan0` for the hotspot, `wlan1` for station Wi-Fi), clone
the repository and run from a local console. The installer asks you to choose a
new Linux username and password, then asks for a separate hotspot password.
It refuses to overwrite an existing user and requires the two passwords to differ:

```bash
git clone https://github.com/JoshiMitesh/storybox.git
cd storybox
sudo bash scripts/provision-device.sh
```

The script creates that dedicated Linux account, uses its home directory for
the story catalog/audio/prompts, configures the player service to run as that
account, installs packages and protected configuration files, enables services,
and checks service state. Choose a strong account password (at least 12
characters) and a different hotspot password. Do not run it over SSH: network
services are changed.

**Important:** this is a first implementation of the fresh-device bootstrap,
not yet a production-certified installer. It has not been validated against a
clean Orange Pi image in this repository's test environment. Test it on a
spare device or recoverable SD card first. It requires both `wlan0` and `wlan1` to exist. It configures `systemd-networkd` for
`wlan1` and disables NetworkManager if active, so review this behavior for
your specific Armbian image. It does not create story audio, `welcome.wav`,
or a populated story catalog.

## Installation and migration

**Important:** `scripts/install.sh` remains a migration helper for an
already-configured development device. It expects existing saved Wi-Fi
configuration and, if the new configuration files are absent, copies the
device's existing hotspot and dnsmasq configuration.

Review the script before running it. It backs up existing application and
systemd unit files, installs the repository under `/opt/storybox`, prepares
configuration files under `/etc/storybox`, and reloads systemd's unit
definitions. It does not restart services.

Do not assume this script is a complete clean-device provisioning procedure.
A clean-device installation still requires a verified setup process for
packages, network configuration, permissions, hotspot services, and service
startup.

After any installation, inspect the service definitions and logs before
restarting services. Preserve existing Wi-Fi credentials and maintain a
recovery path to the device.

## Local story data and credentials

Story audio, the story catalog, voice prompts, and saved Wi-Fi credentials are
device-specific runtime data. They must not be committed to this repository.

Do not commit:
- Wi-Fi passwords or populated supplicant configuration files
- Private keys, tokens, or environment files
- Personal story audio or voice recordings
- Local story catalogs, logs, backups, or runtime databases

Use the example configuration files as templates only. Protect populated
configuration files with appropriate ownership and permissions.

## Current scope

This repository covers device-side software only.

Story Manager is excluded. Mobile application integration, backend APIs,
device registration, cloud synchronization, and other API-dependent features
are not implemented here. Add those features only after the relevant API
contracts and responsibilities have been agreed.

## Development status

The repository has passed its current file-presence, Python syntax, legacy-path,
and basic private-file checks. Hardware integration, clean-device provisioning,
and production readiness require separate testing.
