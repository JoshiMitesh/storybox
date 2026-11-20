#!/usr/bin/env python3
"""Local HTTP API for StoryBox.

The API follows the proposed operations in the backend team's integration
handover. It deliberately keeps API-managed downloads separate from the
legacy /home/admin/stories catalog until the player migration is agreed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from storybox.device_identity import get_device_identity, identity_path

HOME = Path(os.environ.get("STORYBOX_HOME", "/home/admin"))
DATA_DIR = HOME / ".local" / "share" / "storybox"
SETUP_FILE = DATA_DIR / "setup.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
WIFI_FILE = DATA_DIR / "wifi-networks.json"
SYNC_FILE = DATA_DIR / "sync-state.json"
LIBRARY_DIR = Path(os.environ.get("STORYBOX_LIBRARY_DIR", str(HOME / "storybox-library")))
WIFI_INTERFACE = os.environ.get("STORYBOX_WIFI_INTERFACE", "wlan0")
MPV_SOCKET = Path(os.environ.get("STORYBOX_MPV_SOCKET", "/tmp/lunii-player.sock"))
HOST = os.environ.get("STORYBOX_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("STORYBOX_API_PORT", "8089"))
API_TOKEN = os.environ.get("STORYBOX_API_TOKEN", "")
FIRMWARE_VERSION = os.environ.get("STORYBOX_FIRMWARE_VERSION", "0.1.0")
MAX_BODY_BYTES = 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
STATE_LOCK = threading.RLock()
SYNC_THREAD: threading.Thread | None = None
SYNC_PROGRESS = {"sync_status": "idle", "stories": []}


class APIError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        raise APIError("state_unavailable", f"Cannot read {path.name}: {exc}", 500)


def atomic_json(path: Path, value, mode: int = 0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def run_command(*args: str, timeout: int = 10):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise APIError("system_command_failed", str(exc), 503) from exc


def device_info():
    identity = get_device_identity()
    setup = read_json(SETUP_FILE, {})
    return {
        "device_id": identity["device_id"],
        "device_name": setup.get("name") or identity.get("name") or "StoryBox",
        "firmware_version": FIRMWARE_VERSION,
    }


def scan_wifi():
    result = run_command("/usr/sbin/iw", "dev", WIFI_INTERFACE, "scan", timeout=25)
    if result.returncode:
        raise APIError("wifi_scan_failed", result.stderr.strip() or "Wi-Fi scan failed", 503)

    found = {}
    blocks = re.split(r"(?m)^BSS\s+", result.stdout)
    for block in blocks[1:]:
        ssid_match = re.search(r"(?m)^\s*SSID:\s*(.*)$", block)
        if not ssid_match:
            continue
        ssid = ssid_match.group(1).strip()
        if not ssid:
            continue
        signal_match = re.search(r"(?m)^\s*signal:\s*(-?\d+(?:\.\d+)?)", block)
        signal = float(signal_match.group(1)) if signal_match else None
        secured = bool(re.search(r"(?m)^\s*(?:RSN|WPA):", block))
        network = {"ssid": ssid, "signal": signal, "secured": secured}
        previous = found.get(ssid)
        if previous is None or (signal if signal is not None else -999) > (
            previous["signal"] if previous["signal"] is not None else -999
        ):
            found[ssid] = network

    return {"networks": sorted(found.values(), key=lambda item: item["ssid"].lower())}

def connect_wifi(payload):
    ssid = payload.get("ssid")
    password = payload.get("password")
    dry_run = payload.get("dry_run", False)
    if not isinstance(ssid, str) or not ssid.strip():
        raise APIError("invalid_request", "ssid is required")
    if not isinstance(password, str):
        raise APIError("invalid_request", "password must be a string")
    if not isinstance(dry_run, bool):
        raise APIError("invalid_request", "dry_run must be a boolean")
    script = Path(__file__).resolve().parent / "wifi" / "connect_wifi.py"
    try:
        result = subprocess.run(
            ["/usr/bin/python3", str(script)],
            input=json.dumps({"ssid": ssid, "password": password, "dry_run": dry_run}),
            capture_output=True,
            text=True,
            timeout=50,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise APIError("wifi_connect_failed", str(exc), 503) from exc
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError:
        response = {"success": False, "message": result.stderr.strip() or "Wi-Fi connection failed"}
    if result.returncode or not response.get("success"):
        raise APIError("wifi_connect_failed", response.get("message", "Wi-Fi connection failed"), 422)
    return {"connected": not dry_run, **response}


def validate_wifi_networks(networks):
    if not isinstance(networks, list):
        raise APIError("invalid_request", "networks must be an array")
    clean = []
    for index, network in enumerate(networks):
        if not isinstance(network, dict):
            raise APIError("invalid_request", f"networks[{index}] must be an object")
        ssid, password = network.get("ssid"), network.get("password")
        if not isinstance(ssid, str) or not ssid.strip() or len(ssid.encode("utf-8")) > 32:
            raise APIError("invalid_request", f"networks[{index}].ssid is invalid")
        if not isinstance(password, str) or not 8 <= len(password) <= 63:
            raise APIError("invalid_request", f"networks[{index}].password must be 8 to 63 characters")
        clean.append({"ssid": ssid, "password": password})
    return clean


def apply_setup(payload):
    if not isinstance(payload, dict):
        raise APIError("invalid_request", "setup body must be a JSON object")
    setup = {
        key: payload[key]
        for key in ("name", "avatar_id", "child_name", "paired_at", "status_report_interval_seconds")
        if key in payload
    }
    if "name" in setup and (not isinstance(setup["name"], str) or not setup["name"].strip()):
        raise APIError("invalid_request", "name must be a non-empty string")
    if "settings" in payload:
        validate_settings(payload["settings"])
        atomic_json(SETTINGS_FILE, payload["settings"])
    if "wifi_networks" in payload:
        atomic_json(WIFI_FILE, validate_wifi_networks(payload["wifi_networks"]))
    if "sync_version" in payload:
        if not isinstance(payload["sync_version"], int) or payload["sync_version"] < 0:
            raise APIError("invalid_request", "sync_version must be a non-negative integer")
        state = read_json(SYNC_FILE, {"sync_version": 0, "stories": []})
        state["sync_version"] = payload["sync_version"]
        atomic_json(SYNC_FILE, state)
    atomic_json(SETUP_FILE, setup)
    return {"ok": True}


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise APIError("invalid_request", "settings must be a JSON object")
    if "max_volume" in settings and (
        not isinstance(settings["max_volume"], int) or not 0 <= settings["max_volume"] <= 100
    ):
        raise APIError("invalid_request", "max_volume must be an integer from 0 to 100")
    if "continuous_playback" in settings and not isinstance(settings["continuous_playback"], bool):
        raise APIError("invalid_request", "continuous_playback must be boolean")
    if "audio_prompts" in settings and not isinstance(settings["audio_prompts"], bool):
        raise APIError("invalid_request", "audio_prompts must be boolean")
    if "language" in settings and settings["language"] not in ("en", "ar", "fr"):
        raise APIError("invalid_request", "language must be en, ar or fr")
    return settings


def apply_settings(payload):
    validate_settings(payload)
    with STATE_LOCK:
        current = read_json(SETTINGS_FILE, {})
        current.update(payload)
        atomic_json(SETTINGS_FILE, current)
    return {"ok": True}


def safe_relative_path(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise APIError("invalid_sync", "Each file requires a valid path")
    candidate = Path(value)
    if candidate.is_absolute() or any(part in ("..", "") for part in candidate.parts):
        raise APIError("invalid_sync", f"Unsafe file path: {value}")
    return candidate


def download_file(url: str, destination: Path, expected_size, expected_sha):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise APIError("invalid_download_url", "Story downloads must use HTTPS")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": "StoryBox/0.1"})
    fd, temp_name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=30) as response:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise APIError("download_too_large", "Audio file exceeds the 512 MiB limit", 413)
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if expected_size is not None and total != expected_size:
            raise APIError("size_mismatch", f"Expected {expected_size} bytes, received {total}")
        if expected_sha and digest.hexdigest().lower() != expected_sha.lower():
            raise APIError("checksum_mismatch", "SHA-256 checksum does not match")
        os.replace(temp_name, destination)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def normalize_story_files(story):
    files = story.get("files")
    if files is None:
        files = [{
            "path": story.get("filename"),
            "filename": story.get("filename"),
            "download_url": story.get("download_url"),
            "size_bytes": story.get("size_bytes"),
            "sha256": story.get("sha256"),
        }]
    if not isinstance(files, list) or not files:
        raise APIError("invalid_sync", f"Story {story.get('id')} has no files")
    return files


def sync_worker(payload):
    global SYNC_PROGRESS
    try:
        stories = payload.get("stories")
        version = payload.get("sync_version")
        if not isinstance(version, int) or version < 0 or not isinstance(stories, list):
            raise APIError("invalid_sync", "sync_version and stories[] are required")
        deleted_ids = payload.get("deleted_story_ids", [])
        if not isinstance(deleted_ids, list):
            raise APIError("invalid_sync", "deleted_story_ids must be an array")

        previous = read_json(SYNC_FILE, {"sync_version": 0, "stories": []})
        previous_ids = {str(item["id"]) for item in previous.get("stories", []) if "id" in item}
        current_ids = {str(item.get("id")) for item in stories if isinstance(item, dict) and "id" in item}
        remove_ids = (previous_ids - current_ids) | {str(item) for item in deleted_ids}
        for story_id in remove_ids:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", story_id):
                continue
            shutil.rmtree(LIBRARY_DIR / story_id, ignore_errors=True)

        results = []
        for story in stories:
            if not isinstance(story, dict) or not isinstance(story.get("id"), (int, str)):
                raise APIError("invalid_sync", "Every story requires an integer or string id")
            story_id = str(story["id"])
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", story_id):
                raise APIError("invalid_sync", f"Invalid story id: {story_id}")
            item = {"id": story["id"], "status": "downloading", "error": None}
            with STATE_LOCK:
                SYNC_PROGRESS["sync_status"] = "syncing"
                SYNC_PROGRESS["stories"] = results + [item]
            try:
                for file_info in normalize_story_files(story):
                    if not isinstance(file_info, dict):
                        raise APIError("invalid_sync", f"Story {story_id} has an invalid files entry")
                    relative = safe_relative_path(file_info.get("path") or file_info.get("filename"))
                    url = file_info.get("download_url")
                    if not isinstance(url, str):
                        raise APIError("invalid_sync", f"Story {story_id} file has no download_url")
                    expected_size = file_info.get("size_bytes")
                    if expected_size is not None and (not isinstance(expected_size, int) or expected_size < 0):
                        raise APIError("invalid_sync", "size_bytes must be a non-negative integer")
                    destination = LIBRARY_DIR / story_id / relative
                    sha = file_info.get("sha256")
                    if destination.is_file():
                        current_size = destination.stat().st_size
                        if expected_size is not None and current_size != expected_size:
                            destination.unlink()
                        elif sha:
                            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                            if digest.lower() != str(sha).lower():
                                destination.unlink()
                    if not destination.is_file():
                        download_file(url, destination, expected_size, sha)
                item["status"] = "installed"
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)
            results.append(item)
            with STATE_LOCK:
                SYNC_PROGRESS["stories"] = list(results)

        state = {"sync_version": version, "stories": stories, "updated_at": int(time.time())}
        atomic_json(SYNC_FILE, state)
        final_status = "failed" if any(item["status"] == "failed" for item in results) else "completed"
        with STATE_LOCK:
            SYNC_PROGRESS = {"sync_status": final_status, "sync_version": version, "stories": results}
    except Exception as exc:
        with STATE_LOCK:
            SYNC_PROGRESS = {"sync_status": "failed", "stories": [], "error": str(exc)}


def start_sync(payload):
    global SYNC_THREAD, SYNC_PROGRESS
    with STATE_LOCK:
        if SYNC_THREAD and SYNC_THREAD.is_alive():
            raise APIError("busy", "A story sync is already running", 409)
        SYNC_PROGRESS = {"sync_status": "syncing", "stories": []}
        SYNC_THREAD = threading.Thread(target=sync_worker, args=(payload,), daemon=True)
        SYNC_THREAD.start()
    return {"accepted": True}


def get_status():
    identity = get_device_identity()
    setup = read_json(SETUP_FILE, {})
    settings = read_json(SETTINGS_FILE, {})
    sync_state = read_json(SYNC_FILE, {"sync_version": 0, "stories": []})
    try:
        free = shutil.disk_usage(LIBRARY_DIR if LIBRARY_DIR.exists() else HOME)
        storage_free, storage_total = free.free, free.total
    except OSError:
        storage_free = storage_total = 0

    playback_state = "idle"
    current_story_id = None
    if MPV_SOCKET.exists():
        try:
            import socket
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.25)
                client.connect(str(MPV_SOCKET))
                client.sendall(b'{"command":["get_property","pause"]}\n')
                response = client.recv(4096).decode("utf-8", "replace")
            paused = json.loads(response).get("data")
            playback_state = "paused" if paused else "playing"
        except Exception:
            playback_state = "stopped"

    wifi_state = run_command("nmcli", "-g", "GENERAL.STATE", "device", "show", WIFI_INTERFACE)
    connected = wifi_state.returncode == 0 and wifi_state.stdout.strip().startswith("100")
    with STATE_LOCK:
        progress = dict(SYNC_PROGRESS)
    return {
        "device_id": identity["device_id"],
        "online": True,
        "wifi_connected": connected,
        "playback_state": playback_state,
        "current_story_id": current_story_id,
        "volume": settings.get("max_volume", 70),
        "sync_status": progress.get("sync_status", "idle"),
        "sync_version": sync_state.get("sync_version", 0),
        "storage_free_bytes": storage_free,
        "storage_total_bytes": storage_total,
        "battery_percent": None,
        "firmware_version": FIRMWARE_VERSION,
        "device_name": setup.get("name") or "StoryBox",
    }


def reset_parent_data():
    for path in (SETUP_FILE, SETTINGS_FILE, WIFI_FILE, SYNC_FILE):
        path.unlink(missing_ok=True)
    # Keep downloaded audio and the legacy local story library. The handover
    # does not yet define which media should be deleted on unpair.
    return {"ok": True}


class StoryBoxAPIHandler(BaseHTTPRequestHandler):
    server_version = "StoryBoxLocalAPI/0.1"

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError("invalid_request", "Invalid Content-Length")
        if length <= 0 or length > MAX_BODY_BYTES:
            raise APIError("invalid_request", "Request body must be between 1 byte and 1 MiB", 413)
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError("invalid_json", "Request body must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise APIError("invalid_request", "Request body must be a JSON object")
        return value

    def authorized(self):
        # Keep the service safe by default. LAN binding is refused unless an
        # explicit token has been configured.
        if not API_TOKEN:
            self.send_json(503, {"error": "api_not_configured", "message": "Set STORYBOX_API_TOKEN before enabling the local API"})
            return False
        supplied = self.headers.get("Authorization", "")
        if supplied != f"Bearer {API_TOKEN}":
            self.send_json(401, {"error": "unauthorized", "message": "A valid bearer token is required"})
            return False
        return True

    def dispatch(self):
        if not self.authorized():
            return
        path = urlparse(self.path).path
        method = self.command

        if method == "GET" and path == "/device/info":
            return 200, device_info()
        if method == "GET" and path == "/device/wifi/scan":
            return 200, scan_wifi()
        if method == "POST" and path == "/device/wifi/connect":
            return 200, connect_wifi(self.read_body())
        if method == "PUT" and path == "/device/wifi/networks":
            networks = validate_wifi_networks(self.read_body().get("networks"))
            atomic_json(WIFI_FILE, networks)
            return 200, {"ok": True}
        if method == "POST" and path == "/device/setup":
            return 200, apply_setup(self.read_body())
        if method == "PUT" and path == "/device/settings":
            return 200, apply_settings(self.read_body())
        if method == "POST" and path == "/device/sync":
            return 202, start_sync(self.read_body())
        if method == "GET" and path == "/device/sync/progress":
            with STATE_LOCK:
                return 200, dict(SYNC_PROGRESS)
        if method == "GET" and path == "/device/status":
            return 200, get_status()
        if method == "POST" and path == "/device/reset":
            return 200, reset_parent_data()
        raise APIError("not_found", "Local API endpoint not found", 404)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PUT(self):
        self.handle_request()

    def handle_request(self):
        try:
            response = self.dispatch()
            if response is None:
                return
            status, payload = response
            self.send_json(status, payload)
        except APIError as exc:
            self.send_json(exc.status, {"error": exc.code, "message": str(exc)})
        except Exception as exc:
            self.send_json(500, {"error": "internal_error", "message": str(exc)})

    def log_message(self, fmt, *args):
        print("[storybox-api] " + (fmt % args), flush=True)


def main():
    if HOST not in ("127.0.0.1", "::1", "localhost") and not API_TOKEN:
        raise SystemExit("Refusing LAN bind without STORYBOX_API_TOKEN")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), StoryBoxAPIHandler)
    print(f"StoryBox local API listening on {HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
