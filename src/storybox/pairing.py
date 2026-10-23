#!/usr/bin/env python3
"""Generate a development QR code for the local StoryBox info page."""

import json
import shutil
import subprocess
import sys

from storybox.device_identity import get_device_identity, identity_path

DEVICE_INFO_URL = "http://192.168.1.25:8088/"


def main():
    identity = get_device_identity()
    base = identity_path().parent
    base.mkdir(parents=True, exist_ok=True)

    payload_path = base / "pairing-draft.json"
    qr_path = base / "pairing-draft.png"

    # Keep the draft metadata separate from the URL encoded in the QR.
    payload = {
        "type": "storybox-pairing-draft",
        "schema_version": 1,
        "device_id": identity["device_id"],
        "device_name": identity.get("name") or "StoryBox",
        "status": "not_registered",
        "pairing_mode": "local-development",
        "device_info_url": DEVICE_INFO_URL,
        "backend_pairing_url": None,
    }

    payload_path.write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    qrencode = shutil.which("qrencode")
    if not qrencode:
        raise RuntimeError("qrencode is not installed")

    subprocess.run(
        [qrencode, "-o", str(qr_path), "-t", "PNG", DEVICE_INFO_URL],
        check=True,
    )

    print(f"QR image: {qr_path}")
    print(f"Device ID: {identity['device_id']}")
    print(f"Device name: {payload['device_name']}")
    print(f"QR URL: {DEVICE_INFO_URL}")
    print("Status: development only; not registered or paired")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"Pairing QR generation failed: {exc}", file=sys.stderr)
        sys.exit(1)
