#!/usr/bin/env python3
"""Development-only local StoryBox device information page."""

import json
import shutil
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from storybox.device_identity import get_device_identity

HOST = "0.0.0.0"
PORT = 8088
WIFI_INTERFACE = "wlan0"


def command_output(*args):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return ""


def get_wifi_connected():
    """Check Wi-Fi connectivity without depending on NetworkManager."""

    try:
        with open(
            f"/sys/class/net/{WIFI_INTERFACE}/operstate",
            encoding="utf-8",
        ) as file:
            interface_state = file.read().strip()

        addresses = command_output(
            "ip", "-4", "-o", "addr", "show", "dev", WIFI_INTERFACE
        )

        has_ipv4 = any(
            "inet" in line.split()
            for line in addresses.splitlines()
        )

        return interface_state == "up" and has_ipv4

    except OSError:
        return False

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>StoryBox Device Info</title>
<style>
body {
  font-family: system-ui, sans-serif;
  max-width: 480px;
  margin: 40px auto;
  padding: 0 18px;
  line-height: 1.5;
}
h1 { margin-bottom: 4px; }
.muted { opacity: .7; }
.card {
  border: 1px solid #8886;
  border-radius: 14px;
  padding: 20px;
  margin-top: 20px;
}
.label { opacity: .7; font-size: 14px; }
.value {
  font-size: 18px;
  overflow-wrap: anywhere;
  margin-bottom: 18px;
}
.status { font-weight: 700; }
</style>
</head>
<body>
<h1>StoryBox</h1>
<div class="muted">Device information</div>
<div class="card">
  <div class="label">Device name</div>
  <div class="value" id="name">Loading...</div>

  <div class="label">Device ID</div>
  <div class="value" id="id">Loading...</div>

  <div class="label">Wi-Fi status</div>
  <div class="value status" id="wifi">Checking...</div>

  <div class="muted" id="updated">Checking device...</div>
</div>
<script>
async function refreshInfo() {
  try {
    const response = await fetch('/api/device-info', {
      cache: 'no-store'
    });
    if (!response.ok) throw new Error('Request failed');

    const data = await response.json();
    document.getElementById('name').textContent = data.device_name;
    document.getElementById('id').textContent = data.device_id;
    document.getElementById('wifi').textContent = data.wifi_status;
    document.getElementById('updated').textContent =
      'Last checked: ' + new Date().toLocaleTimeString();
  } catch (error) {
    document.getElementById('updated').textContent =
      'Unable to retrieve device information.';
  }
}
refreshInfo();
setInterval(refreshInfo, 5000);
</script>
</body>
</html>
"""


class DeviceInfoHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/device-info":
            identity = get_device_identity()
            data = {
                "device_name": identity.get("name") or "StoryBox",
                "device_id": identity["device_id"],
                "wifi_status": (
                    "Connected" if get_wifi_connected() else "Disconnected"
                ),
            }
            body = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/json; charset=utf-8"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header(
                "Content-Type", "text/html; charset=utf-8"
            )
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_error(404)

    def log_message(self, fmt, *args):
        print("[device-info] " + (fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), DeviceInfoHandler)
    print(f"StoryBox device info: http://192.168.4.1:{PORT}/")
    print("Development server only. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\\nStopping device-info server.")
    finally:
        server.server_close()
