#!/usr/bin/env python3
"""Connect wlan0 to home Wi-Fi and safely clean duplicate profiles after success."""
import json
import subprocess
import sys
import time
import uuid

INTERFACE = "wlan0"
NMCLI = "/usr/bin/nmcli"
IP = "/usr/sbin/ip"
PROFILE = "StoryBox Home"


def run(*args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def error_text(result, fallback):
    return (result.stderr or result.stdout).strip() or fallback


def profile_names():
    result = run(NMCLI, "-t", "-f", "NAME,TYPE", "connection", "show")
    if result.returncode:
        return []
    names = []
    for line in result.stdout.splitlines():
        name, sep, kind = line.partition(":")
        if sep and kind in ("802-11-wireless", "wifi"):
            names.append(name.replace("\\:", ":"))
    return names


def profile_ssid(name):
    result = run(NMCLI, "-g", "802-11-wireless.ssid", "connection", "show", name)
    return result.stdout.rstrip("\n") if result.returncode == 0 else None


def delete_profile(name):
    if name:
        run(NMCLI, "connection", "delete", name)


def connect(ssid, password, dry_run=False):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("Invalid Wi-Fi network name")
    if not isinstance(password, str) or not 8 <= len(password) <= 63:
        raise ValueError("Wi-Fi password must contain 8 to 63 characters")

    managed = run(NMCLI, "-g", "GENERAL.NM-MANAGED", "device", "show", INTERFACE)
    if managed.returncode != 0 or managed.stdout.strip().lower() != "yes":
        raise RuntimeError("wlan0 is not managed by NetworkManager")

    # Preserve existing saved profiles until the new credentials are proven to work.
    candidate = "StoryBox-Candidate-" + uuid.uuid4().hex[:8]
    added = run(
        NMCLI, "connection", "add",
        "type", "wifi",
        "ifname", INTERFACE,
        "con-name", candidate,
        "ssid", ssid,
        "wifi.mode", "infrastructure",
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", password,
        "wifi-sec.psk-flags", "0",
        "ipv4.method", "auto",
        "ipv6.method", "auto",
        "connection.autoconnect", "no" if dry_run else "yes",
        timeout=20,
    )
    if added.returncode != 0:
        raise RuntimeError(error_text(added, "Unable to create secured Wi-Fi profile"))

    security = run(NMCLI, "-g", "802-11-wireless-security.key-mgmt", "connection", "show", candidate)
    if security.returncode != 0 or security.stdout.strip() != "wpa-psk":
        delete_profile(candidate)
        raise RuntimeError("Could not configure WPA-PSK security for this Wi-Fi profile")

    if dry_run:
        deleted = run(NMCLI, "connection", "delete", candidate)
        if deleted.returncode != 0:
            raise RuntimeError("Dry-run profile was created but could not be removed")
        return {
            "success": True,
            "dry_run": True,
            "message": "Wi-Fi profile creation and WPA-PSK validation passed; no connection was activated",
            "ssid": ssid,
        }

    result = run(NMCLI, "--wait", "35", "connection", "up", candidate, "ifname", INTERFACE, timeout=40)
    if result.returncode != 0:
        detail = error_text(result, "Unable to connect; check the Wi-Fi password and router security mode")
        delete_profile(candidate)
        raise RuntimeError(detail)

    ip_address = None
    for _ in range(20):
        time.sleep(1)
        addr = run(IP, "-4", "-o", "addr", "show", "dev", INTERFACE)
        for line in addr.stdout.splitlines():
            parts = line.split()
            if "inet" in parts:
                candidate_ip = parts[parts.index("inet") + 1]
                if not candidate_ip.startswith("127."):
                    ip_address = candidate_ip
                    break
        if ip_address:
            break

    if not ip_address:
        delete_profile(candidate)
        raise RuntimeError("Wi-Fi connected but no IPv4 address was assigned")

    # Keep the old profile until the new profile has its final name.
    candidate_result = run(NMCLI, "-g", "UUID", "connection", "show", candidate)
    candidate_uuid = candidate_result.stdout.strip().splitlines()[0] if candidate_result.returncode == 0 and candidate_result.stdout.strip() else None
    if not candidate_uuid:
        raise RuntimeError("Connected successfully, but could not identify the new Wi-Fi profile")

    old_result = run(NMCLI, "-g", "UUID", "connection", "show", PROFILE)
    old_uuid = old_result.stdout.strip().splitlines()[0] if old_result.returncode == 0 and old_result.stdout.strip() else None
    backup = "StoryBox-Backup-" + uuid.uuid4().hex[:8]

    if old_uuid:
        backed_up = run(NMCLI, "connection", "modify", "uuid", old_uuid, "connection.id", backup)
        if backed_up.returncode != 0:
            raise RuntimeError("New Wi-Fi connected, but the existing profile could not be backed up; both profiles were kept")

    renamed = run(NMCLI, "connection", "modify", "uuid", candidate_uuid, "connection.id", PROFILE)
    if renamed.returncode != 0:
        if old_uuid:
            run(NMCLI, "connection", "modify", "uuid", old_uuid, "connection.id", PROFILE)
        raise RuntimeError("New Wi-Fi connected, but profile naming failed; the previous profile was restored")

    # Remove the old profile only after the new profile has its final name.
    if old_uuid:
        run(NMCLI, "connection", "delete", "uuid", old_uuid)

    for name in profile_names():
        if name == PROFILE:
            continue
        if profile_ssid(name) == ssid:
            delete_profile(name)

    return {
        "success": True,
        "message": f"Connected and saved {ssid}",
        "ssid": ssid,
        "ip_address": ip_address,
    }


def main():
    data = json.load(sys.stdin)
    result = connect(data.get("ssid", ""), data.get("password", ""), data.get("dry_run", False))
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "message": str(exc)}))
        sys.exit(1)
