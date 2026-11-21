# StoryBox Local Device API (development)

This document describes the first local-only API implementation based on the
backend team's *StoryBox Integration: Handover for the IoT Team* (3 Nov 2026).

## Scope

This branch implements the ten proposed local operations:

| Method | Path | Purpose |
|---|---|---|
| GET | /device/info | Device identity and firmware version |
| GET | /device/wifi/scan | Scan nearby Wi-Fi networks |
| POST | /device/wifi/connect | Connect wlan0 using the existing Wi-Fi helper |
| PUT | /device/wifi/networks | Store parent-saved Wi-Fi networks |
| POST | /device/setup | Store first-time setup data |
| PUT | /device/settings | Store device settings |
| POST | /device/sync | Accept a full story snapshot and start download |
| GET | /device/sync/progress | Read per-story sync progress |
| GET | /device/status | Read device, Wi-Fi, storage and playback status |
| POST | /device/reset | Clear parent setup/settings data |

The API does not call the backend. No backend URL, parent login, or backend
credential is used by this service.

## Important integration boundaries

- This is a first implementation of the proposed local paths and payloads,
  not a final agreed contract. The handover says the paths and data still need
  agreement by both teams.
- The OpenAPI file referenced by the backend team was not supplied yet.
- The service is separate from the current player and Wi-Fi manager. It does
  not change their systemd units or their runtime configuration.
- Existing manually managed stories under `/home/admin/stories` and
  `story-library.json` are not modified by sync or reset.
- API-managed audio is stored separately under
  `/home/admin/storybox-library/<story_id>/`.
- Branching story tree interpretation and playback integration are not part
  of this first API-only stage. The sync handler stores the supplied story
  metadata and downloads the listed files.
- Battery percentage is reported as null when no battery hardware interface
  is defined.
- First-time account registration is available for ten minutes after
  the first API startup. The deadline is persisted and is not extended by
  service restarts. Successful registration closes the window permanently.
- Keep the device on a trusted setup network during this initial window:
  another client on that network could otherwise claim the unregistered account.
- The account uses the fixed username `admin`; the parent chooses a password
  of at least ten characters. Successful registration returns a bearer token.

## Runtime configuration

The module is `src/storybox/local_api.py`. It uses only the Python standard
library and the existing `storybox.device_identity` module.

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| STORYBOX_HOME | /home/admin | Device data home |
| STORYBOX_LIBRARY_DIR | /home/admin/storybox-library | API-managed downloaded stories |
| STORYBOX_WIFI_INTERFACE | wlan0 | Wi-Fi interface |
| STORYBOX_MPV_SOCKET | /tmp/lunii-player.sock | Existing MPV IPC socket |
| STORYBOX_API_HOST | 127.0.0.1 | Bind address; loopback is safe for initial testing |
| STORYBOX_API_PORT | 8089 | HTTP port |
| STORYBOX_FIRMWARE_VERSION | 0.1.0 | Reported firmware version |

Run locally for development:

```bash
cd /opt/storybox
PYTHONPATH=/opt/storybox/src /usr/bin/python3 -m storybox.local_api
```

On the first API startup, the service persists a ten-minute registration
deadline in `registration-window.json`. Restarting the API does not extend
that deadline. During the window, open `/console` on a trusted setup network,
choose the admin password, and submit registration. The API closes the window
after successful registration; subsequent attempts are rejected. If the
window expires before setup, registration remains closed and requires an
explicit device re-provisioning procedure.

After registration, every protected request must include the issued bearer
token:

```http
Authorization: Bearer <access-token>
Content-Type: application/json
```

HTTP is intended for a trusted local network during this development stage;
production transport security remains an open item.

## Request examples

### First-time setup

```json
{
  "name": "StoryBox",
  "avatar_id": "avatar_01",
  "child_name": "Aarav",
  "settings": {
    "max_volume": 70,
    "continuous_playback": false,
    "audio_prompts": true,
    "language": "en"
  },
  "wifi_networks": []
}
```

### Save Wi-Fi networks

```json
{
  "networks": [
    {"ssid": "Home Wi-Fi", "password": "example-password"}
  ]
}
```

### Apply settings

Supported validation follows the handover fields: `night_mode`,
`max_volume`, `continuous_playback`, `audio_prompts`,
`default_story_id`, `night_mode_schedule`, `language`, and
`lock_schedule`. The first implementation validates the types/ranges of
max_volume, continuous_playback, audio_prompts and language; other proposed
fields are retained for compatibility pending the final schema.

### Start sync

The endpoint accepts a full snapshot, not a delta. Each story must contain
an `id` and either a `files[]` list or the top-level file fields
`filename`, `download_url`, `size_bytes`, and `sha256`.

```json
{
  "sync_version": 12,
  "stories": [
    {
      "id": 103,
      "title": "The Lion and the Mouse",
      "format": "branching",
      "version": 2,
      "filename": "lion_mouse.mp3",
      "download_url": "https://example.com/audio/lion_mouse.mp3",
      "size_bytes": 5242880,
      "sha256": null,
      "files": [
        {
          "node_id": "node_1",
          "role": "voice_audio",
          "path": "audio/lion_mouse.mp3",
          "filename": "lion_mouse.mp3",
          "download_url": "https://example.com/audio/lion_mouse.mp3",
          "size_bytes": 5242880,
          "sha256": null
        }
      ],
      "tree": {}
    }
  ],
  "deleted_story_ids": []
}
```

Downloads require HTTPS, are limited to 512 MiB per file, and are written
atomically. When SHA-256 is supplied it is verified; otherwise supplied
size_bytes is checked. Per-story result statuses are downloading, installed,
or failed.

## Error response

Errors use the handover's proposed shape:

```json
{"error": "invalid_request", "message": "A useful explanation"}
```

The API returns 400 for invalid payloads, 401 for missing/invalid bearer
tokens, 404 for unknown paths, 409 when sync is already running, 413 for
oversized request/download data, 422 for a failed Wi-Fi join, 500 for
unexpected/internal state errors, and 503 for unavailable system operations
or missing API configuration.

## Known open points for backend/app discussion

1. Final schemas from the missing `device-api.openapi.yaml`.
2. How the mobile app receives and securely stores the local API bearer token.
3. Whether the app connects by BLE or Wi-Fi/hotspot, and the required bind/transport.
4. Exact branching story tree schema and how node audio paths map to local playback.
5. Whether StoryBox or the mobile app downloads audio (this implementation follows
   the handover proposal: the box downloads directly).
6. Deletion semantics on unpair/reset, including whether downloaded media is removed.
7. How current story ID, battery status, and playback state are obtained from the
   final player implementation.
8. Exact status/sync progress response schemas and retry semantics.

## Safety notes

Do not commit real Wi-Fi passwords, bearer tokens, pairing codes, audio files,
generated prompts, device identity files, or device-specific data.
