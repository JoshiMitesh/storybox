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

## Development checks

```bash
bash -n scripts/setup-device.sh
python3 -m py_compile scripts/storybox_watcher.py src/storybox/player/story_player.py
```

Do not commit story audio, generated prompts, catalog data, Piper model files, Wi-Fi credentials, or device-specific secrets.
