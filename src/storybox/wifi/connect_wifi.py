#!/usr/bin/env python3
"""Connect wlan0 to home Wi-Fi through an explicit NetworkManager profile."""
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


def connect(ssid, password):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("Invalid Wi-Fi network name")
    if not isinstance(password, str) or not 8 <= len(password) <= 63:
        raise ValueError("Wi-Fi password must be 8-63 characters")

    managed = run(NMCLI, "-g", "GENERAL.NM-MANAGED", "device", "show", INTERFACE)
    if managed.returncode != 0 or managed.stdout.strip().lower() != "yes":
        raise RuntimeError("wlan0 is not managed by NetworkManager")

    # Create an explicit WPA-PSK profile. This avoids NetworkManager's
    # "802-11-wireless-security key mgmt property is missing" error when
    # an incomplete profile was left by an earlier setup attempt.
    existing = run(NMCLI, "-g", "NAME", "connection", "show")
    profiles = {line.strip() for line in existing.stdout.splitlines()}
    if PROFILE not in profiles:
        added = run(
            NMCLI, "connection", "add", "type", "wifi",
            "ifname", INTERFACE, "con-name", PROFILE,
            "ssid", ssid,
            "wifi-sec.key-mgmt", "wpa-psk",
            "wifi-sec.psk", password,
            "ipv4.method", "auto",
            "connection.autoconnect", "yes",
            timeout=20,
        )
        if added.returncode != 0:
            raise RuntimeError((added.stderr or added.stdout).strip() or "Unable to create Wi-Fi profile")
    else:
        modified = run(
            NMCLI, "connection", "modify", PROFILE,
            "connection.type", "802-11-wireless",
            "802-11-wireless.ssid", ssid,
            "802-11-wireless-security.key-mgmt", "wpa-psk",
            "802-11-wireless-security.psk", password,
            "ipv4.method", "auto",
            "connection.autoconnect", "yes",
            timeout=20,
        )
        if modified.returncode != 0:
            raise RuntimeError((modified.stderr or modified.stdout).strip() or "Unable to configure Wi-Fi security")

    result = run(
        NMCLI, "--wait", "35", "connection", "up", PROFILE,
        "ifname", INTERFACE, timeout=40
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or "Unable to connect to Wi-Fi")

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
