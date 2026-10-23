# StoryBox

## Run Commands

### 1. Start Device Information Server
```bash
cd /home/admin/storybox-repo
PYTHONPATH=src /usr/bin/python3 -u -m storybox.device_info
```

### 2. Check Device Information API
```bash
curl -s http://127.0.0.1:8088/api/device-info
echo
```

### 3. Check Device Network
```bash
hostname
ip -4 -br addr
```

### 4. Generate Pairing QR Code
```bash
cd /home/admin/storybox-repo
PYTHONPATH=src /usr/bin/python3 -m storybox.pairing
```

---

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
  install.sh         Installation/migration helper
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

## Installation and migration

**Important:** `scripts/install.sh` is currently a migration helper for an
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
