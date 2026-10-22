
#!/usr/bin/env python3
import os
import signal
import subprocess
import time

WIFI_INTERFACE = "wlan1"
HOTSPOT_INTERFACE = "wlan0"
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


def command(*args):
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=10
    )


def wifi_connected():
    try:
        result = command(
            "/usr/sbin/wpa_cli",
            "-i", WIFI_INTERFACE,
            "status"
        )

        return (
            result.returncode == 0
            and "wpa_state=COMPLETED" in result.stdout
        )
    except Exception:
        return False


def start_process(name, args):
    existing = processes.get(name)

    if existing and existing.poll() is None:
        return

    log(f"Starting {name}")

    processes[name] = subprocess.Popen(
        args,
        start_new_session=True
    )

    time.sleep(1)

    if processes[name].poll() is not None:
        log(f"ERROR: {name} exited unexpectedly")


def stop_process(name):
    process = processes.pop(name, None)

    if not process:
        return

    if process.poll() is None:
        log(f"Stopping {name}")
        process.terminate()

        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def start_hotspot():
    log("Starting StoryBox hotspot")

    command(
        "/usr/sbin/ip",
        "link", "set", HOTSPOT_INTERFACE, "up"
    )

    result = command(
        "/usr/sbin/ip",
        "addr", "show", HOTSPOT_INTERFACE
    )

    if HOTSPOT_IP.split("/")[0] not in result.stdout:
        command(
            "/usr/sbin/ip",
            "addr", "add",
            HOTSPOT_IP,
            "dev", HOTSPOT_INTERFACE
        )

    start_process(
        "hostapd",
        ["/usr/sbin/hostapd", HOTSPOT_CONFIG]
    )

    start_process(
        "dnsmasq",
        [
            "/usr/sbin/dnsmasq",
            "--no-daemon",
            f"--conf-file={DNSMASQ_CONFIG}"
        ]
    )

    start_process(
        "portal",
        [
            "/usr/bin/python3",
            "-u",
            PORTAL_SCRIPT
        ]
    )


def stop_hotspot():
    log("Stopping StoryBox hotspot")

    stop_process("portal")
    stop_process("dnsmasq")
    stop_process("hostapd")


def shutdown(signum, frame):
    global running
    running = False


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)


def main():
    log("Manager started")

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

            if disconnected_count >= DISCONNECTED_CHECKS:
                if not hotspot_active:
                    start_hotspot()
                    hotspot_active = True

        time.sleep(CHECK_INTERVAL)

    stop_hotspot()
    log("Manager stopped")


if __name__ == "__main__":
    main()
