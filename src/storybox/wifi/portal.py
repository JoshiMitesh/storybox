
#!/usr/bin/env python3

import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

PORTAL_IP = "192.168.4.1"
PORTAL_PORT = 80
WIFI_INTERFACE = "wlan0"

CONNECT_SCRIPT = "/opt/storybox/src/storybox/wifi/connect_wifi.py"


def scan_wifi():
    networks = set()
    last_error = None

    for attempt in range(3):
        try:
            result = subprocess.run(
                ["/usr/sbin/iw", "dev", WIFI_INTERFACE, "scan"],
                capture_output=True,
                text=True,
                timeout=25
            )

            if result.returncode != 0:
                last_error = result.stderr.strip() or "Scan failed"
                import time
                time.sleep(2)
                continue

            for line in result.stdout.splitlines():
                line = line.strip()

                if line.startswith("SSID:"):
                    ssid = line[5:].strip()
                    if ssid:
                        networks.add(ssid)

            return sorted(networks), None

        except subprocess.TimeoutExpired:
            last_error = "Wi-Fi scan timed out"

        except Exception as exc:
            last_error = str(exc)

    print("StoryBox Wi-Fi scan error:", last_error, flush=True)
    return [], "Wi-Fi scan temporarily unavailable. Please retry."


HTML_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>StoryBox Wi-Fi Setup</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 20px;
    background: #f4f6fb;
    font-family: Arial, sans-serif;
    color: #26334d;
}

.card {
    max-width: 420px;
    margin: 50px auto;
    padding: 30px;
    background: white;
    border-radius: 20px;
    box-shadow: 0 5px 25px rgba(0,0,0,.08);
}

h1 {
    text-align: center;
    color: #273b72;
    margin-bottom: 8px;
}

.subtitle {
    text-align: center;
    color: #777;
    margin-bottom: 28px;
}

label {
    display: block;
    margin-top: 18px;
    font-weight: bold;
    font-size: 14px;
}

select, input {
    width: 100%;
    padding: 14px;
    margin-top: 8px;
    border: 1px solid #d4d9e3;
    border-radius: 10px;
    font-size: 16px;
    background: white;
}

button {
    width: 100%;
    padding: 14px;
    margin-top: 16px;
    border: 0;
    border-radius: 10px;
    font-size: 16px;
    font-weight: bold;
    cursor: pointer;
}

.primary {
    background: #273b72;
    color: white;
}

.secondary {
    background: #edf0f8;
    color: #273b72;
}

button:disabled {
    opacity: .55;
    cursor: not-allowed;
}

#status {
    margin-top: 20px;
    text-align: center;
    font-size: 14px;
    line-height: 1.5;
    min-height: 24px;
}

.footer {
    margin-top: 25px;
    text-align: center;
    color: #999;
    font-size: 12px;
}
</style>
</head>

<body>

<div class="card">

<h1>StoryBox</h1>

<p class="subtitle">
Connect your StoryBox to Wi-Fi
</p>

<label for="networks">Available Wi-Fi Networks</label>

<select id="networks">
<option value="">Scanning networks...</option>
</select>

<label for="password">Wi-Fi Password</label>

<input
    id="password"
    type="password"
    placeholder="Enter Wi-Fi password"
    autocomplete="off"
>

<button class="secondary" onclick="scan()">
Refresh Networks
</button>

<button
    id="connectButton"
    class="primary"
    onclick="connectWifi()">
Connect to Wi-Fi
</button>

<div id="status"></div>

<div class="footer">
StoryBox Device Setup
</div>

</div>

<script>

function setStatus(message, color="#555") {
    const element = document.getElementById("status");
    element.textContent = message;
    element.style.color = color;
}

async function scan() {
    const select = document.getElementById("networks");

    select.replaceChildren();
    select.add(new Option("Scanning...", ""));

    setStatus("Searching for Wi-Fi networks...");

    try {
        const response = await fetch("/scan", {
            cache: "no-store"
        });

        const data = await response.json();

        select.replaceChildren();

        for (const ssid of data.networks) {
            select.add(new Option(ssid, ssid));
        }

        if (data.networks.length === 0) {
            select.add(new Option("No networks found", ""));
        }

        if (data.error) {
            setStatus(data.error, "red");
        } else {
            setStatus(
                data.networks.length + " Wi-Fi networks found",
                "green"
            );
        }

    } catch (error) {
        setStatus("Unable to scan Wi-Fi networks.", "red");
    }
}


async function connectWifi() {
    const ssid = document.getElementById("networks").value;
    const password = document.getElementById("password").value;
    const button = document.getElementById("connectButton");

    if (!ssid) {
        setStatus("Please select a Wi-Fi network.", "red");
        return;
    }

    if (password.length < 8) {
        setStatus("Enter a valid Wi-Fi password.", "red");
        return;
    }

    button.disabled = true;
    button.textContent = "Connecting...";

    setStatus("Connecting to " + ssid + "...");

    try {
        const response = await fetch("/connect", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                ssid: ssid,
                password: password
            })
        });

        const result = await response.json();

        if (result.success) {
            setStatus(
                "Successfully connected to " + ssid,
                "green"
            );

            document.getElementById("password").value = "";

        } else {
            setStatus(result.message, "red");
        }

    } catch (error) {
        setStatus(
            "Connection failed. Please try again.",
            "red"
        );
    } finally {
        button.disabled = false;
        button.textContent = "Connect to Wi-Fi";
    }
}

window.addEventListener("load", scan);

</script>

</body>
</html>
"""


class Portal(BaseHTTPRequestHandler):

    def send_json(self, data, status=200):
        content = json.dumps(data).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/scan":
            try:
                networks, error = scan_wifi()

                self.send_json({
                    "networks": networks,
                    "error": error
                })

            except Exception:
                self.send_json({
                    "networks": [],
                    "error": "Unable to scan networks"
                }, 500)

            return

        if path != "/":
            self.send_response(302)
            self.send_header(
                "Location",
                f"http://{PORTAL_IP}/"
            )
            self.end_headers()
            return

        content = HTML_PAGE.encode("utf-8")

        self.send_response(200)
        self.send_header(
            "Content-Type",
            "text/html; charset=utf-8"
        )
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self):
        if urlparse(self.path).path != "/connect":
            self.send_error(404)
            return

        try:
            length = int(
                self.headers.get("Content-Length", "0")
            )

            if length <= 0 or length > 4096:
                self.send_json({
                    "success": False,
                    "message": "Invalid request"
                }, 400)
                return

            data = json.loads(
                self.rfile.read(length).decode("utf-8")
            )

            result = subprocess.run(
                [
                    "/usr/bin/python3",
                    CONNECT_SCRIPT
                ],
                input=json.dumps(data),
                capture_output=True,
                text=True,
                timeout=45
            )

            response = json.loads(result.stdout)

            self.send_json(
                response,
                200 if response.get("success") else 400
            )

        except subprocess.TimeoutExpired:
            self.send_json({
                "success": False,
                "message": "Wi-Fi connection timed out"
            }, 504)

        except Exception:
            self.send_json({
                "success": False,
                "message": "Unable to process Wi-Fi connection"
            }, 500)


if __name__ == "__main__":
    server = ThreadingHTTPServer(
        (PORTAL_IP, PORTAL_PORT),
        Portal
    )

    print(
        f"StoryBox captive portal running at "
        f"http://{PORTAL_IP}",
        flush=True
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
