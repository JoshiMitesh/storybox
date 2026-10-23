#!/usr/bin/env python3
"""Connect wlan0 to home Wi-Fi through NetworkManager."""
import json
import os
import subprocess
import sys
import time

INTERFACE = "wlan0"
NMCLI = "/usr/bin/nmcli"
IP = "/usr/sbin/ip"


def run(*args, timeout=15):
    return subprocess.run(
        args, capture_output=True, text=True, timeout=timeout
    )


def connect(ssid, password):
    if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("Invalid Wi-Fi network name")
    if not isinstance(password, str) or not 8 <= len(password) <= 63:
        raise ValueError("Wi-Fi password must be 8-63 characters")

    # Ensure the target interface is managed by NetworkManager.
    managed = run(NMCLI, "-g", "GENERAL.NM-MANAGED", "device", "show", INTERFACE)
    if managed.returncode != 0 or managed.stdout.strip().lower() != "yes":
        raise RuntimeError("wlan0 is not managed by NetworkManager")

    result = run(
        NMCLI, "--wait", "35", "device", "wifi", "connect", ssid,
        "password", password, "ifname", INTERFACE, timeout=40
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(detail or "Unable to connect to Wi-Fi")

    # Wait for NetworkManager to finish DHCP and assign IPv4.
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

    # NetworkManager persists the connection profile automatically.
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
