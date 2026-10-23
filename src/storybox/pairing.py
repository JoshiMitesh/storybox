#!/usr/bin/env python3
"""Generate a development QR code for the current StoryBox wlan0 address."""

import ipaddress
import json
import shutil
import subprocess
import sys

from storybox.device_identity import get_device_identity, identity_path


def device_info_url():
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "dev", "wlan0"],
        capture_output=True,
        text=True,
        check=True,
        timeout=5,
    )
    for line in result.stdout.splitlines():
        fields = line.split()
        if "inet" not in fields:
            continue
        address = fields[fields.index("inet") + 1].split("/", 1)[0]
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv4Address) and not ip.is_loopback and not ip.is_link_local:
            return f"http://{ip}:8088/"
    raise RuntimeError("wlan0 has no usable IPv4 address; connect home Wi-Fi first")


def main():
    qrencode = shutil.which("qrencode")
    if not qrencode:
        raise RuntimeError("qrencode is not installed")

    url = device_info_url()
    identity = get_device_identity()
    base = identity_path().parent
    base.mkdir(parents=True, exist_ok=True)
    payload_path = base / "pairing-draft.json"
    qr_path = base / "pairing-draft.png"

    payload = {
        "type": "storybox-pairing-draft",
        "schema_version": 1,
        "device_id": identity["device_id"],
        "device_name": identity.get("name") or "StoryBox",
        "status": "not_registered",
        "pairing_mode": "local-development",
        "device_info_url": url,
        "backend_pairing_url": None,
    }

    payload_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    subprocess.run([qrencode, "-o", str(qr_path), "-t", "PNG", url], check=True)

    print(f"QR image: {qr_path}")
    print(f"Device ID: {identity['device_id']}")
    print(f"Device name: {payload['device_name']}")
    print(f"QR URL: {url}")
    print("Status: development only; not registered or paired")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError, ValueError) as exc:
        print(f"Pairing QR generation failed: {exc}", file=sys.stderr)
        sys.exit(1)
