#!/usr/bin/env python3
"""Connect wlan0 to home Wi-Fi using an explicit WPA-PSK NetworkManager profile."""
import json
import subprocess
import sys
import time

INTERFACE = "wlan0"
NMCLI = "/usr/bin/nmcli"
IP = "/usr/sbin/ip"
PROFILE = "StoryBox Home"


def run(*args, timeout=15):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def error_text(result, fallback):
    return (result.stderr or result.stdout).strip() or fallback


def connect(ssid, password):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("Invalid Wi-Fi network name")
    if not isinstance(password, str) or not 8 <= len(password) <= 63:
        raise ValueError("Wi-Fi password must contain 8 to 63 characters")

    managed = run(NMCLI, "-g", "GENERAL.NM-MANAGED", "device", "show", INTERFACE)
    if managed.returncode != 0 or managed.stdout.strip().lower() != "yes":
        raise RuntimeError("wlan0 is not managed by NetworkManager")

    # Rebuild only StoryBox's dedicated profile. This removes any stale profile
    # that may be missing 802-11-wireless-security.key-mgmt from an earlier try.
    existing = run(NMCLI, "connection", "delete", PROFILE)
    if existing.returncode != 0:
        # A missing profile is normal; continue. Do not expose secrets in errors.
        pass

    added = run(
        NMCLI, "connection", "add",
        "type", "wifi",
        "ifname", INTERFACE,
        "con-name", PROFILE,
        "ssid", ssid,
        "wifi.mode", "infrastructure",
        "wifi-sec.key-mgmt", "wpa-psk",
        "wifi-sec.psk", password,
        "wifi-sec.psk-flags", "0",
        "ipv4.method", "auto",
        "ipv6.method", "auto",
        "connection.autoconnect", "yes",
        timeout=20,
    )
    if added.returncode != 0:
        raise RuntimeError(error_text(added, "Unable to create secured Wi-Fi profile"))

    # Verify security fields before activating the profile.
    security = run(NMCLI, "-g", "802-11-wireless-security.key-mgmt", "connection", "show", PROFILE)
    if security.returncode != 0 or security.stdout.strip() != "wpa-psk":
        raise RuntimeError("Could not configure WPA-PSK security for this Wi-Fi profile")

    result = run(
        NMCLI, "--wait", "35", "connection", "up", PROFILE,
        "ifname", INTERFACE, timeout=40
    )
    if result.returncode != 0:
        raise RuntimeError(error_text(result, "Unable to connect; check the Wi-Fi password and router security mode"))

    ip_address = None
    for _ in range(20):
        time.sleep(1)
        addr = run(IP, "-4", "-o", "addr", "show", "dev", INTERFACE)
        for line in addr.stdout.splitlines():
            parts = line.split()
            if "inet" in parts:
                candidate = parts[parts.index("inet") + 1]
                if not candidate.startswith("127."):
                    ip_address = candidate
                    break
        if ip_address:
            break

    if not ip_address:
        raise RuntimeError("Wi-Fi connected but no IPv4 address was assigned")

    return {
        "success": True,
        "message": f"Connected and saved {ssid}",
        "ssid": ssid,
        "ip_address": ip_address,
    }


def main():
    data = json.load(sys.stdin)
    result = connect(data.get("ssid", ""), data.get("password", ""))
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"success": False, "message": str(exc)}))
        sys.exit(1)
