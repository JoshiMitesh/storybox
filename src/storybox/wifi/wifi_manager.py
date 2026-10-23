#!/usr/bin/env python3
"""Fallback StoryBox setup hotspot manager.

wlan0 is managed by NetworkManager and connects to the saved home Wi-Fi.
wlan1 is reserved for the temporary StoryBox setup AP.
"""
import signal
import subprocess
import time

WIFI_INTERFACE = "wlan0"
HOTSPOT_INTERFACE = "wlan1"
HOTSPOT_IP = "192.168.4.1/24"

HOTSPOT_CONFIG = "/etc/storybox/hostapd.conf"
DNSMASQ_CONFIG = "/etc/storybox/dnsmasq.conf"
PORTAL_SCRIPT = "/opt/storybox/src/storybox/wifi/portal.py"

CHECK_INTERVAL = 10
DISCONNECTED_CHECKS = 3

running = True
processes = {}


def log(message):
    print(f"[StoryBox Wi-Fi] {message}", flush=True)


def command(*args, timeout=10):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def wifi_connected():
    """Use NetworkManager's state, rather than a competing wpa_supplicant."""
    try:
        result = command(
            "/usr/bin/nmcli", "-g", "GENERAL.STATE",
            "device", "show", WIFI_INTERFACE
        )
        state = result.stdout.strip()
        return result.returncode == 0 and state.startswith("100")
    except (OSError, subprocess.SubprocessError):
        return False


def start_process(name, args):
    existing = processes.get(name)
    if existing and existing.poll() is None:
        return True

    log(f"Starting {name}")
    try:
        process = subprocess.Popen(args, start_new_session=True)
    except OSError as exc:
        log(f"ERROR: could not start {name}: {exc}")
        return False

    processes[name] = process
    time.sleep(1)
    if process.poll() is not None:
        log(f"ERROR: {name} exited unexpectedly (code {process.returncode})")
        processes.pop(name, None)
        return False
    return True


def stop_process(name):
    process = processes.pop(name, None)
    if process and process.poll() is None:
        log(f"Stopping {name}")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def start_hotspot():
    log("Starting StoryBox setup hotspot on wlan1")
    result = command("/usr/sbin/ip", "link", "set", HOTSPOT_INTERFACE, "up")
    if result.returncode:
        log(f"ERROR: cannot bring {HOTSPOT_INTERFACE} up: {result.stderr.strip()}")
        return False

    result = command("/usr/sbin/ip", "-4", "addr", "show", HOTSPOT_INTERFACE)
    if HOTSPOT_IP.split("/")[0] not in result.stdout:
        result = command(
            "/usr/sbin/ip", "addr", "add", HOTSPOT_IP, "dev", HOTSPOT_INTERFACE
        )
        if result.returncode and "File exists" not in result.stderr:
            log(f"ERROR: cannot assign hotspot IP: {result.stderr.strip()}")
            return False

    started = []
    try:
        for name, args in (
            ("hostapd", ["/usr/sbin/hostapd", HOTSPOT_CONFIG]),
            ("dnsmasq", ["/usr/sbin/dnsmasq", "--no-daemon",
                         f"--conf-file={DNSMASQ_CONFIG}"]),
            ("portal", ["/usr/bin/python3", "-u", PORTAL_SCRIPT]),
        ):
            if not start_process(name, args):
                raise RuntimeError(f"{name} failed to start")
            started.append(name)
        return True
    except RuntimeError as exc:
        log(f"ERROR: {exc}; stopping partial hotspot")
        for name in reversed(started):
            stop_process(name)
        return False


def stop_hotspot():
    log("Stopping StoryBox setup hotspot")
    for name in ("portal", "dnsmasq", "hostapd"):
        stop_process(name)


def shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def main():
    log("Manager started: wlan0=home Wi-Fi, wlan1=fallback setup hotspot")
    hotspot_active = False
    disconnected_count = 0

    while running:
        connected = wifi_connected()
        if connected:
            disconnected_count = 0
            if hotspot_active:
                stop_hotspot()
                hotspot_active = False
        else:
            disconnected_count += 1
            if disconnected_count >= DISCONNECTED_CHECKS and not hotspot_active:
                hotspot_active = start_hotspot()
        time.sleep(CHECK_INTERVAL)

    stop_hotspot()
    log("Manager stopped")


if __name__ == "__main__":
    main()
