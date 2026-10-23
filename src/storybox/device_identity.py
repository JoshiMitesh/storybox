#!/usr/bin/env python3
"""Persistent local identity for a StoryBox device."""

import json
import os
import tempfile
import uuid
from pathlib import Path


def identity_path() -> Path:
    home = Path(os.environ.get("STORYBOX_HOME", str(Path.home())))
    return home / ".local" / "share" / "storybox" / "device.json"


def get_device_identity() -> dict:
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Reuse the existing identity. Never silently replace a damaged identity.
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Cannot read existing device identity at {path}"
            ) from exc

        device_id = data.get("device_id") if isinstance(data, dict) else None
        if not isinstance(device_id, str) or not device_id.startswith("sb-"):
            raise RuntimeError(
                f"Existing device identity is invalid: {path}. "
                "Preserve the file and inspect it before recovery."
            )
        return data

    data = {
        "schema_version": 1,
        "device_id": f"sb-{uuid.uuid4()}",
    }

    # Write privately, then atomically publish the completed file.
    fd, temp_name = tempfile.mkstemp(
        prefix=".device-", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise

    return data


if __name__ == "__main__":
    identity = get_device_identity()
    print(f"Device ID: {identity['device_id']}")
    print(f"Saved at:  {identity_path()}")
