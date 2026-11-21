# StoryBox

Standalone offline audio story player for Orange Pi PC Plus.

## One-command device setup

Requirements:
- Armbian/Debian on Orange Pi PC Plus (ARMv7/armhf).
- Linux account named `admin`.
- Piper executable: `/opt/piper/piper`.
- Piper voice model: `/opt/piper/models/en_US-lessac-medium.onnx`.
- ALSA output available as `plughw:0,0`.
- GPIO buttons wired as mapped in `src/storybox/player/story_player.py`.

Piper and its voice model are external assets and are not bundled. Install an ARMv7-compatible Piper binary and the Lessac medium English model at the paths above before setup. The installer checks these prerequisites and stops if they are missing.

### Install

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/JoshiMitesh/storybox.git
cd storybox
git checkout main
sudo bash scripts/setup-device.sh
sudo reboot
```

The script automatically installs Python, MPV, gpiod, ffmpeg and ALSA utilities; checks gpiomon support; installs the player, watcher, and systemd units; creates runtime directories; adds admin to gpio/audio groups; installs the GPIO udev rule; and enables both services. It does not modify Wi-Fi configuration. Reboot is required for group membership and device permissions.

### Verify

```bash
systemctl status storybox-player.service storybox-watcher.service --no-pager
journalctl -u storybox-player.service -b --no-pager
journalctl -u storybox-watcher.service -b --no-pager
id admin
ls -l /dev/gpiochip*
```

## Automatic story management

Copy supported files into `/home/admin/stories/`:

- `.mp3`
- `.wav`
- `.m4a`
- `.ogg`
- `.flac`

The watcher waits for copying to finish, derives a clean title from the filename, generates a WAV prompt with local Piper, and synchronizes `/home/admin/story-library.json`.

| Filename | Spoken prompt |
|---|---|
| `The-Golden-Key.mp3` | The Golden Key |
| `clever_rabbit.mp3` | Clever Rabbit |
| `My__Little--Star.mp3` | My Little Star |

Extensions and filename separators are not spoken. Deleting a story removes its catalog entry and deletes its generated prompt only when no remaining story uses that prompt. `welcome.wav` is preserved.

## Services

```bash
sudo systemctl restart storybox-player.service
sudo systemctl restart storybox-watcher.service
sudo systemctl stop storybox-player.service
sudo systemctl start storybox-player.service
sudo journalctl -fu storybox-watcher.service
```

## Device paths

- Player: `/opt/storybox/src/storybox/player/story_player.py`
- Watcher: `/opt/storybox/scripts/storybox_watcher.py`
- Stories: `/home/admin/stories/`
- Prompts: `/home/admin/story-prompts/`
- Catalog: `/home/admin/story-library.json`
- Piper: `/opt/piper/piper`
- Voice model: `/opt/piper/models/en_US-lessac-medium.onnx`
- MPV IPC socket: `/tmp/lunii-player.sock`

## Wi-Fi

The Wi-Fi manager is separate. Current device configuration uses wlan0 for home Wi-Fi, wlan1 for the setup hotspot, and the local portal at `http://192.168.4.1/`. The one-command player setup deliberately does not change Wi-Fi settings or services.

## Local Device API — Development Testing

The `feature/local-device-api` branch contains a first implementation of the ten local device API operations. These APIs are intended for the mobile app to communicate with the StoryBox on the local network. The StoryBox API does not call the backend directly.

> **Development status:** The API paths and payloads are a first implementation based on the integration handover. The final backend OpenAPI contract is still pending. Do not treat this as a production deployment guide.

### 1. Clone the API branch

```bash
git clone -b feature/local-device-api https://github.com/JoshiMitesh/storybox.git
cd storybox
```

### 2. Run automated tests

```bash
python3 -m py_compile src/storybox/local_api.py src/storybox/wifi/connect_wifi.py
PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_local_api.py' -v
```

The current local API test module contains seven unit tests.

### 3. Start the API with isolated test data

Run the following in terminal 1. The separate test directories prevent normal development tests from changing the device's real StoryBox data.

```bash
mkdir -p "$HOME/.storybox-api-test"

export PYTHONPATH="$PWD/src"
export STORYBOX_HOME="$HOME/.storybox-api-test"
export STORYBOX_LIBRARY_DIR="$HOME/.storybox-api-test/library"
export STORYBOX_API_HOST=127.0.0.1
export STORYBOX_API_PORT=8089
unset STORYBOX_API_TOKEN

python3 -m storybox.local_api
```

On the first API startup, a ten-minute registration window is created and persisted under:

```text
$STORYBOX_HOME/.local/share/storybox/registration-window.json
```

The deadline is not extended by restarting the API. During that window, open `/console` on a trusted first-time setup network, create a password, confirm it, and submit. The API creates the fixed `admin` account and signs it in. The console receives the generated bearer access token automatically. Later, sign in using the fixed username `admin` and the password created during registration.

