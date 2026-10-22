
#!/usr/bin/env python3

import json
import subprocess
import sys
import time

INTERFACE = "wlan1"
WPA_CLI = "/usr/sbin/wpa_cli"
import os

def wpa(*args):
    result = subprocess.run(
        [WPA_CLI, "-i", INTERFACE, *args],
        capture_output=True,
        text=True,
        timeout=15
    )

    output = result.stdout.strip()

    if (
        result.returncode != 0
        or output == "FAIL"
        or output.startswith("FAIL\n")
    ):
        raise RuntimeError("Wi-Fi operation failed")

    return output


def get_status():
    status = {}

    for line in wpa("status").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            status[key] = value

    return status


def current_network_id():
    for line in wpa("list_networks").splitlines()[1:]:
        parts = line.split("\t")

        if len(parts) >= 4 and "[CURRENT]" in parts[3]:
            return parts[0]

    return None


def connect(ssid, password):
    if (
        not isinstance(ssid, str)
        or not 1 <= len(ssid.encode("utf-8")) <= 32
    ):
        raise ValueError("Invalid Wi-Fi network name")

    if (
        not isinstance(password, str)
        or not 8 <= len(password) <= 63
    ):
        raise ValueError("Wi-Fi password must be 8-63 characters")

    previous_id = current_network_id()
    network_id = wpa("add_network")

    if not network_id.isdigit():
        raise RuntimeError("Unable to create Wi-Fi connection")

    try:
        wpa("set_network", network_id, "ssid", json.dumps(ssid))
        wpa("set_network", network_id, "psk", json.dumps(password))

        wpa("enable_network", network_id)
        wpa("select_network", network_id)

        # Wait for Wi-Fi association and authentication.
        connected = False

        for _ in range(30):
            time.sleep(1)
            status = get_status()

            if (
                status.get("wpa_state") == "COMPLETED"
                and status.get("ssid") == ssid
            ):
                connected = True
                break

        if not connected:
            raise RuntimeError(
                "Connection timed out. Check Wi-Fi password."
            )

        # Wait for DHCP to assign an IPv4 address.
        ip_address = None

        for _ in range(20):
            time.sleep(1)

            result = subprocess.run(
                ["/usr/sbin/ip", "-4", "-o", "addr", "show", INTERFACE],
                capture_output=True,
                text=True,
                timeout=5
            )

            status = get_status()

            if (
                status.get("wpa_state") != "COMPLETED"
                or status.get("ssid") != ssid
            ):
                raise RuntimeError(
                    "Wi-Fi disconnected while obtaining an IP address"
                )

            for line in result.stdout.splitlines():
                parts = line.split()

                if "inet" in parts:
                    ip_address = parts[parts.index("inet") + 1]
                    break

            if ip_address:
                break

        if not ip_address:
            raise RuntimeError(
                "Connected to Wi-Fi but DHCP did not assign an IPv4 address"
            )

        # Persist the working network for future boots.
        result = wpa("save_config")
        os.chown("/etc/storybox/wpa_supplicant.conf", 0, 0)
        os.chmod("/etc/storybox/wpa_supplicant.conf", 0o600)

        if result != "OK":
            raise RuntimeError(
                "Connected, but could not save Wi-Fi credentials"
            )

        return {
            "success": True,
            "message": f"Connected and saved {ssid}",
            "ssid": ssid,
            "ip_address": ip_address
        }

    except Exception:
        # Restore the previous connection when possible.
        try:
            wpa("remove_network", network_id)

            if previous_id is not None:
                wpa("enable_network", previous_id)
                wpa("select_network", previous_id)
        except Exception:
            pass

        raise


def main():
    data = json.load(sys.stdin)

    result = connect(
        data.get("ssid", ""),
        data.get("password", "")
    )

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({
            "success": False,
            "message": str(exc)
        }))
        sys.exit(1)