Successful registration permanently closes the first-time window. If the ten-minute window expires before registration, the device remains unregistered and requires an explicit re-provisioning procedure. Keep the device on a trusted setup network during the window because another client on that network could otherwise claim the initial account.

The example binds only to localhost. To test from another device, deliberately configure a trusted local-network bind address. Once the account is registered, protected device endpoints require the generated bearer access token.

Every protected request requires the bearer token. JSON requests also use `Content-Type: application/json`.

### 4. Test the endpoints

**Device information — GET**

```bash
curl -i -H "Authorization: Bearer $TOKEN" "$API/device/info"
```

**Wi-Fi scan — GET**

```bash
curl -i -H "Authorization: Bearer $TOKEN" "$API/device/wifi/scan"
```

Wi-Fi scanning requires a compatible wireless interface and sufficient privileges. The default interface is `wlan0`; laptop interfaces often have a different name. On Linux, the API process may need `CAP_NET_ADMIN` for the scan operation.

**Wi-Fi connection — POST (dry run only)**

```bash
curl -i -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"ssid":"Test-WiFi","password":"temporary-test-password","dry_run":true}' \
  "$API/device/wifi/connect"
```

Use `"dry_run": true` for safe testing. This checks that a temporary NetworkManager profile can be created and its WPA-PSK configuration validated, then removes that profile. It does **not** authenticate the password, connect to the network, or test DHCP. Do not test a real connection remotely unless you have physical access or a verified recovery method.

**Save parent-provided Wi-Fi networks — PUT**

```bash
curl -i -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"networks":[{"ssid":"Example-WiFi","password":"example-password"}]}' \
  "$API/device/wifi/networks"
```

Use dummy credentials in a disposable test environment. Never commit real Wi-Fi passwords.

**First-time setup — POST**

```bash
curl -i -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test StoryBox","child_name":"Test Child","avatar_id":"avatar_01"}' \
  "$API/device/setup"
```

**Device settings — PUT**

```bash
curl -i -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"language":"en","max_volume":60}' \
  "$API/device/settings"
```

**Device status — GET**

```bash
curl -i -H "Authorization: Bearer $TOKEN" "$API/device/status"
```

**Sync progress — GET**

```bash
curl -i -H "Authorization: Bearer $TOKEN" "$API/device/sync/progress"
```

**Start story sync — POST**

The endpoint accepts a full snapshot. Each story needs an `id` and either a `files[]` list or the top-level file fields `filename`, `download_url`, `size_bytes`, and `sha256`. Downloads must use HTTPS. See [docs/local-device-api.md](docs/local-device-api.md) for the complete example payload and file schema.

> **Do not run sync tests against real device data yet.** The current sync implementation still needs transaction and failure-handling hardening. Review the implementation and use a disposable test environment before invoking this endpoint.

**Device reset — POST**

```bash
curl -i -X POST -H "Authorization: Bearer $TOKEN" "$API/device/reset"
```

> **Destructive operation:** Reset clears parent setup/settings data. Invoke it only in a disposable test environment after reviewing the implementation. It is not needed for ordinary API smoke tests.

### 5. Check authentication and validation

A request without a token should return `401 Unauthorized`:

```bash
curl -i "$API/device/info"
```

An invalid volume should return `400 Bad Request`:

```bash
curl -i -X PUT \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"language":"en","max_volume":150}' \
  "$API/device/settings"
```

### API endpoint checklist

| Method | Endpoint | Safe initial test |
|---|---|---|
| GET | `/device/info` | Yes |
| GET | `/device/wifi/scan` | Yes; requires Wi-Fi permissions |
| POST | `/device/wifi/connect` | Yes, with `dry_run: true` only |
| PUT | `/device/wifi/networks` | Use dummy credentials and test data |
| POST | `/device/setup` | Yes, in isolated test data |
| PUT | `/device/settings` | Yes, in isolated test data |
| POST | `/device/sync` | Wait for sync hardening; disposable test only |
| GET | `/device/sync/progress` | Yes |
| GET | `/device/status` | Yes |
| POST | `/device/reset` | Disposable test only; destructive |

For the full implementation notes, runtime environment variables, request examples, and known integration gaps, see [docs/local-device-api.md](docs/local-device-api.md).

### Important test isolation rules

- Do not point `STORYBOX_HOME` or `STORYBOX_LIBRARY_DIR` at production paths during development tests.
- Do not modify `/opt/storybox`, `/home/admin/stories`, `/home/admin/story-library.json`, or `/home/admin/.local/share/storybox` when testing the API branch.
- Do not enable the optional API systemd service on a production device as part of a local smoke test.
- Do not commit Wi-Fi passwords, bearer tokens, pairing codes, audio files, generated prompts, device identity files, or device-specific data.

## Development checks

```bash
bash -n scripts/setup-device.sh
python3 -m py_compile scripts/storybox_watcher.py src/storybox/player/story_player.py
```

Do not commit story audio, generated prompts, catalog data, Piper model files, Wi-Fi credentials, or device-specific secrets.
