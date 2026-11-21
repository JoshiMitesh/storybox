#!/usr/bin/env python3
"""Local HTTP API for StoryBox.

The API follows the proposed operations in the backend team's integration
handover. It deliberately keeps API-managed downloads separate from the
legacy /home/admin/stories catalog until the player migration is agreed.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import hmac
import secrets
import hmac
import secrets
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
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from storybox.device_identity import get_device_identity, identity_path

HOME = Path(os.environ.get("STORYBOX_HOME", "/home/admin"))
DATA_DIR = HOME / ".local" / "share" / "storybox"
SETUP_FILE = DATA_DIR / "setup.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
WIFI_FILE = DATA_DIR / "wifi-networks.json"
WIFI_CONNECT_FILE = DATA_DIR / "wifi-connect-operation.json"
SYNC_FILE = DATA_DIR / "sync-state.json"
SYNC_JOURNAL_FILE = DATA_DIR / "sync-journal.json"
LIBRARY_DIR = Path(os.environ.get("STORYBOX_LIBRARY_DIR", str(HOME / "storybox-library")))
WIFI_INTERFACE = os.environ.get("STORYBOX_WIFI_INTERFACE", "wlan0")
MPV_SOCKET = Path(os.environ.get("STORYBOX_MPV_SOCKET", "/tmp/lunii-player.sock"))
HOST = os.environ.get("STORYBOX_API_HOST", "127.0.0.1")
PORT = int(os.environ.get("STORYBOX_API_PORT", "8089"))
API_TOKEN = os.environ.get("STORYBOX_API_TOKEN", "")
AUTH_FILE = DATA_DIR / "auth.json"
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
        directory_fd = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise



AUTH_ITERATIONS = 310000
AUTH_TOKEN_TTL = 30 * 24 * 60 * 60
LOGIN_FAILURES = []
LOGIN_LOCK_UNTIL = 0


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        AUTH_ITERATIONS,
    ).hex()


def register_account(payload):
    password = payload.get("password")
    if not isinstance(password, str) or len(password) < 10:
        raise APIError("invalid_password", "Password must contain at least 10 characters")

    with STATE_LOCK:
        if AUTH_FILE.exists():
            raise APIError("already_registered", "StoryBox account is already registered", 409)

        salt = secrets.token_bytes(16)
        atomic_json(AUTH_FILE, {
            "password_salt": salt.hex(),
            "password_hash": password_hash(password, salt),
            "token_hash": "",
            "token_expires_at": 0,
        })
    return {"registered": True, "message": "StoryBox account registered successfully"}


def login_account(payload):
    global LOGIN_LOCK_UNTIL

    password = payload.get("password")
    if not isinstance(password, str) or not password:
        raise APIError("invalid_request", "Password is required")

    now = time.time()
    with STATE_LOCK:
        if now < LOGIN_LOCK_UNTIL:
            raise APIError("login_rate_limited", "Too many failed attempts. Try again later.", 429)

        account = read_json(AUTH_FILE, None)
        if not isinstance(account, dict):
            raise APIError("not_registered", "Register the StoryBox account first", 404)

        try:
            salt = bytes.fromhex(account["password_salt"])
            expected = account["password_hash"]
        except (KeyError, TypeError, ValueError):
            raise APIError("auth_state_invalid", "Stored account data is invalid", 500)

        supplied = password_hash(password, salt)
        if not hmac.compare_digest(supplied, expected):
            LOGIN_FAILURES.append(now)
            LOGIN_FAILURES[:] = [t for t in LOGIN_FAILURES if now - t < 60]
            if len(LOGIN_FAILURES) >= 5:
                LOGIN_LOCK_UNTIL = now + 60
                LOGIN_FAILURES.clear()
            raise APIError("invalid_credentials", "Incorrect password", 401)

        LOGIN_FAILURES.clear()
        LOGIN_LOCK_UNTIL = 0
        token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + AUTH_TOKEN_TTL
        account["token_hash"] = hashlib.sha256(token.encode("utf-8")).hexdigest()
        account["token_expires_at"] = expires_at
        atomic_json(AUTH_FILE, account)

    return {
        "authenticated": True,
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": AUTH_TOKEN_TTL,
        "expires_at": expires_at,
    }


def valid_login_token(token):
    account = read_json(AUTH_FILE, None)
    if not isinstance(account, dict):
        return False

    stored_hash = account.get("token_hash", "")
    expires_at = account.get("token_expires_at", 0)
    if not isinstance(stored_hash, str) or not stored_hash:
        return False
    if not isinstance(expires_at, int) or expires_at <= int(time.time()):
        return False

    supplied_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(supplied_hash, stored_hash)


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




def recover_wifi_connect_operation(force=False):
    with STATE_LOCK:
        operation = read_json(WIFI_CONNECT_FILE, None)
        if not isinstance(operation, dict) or operation.get("status") != "pending":
            return False

        try:
            created_at = int(operation["created_at"])
        except (KeyError, TypeError, ValueError):
            created_at = 0

        if not force and time.time() - created_at < 120:
            return False

        operation.update({
            "status": "failed",
            "error": "wifi_connect_interrupted",
            "message": "Wi-Fi connection was interrupted before the result could be saved",
            "completed_at": int(time.time()),
        })
        atomic_json(WIFI_CONNECT_FILE, operation)
        return True


def run_wifi_connect_operation(operation_id, payload):
    try:
        result = connect_wifi(payload)
        operation = {
            "operation_id": operation_id,
            "status": "success",
            "ssid": payload["ssid"],
            "result": result,
            "message": result.get("message", "Wi-Fi operation completed"),
            "completed_at": int(time.time()),
        }
    except Exception as exc:
        operation = {
            "operation_id": operation_id,
            "status": "failed",
            "ssid": payload["ssid"],
            "error": getattr(exc, "code", "wifi_connect_failed"),
            "message": str(exc),
            "completed_at": int(time.time()),
        }

    with STATE_LOCK:
        atomic_json(WIFI_CONNECT_FILE, operation)


def start_wifi_connect(payload):
    ssid = payload.get("ssid")
    password = payload.get("password")
    dry_run = payload.get("dry_run", False)
    operation_id = payload.get("operation_id")

    if not isinstance(ssid, str) or not ssid.strip():
        raise APIError("invalid_request", "ssid is required")
    if not isinstance(password, str):
        raise APIError("invalid_request", "password must be a string")
    if not isinstance(dry_run, bool):
        raise APIError("invalid_request", "dry_run must be a boolean")

    if operation_id is None:
        operation_id = str(uuid.uuid4())
    try:
        operation_id = str(uuid.UUID(operation_id))
    except (ValueError, TypeError, AttributeError):
        raise APIError("invalid_request", "operation_id must be a valid UUID")

    recover_wifi_connect_operation()

    with STATE_LOCK:
        previous = read_json(WIFI_CONNECT_FILE, {})
        if isinstance(previous, dict) and previous.get("status") == "pending":
            raise APIError(
                "wifi_connect_in_progress",
                "Another Wi-Fi connection operation is still running",
                409,
            )

        atomic_json(WIFI_CONNECT_FILE, {
            "operation_id": operation_id,
            "status": "pending",
            "ssid": ssid,
            "message": "Wi-Fi connection is in progress",
            "created_at": int(time.time()),
        })

    worker_payload = {
        "ssid": ssid,
        "password": password,
        "dry_run": dry_run,
    }
    thread = threading.Thread(
        target=run_wifi_connect_operation,
        args=(operation_id, worker_payload),
        daemon=True,
    )
    thread.start()

    return {
        "accepted": True,
        "operation_id": operation_id,
        "status": "pending",
        "message": "Wi-Fi connection operation started",
    }


def get_wifi_connect_status(query):
    operation_id = parse_qs(query).get("operation_id", [None])[0]
    if not operation_id:
        raise APIError("invalid_request", "operation_id is required")

    try:
        operation_id = str(uuid.UUID(operation_id))
    except (ValueError, TypeError, AttributeError):
        raise APIError("invalid_request", "operation_id must be a valid UUID")

    recover_wifi_connect_operation()
    operation = read_json(WIFI_CONNECT_FILE, None)
    if not isinstance(operation, dict) or operation.get("operation_id") != operation_id:
        raise APIError("operation_not_found", "Wi-Fi operation was not found", 404)

    return operation


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

    if "name" in setup and (
        not isinstance(setup["name"], str) or not setup["name"].strip()
    ):
        raise APIError("invalid_request", "name must be a non-empty string")

    settings = None
    networks = None
    sync_version = None

    if "settings" in payload:
        settings = validate_settings(payload["settings"])

    if "wifi_networks" in payload:
        networks = validate_wifi_networks(payload["wifi_networks"])

    if "sync_version" in payload:
        sync_version = payload["sync_version"]
        if (
            isinstance(sync_version, bool)
            or not isinstance(sync_version, int)
            or sync_version < 0
        ):
            raise APIError(
                "invalid_request",
                "sync_version must be a non-negative integer",
            )

    with STATE_LOCK:
        if sync_version is not None and SYNC_THREAD and SYNC_THREAD.is_alive():
            raise APIError(
                "busy",
                "Cannot change sync_version while a story sync is running",
                409,
            )

        if settings is not None:
            atomic_json(SETTINGS_FILE, settings)

        if networks is not None:
            atomic_json(WIFI_FILE, networks)

        if sync_version is not None:
            state = read_json(SYNC_FILE, {"sync_version": 0, "stories": []})
            state["sync_version"] = sync_version
            atomic_json(SYNC_FILE, state)

        atomic_json(SETUP_FILE, setup)

    return {"ok": True}


def validate_settings(settings):
    if not isinstance(settings, dict):
        raise APIError("invalid_request", "settings must be a JSON object")
    if "max_volume" in settings and (
        isinstance(settings["max_volume"], bool)
        or not isinstance(settings["max_volume"], int)
        or not 0 <= settings["max_volume"] <= 100
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
    if (
        candidate.is_absolute()
        or candidate == Path(".")
        or any(part in ("..", "") for part in candidate.parts)
        or candidate.as_posix() != value
    ):
        raise APIError("invalid_sync", f"Unsafe file path: {value}")

    return candidate


def validated_https_origin(url):
    if not isinstance(url, str):
        raise APIError("invalid_download_url", "Story downloads must use a valid HTTPS URL")

    parsed = urlparse(url)
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise APIError("invalid_download_url", "Story download URL has an invalid port") from exc

    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or not 1 <= port <= 65535
    ):
        raise APIError("invalid_download_url", "Story downloads must use a valid HTTPS URL")

    return parsed.hostname.lower(), port


class SameOriginHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, original_origin):
        super().__init__()
        self.original_origin = original_origin

    def redirect_request(self, request, response, code, message, headers, new_url):
        try:
            redirected_origin = validated_https_origin(new_url)
        except APIError as exc:
            raise APIError(
                "unsafe_redirect",
                "Story download redirects must remain on the same HTTPS origin",
            ) from exc

        if redirected_origin != self.original_origin:
            raise APIError(
                "unsafe_redirect",
                "Story download redirects must remain on the same HTTPS origin",
            )

        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def download_file(url: str, destination: Path, expected_size, expected_sha):
    original_origin = validated_https_origin(url)

    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    total = 0
    request = urllib.request.Request(url, headers={"User-Agent": "StoryBox/0.1"})
    fd, temp_name = tempfile.mkstemp(prefix=".download-", dir=destination.parent)
    try:
        opener = urllib.request.build_opener(SameOriginHTTPSRedirectHandler(original_origin))
        with os.fdopen(fd, "wb") as output, opener.open(request, timeout=30) as response:
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


def validate_sync_payload(payload):
    if not isinstance(payload, dict):
        raise APIError("invalid_sync", "Sync payload must be an object")

    version = payload.get("sync_version")
    stories = payload.get("stories")
    deleted_ids = payload.get("deleted_story_ids", [])

    if isinstance(version, bool) or not isinstance(version, int) or version < 0:
        raise APIError("invalid_sync", "sync_version must be a non-negative integer")
    if not isinstance(stories, list):
        raise APIError("invalid_sync", "stories must be an array")
    if not isinstance(deleted_ids, list):
        raise APIError("invalid_sync", "deleted_story_ids must be an array")

    story_ids = set()
    for story in stories:
        if not isinstance(story, dict):
            raise APIError("invalid_sync", "Every story must be an object")

        raw_id = story.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, str)):
            raise APIError("invalid_sync", "Every story requires an integer or string id")

        story_id = str(raw_id)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", story_id):
            raise APIError("invalid_sync", f"Invalid story id: {story_id}")
        if story_id in story_ids:
            raise APIError("invalid_sync", f"Duplicate story id: {story_id}")
        story_ids.add(story_id)

        paths = []
        for file_info in normalize_story_files(story):
            if not isinstance(file_info, dict):
                raise APIError("invalid_sync", f"Story {story_id} has an invalid files entry")

            relative = safe_relative_path(file_info.get("path") or file_info.get("filename"))
            paths.append(relative)

            url = file_info.get("download_url")
            if not isinstance(url, str):
                raise APIError("invalid_sync", f"Story {story_id} file has no download_url")
            validated_https_origin(url)

            size = file_info.get("size_bytes")
            if size is not None and (
                isinstance(size, bool) or not isinstance(size, int) or size < 0
            ):
                raise APIError("invalid_sync", "size_bytes must be a non-negative integer")

            sha = file_info.get("sha256")
            if sha is not None and (
                not isinstance(sha, str) or not re.fullmatch(r"[A-Fa-f0-9]{64}", sha)
            ):
                raise APIError("invalid_sync", "sha256 must contain exactly 64 hexadecimal characters")

        for index, first in enumerate(paths):
            for second in paths[index + 1:]:
                if first == second or first in second.parents or second in first.parents:
                    raise APIError("invalid_sync", f"Conflicting file paths in story {story_id}")

    deleted_set = set()
    for item in deleted_ids:
        if isinstance(item, bool) or not isinstance(item, (int, str)):
            raise APIError("invalid_sync", "Every deleted story id must be an integer or string")
        story_id = str(item)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", story_id):
            raise APIError("invalid_sync", f"Invalid deleted story id: {story_id}")
        if story_id in deleted_set:
            raise APIError("invalid_sync", f"Duplicate deleted story id: {story_id}")
        if story_id in story_ids:
            raise APIError("invalid_sync", f"Story {story_id} cannot be both present and deleted")
        deleted_set.add(story_id)

    return version, stories



def sync_transaction_path(name, kind, transaction_id):
    expected_name = f".{LIBRARY_DIR.name}.{kind}-{transaction_id}"
    if not isinstance(name, str) or name != expected_name:
        raise APIError(
            "sync_recovery_failed",
            "Invalid transaction path in sync journal",
            500,
        )

    path = LIBRARY_DIR.parent / name
    if path.is_symlink():
        raise APIError(
            "sync_recovery_failed",
            "Transaction path must not be a symlink",
            500,
        )
    return path


def remove_transaction_path(path):
    if path.is_symlink():
        raise APIError(
            "sync_recovery_failed",
            "Refusing to remove a transaction symlink",
            500,
        )
    if not path.exists():
        return
    if not path.is_dir():
        raise APIError(
            "sync_recovery_failed",
            "Transaction path must be a directory",
            500,
        )
    shutil.rmtree(path)


def recover_sync_transaction():
    if SYNC_JOURNAL_FILE.is_symlink():
        raise APIError(
            "sync_recovery_failed",
            "Sync journal must not be a symlink",
            500,
        )
    if not SYNC_JOURNAL_FILE.exists():
        return False
    if not SYNC_JOURNAL_FILE.is_file():
        raise APIError(
            "sync_recovery_failed",
            "Sync journal path must be a regular file",
            500,
        )

    journal = read_json(SYNC_JOURNAL_FILE, None)
    if not isinstance(journal, dict):
        raise APIError("sync_recovery_failed", "Sync journal is invalid", 500)

    transaction_id = journal.get("transaction_id")
    try:
        uuid.UUID(transaction_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise APIError("sync_recovery_failed", "Sync journal transaction ID is invalid", 500) from exc

    phase = journal.get("phase")
    if phase not in ("prepared", "library_activated", "state_committed"):
        raise APIError("sync_recovery_failed", "Sync journal phase is invalid", 500)

    had_library = journal.get("had_library")
    if not isinstance(had_library, bool):
        raise APIError("sync_recovery_failed", "Sync journal library flag is invalid", 500)

    stage_dir = sync_transaction_path(journal.get("stage_name"), "stage", transaction_id)
    backup_name = journal.get("backup_name")
    backup_dir = (
        sync_transaction_path(backup_name, "backup", transaction_id)
        if backup_name is not None else None
    )

    if had_library != (backup_dir is not None):
        raise APIError("sync_recovery_failed", "Sync journal backup information is inconsistent", 500)

    for transaction_path in (stage_dir, backup_dir):
        if transaction_path is None:
            continue
        if transaction_path.is_symlink():
            raise APIError(
                "sync_recovery_failed",
                "Transaction path must not be a symlink",
                500,
            )
        if transaction_path.exists() and not transaction_path.is_dir():
            raise APIError(
                "sync_recovery_failed",
                "Transaction path must be a directory",
                500,
            )

    if LIBRARY_DIR.is_symlink():
        raise APIError(
            "sync_recovery_failed",
            "Story library must not be a symlink",
            500,
        )
    if LIBRARY_DIR.exists() and not LIBRARY_DIR.is_dir():
        raise APIError(
            "sync_recovery_failed",
            "Story library path must be a directory",
            500,
        )

    state = read_json(SYNC_FILE, {})
    committed = (
        isinstance(state, dict)
        and state.get("transaction_id") == transaction_id
    )

    if committed:
        # The new library and sync state were committed. Only cleanup remains.
        remove_transaction_path(stage_dir)
        if backup_dir is not None:
            remove_transaction_path(backup_dir)
    else:
        # The state does not identify this transaction: restore the old snapshot.
        if had_library:
            if backup_dir.exists():
                if LIBRARY_DIR.exists():
                    remove_transaction_path(LIBRARY_DIR)
                os.replace(backup_dir, LIBRARY_DIR)
            elif phase != "prepared" or not LIBRARY_DIR.exists():
                raise APIError(
                    "sync_recovery_failed",
                    "Old library backup is missing; refusing unsafe recovery",
                    500,
                )
        elif LIBRARY_DIR.exists():
            # There was no old library; this directory can only be the uncommitted snapshot.
            remove_transaction_path(LIBRARY_DIR)

        remove_transaction_path(stage_dir)

    SYNC_JOURNAL_FILE.unlink()
    directory_fd = os.open(
        SYNC_JOURNAL_FILE.parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

    return True


def sync_worker(payload):
    global SYNC_PROGRESS

    stage_dir = None
    transaction_id = str(uuid.uuid4())
    journal_created = False

    try:
        version, stories = validate_sync_payload(payload)

        parent = LIBRARY_DIR.parent
        parent.mkdir(parents=True, exist_ok=True)
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if LIBRARY_DIR.is_symlink():
            raise APIError("invalid_library", "Story library must not be a symlink", 500)
        if LIBRARY_DIR.exists() and not LIBRARY_DIR.is_dir():
            raise APIError("invalid_library", "Story library path is not a directory", 500)

        stage_name = f".{LIBRARY_DIR.name}.stage-{transaction_id}"
        backup_name = f".{LIBRARY_DIR.name}.backup-{transaction_id}"
        stage_dir = parent / stage_name
        backup_dir = parent / backup_name

        if stage_dir.exists() or stage_dir.is_symlink():
            raise APIError("sync_failed", "Transaction staging path already exists", 500)
        if backup_dir.exists() or backup_dir.is_symlink():
            raise APIError("sync_failed", "Transaction backup path already exists", 500)

        stage_dir.mkdir(mode=0o700)

        for story in stories:
            story_id = str(story["id"])
            item = {"id": story["id"], "status": "downloading", "error": None}

            with STATE_LOCK:
                SYNC_PROGRESS = {
                    "sync_status": "syncing",
                    "sync_version": version,
                    "stories": [
                        dict(result)
                        for result in SYNC_PROGRESS.get("stories", [])
                    ] + [dict(item)],
                }

            try:
                story_dir = stage_dir / story_id
                for file_info in normalize_story_files(story):
                    relative = safe_relative_path(
                        file_info.get("path") or file_info.get("filename")
                    )
                    destination = story_dir / relative
                    download_file(
                        file_info["download_url"],
                        destination,
                        file_info.get("size_bytes"),
                        file_info.get("sha256"),
                    )
                item["status"] = "downloaded"
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = str(exc)
                raise
            finally:
                with STATE_LOCK:
                    current = SYNC_PROGRESS.get("stories", [])
                    for index, result in enumerate(current):
                        if result.get("id") == item["id"]:
                            current[index] = dict(item)
                            break

        had_library = LIBRARY_DIR.exists()
        journal = {
            "transaction_id": transaction_id,
            "phase": "prepared",
            "had_library": had_library,
            "stage_name": stage_name,
            "backup_name": backup_name if had_library else None,
        }

        atomic_json(SYNC_JOURNAL_FILE, journal)
        journal_created = True

        if had_library:
            os.replace(LIBRARY_DIR, backup_dir)
            directory_fd = os.open(
                parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

        os.replace(stage_dir, LIBRARY_DIR)
        stage_dir = None

        directory_fd = os.open(
            parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

        journal["phase"] = "library_activated"
        atomic_json(SYNC_JOURNAL_FILE, journal)

        state = {
            "sync_version": version,
            "stories": stories,
            "updated_at": int(time.time()),
            "transaction_id": transaction_id,
        }
        atomic_json(SYNC_FILE, state)

        # The transaction ID in sync-state.json is the commit record.
        # Cleanup can be retried safely during the next startup.
        try:
            journal["phase"] = "state_committed"
            atomic_json(SYNC_JOURNAL_FILE, journal)
            recover_sync_transaction()
            journal_created = False
        except Exception as cleanup_error:
            print(
                f"StoryBox sync committed; cleanup deferred: {cleanup_error}",
                flush=True,
            )

        with STATE_LOCK:
            SYNC_PROGRESS = {
                "sync_status": "completed",
                "sync_version": version,
                "stories": [
                    dict(result)
                    for result in SYNC_PROGRESS.get("stories", [])
                ],
            }

    except Exception as exc:
        if SYNC_JOURNAL_FILE.is_symlink() or SYNC_JOURNAL_FILE.exists():
            try:
                recover_sync_transaction()
                journal_created = False
            except Exception as recovery_error:
                print(
                    f"StoryBox sync recovery failed: {recovery_error}",
                    flush=True,
                )

        state_read_error = None
        try:
            state = read_json(SYNC_FILE, {})
        except Exception as state_error:
            state = {}
            state_read_error = str(state_error)

        committed = (
            isinstance(state, dict)
            and state.get("transaction_id") == transaction_id
        )

        error_message = None if committed else str(exc)
        if state_read_error:
            error_message = (
                f"{error_message}; sync state could not be read: {state_read_error}"
            )

        with STATE_LOCK:
            SYNC_PROGRESS = {
                "sync_status": "completed" if committed else "failed",
                "sync_version": state.get("sync_version") if committed else None,
                "stories": [
                    dict(result)
                    for result in SYNC_PROGRESS.get("stories", [])
                ],
                "error": error_message,
            }

    finally:
        if stage_dir is not None and stage_dir.exists():
            try:
                shutil.rmtree(stage_dir)
            except OSError as cleanup_error:
                print(
                    f"StoryBox sync staging cleanup deferred: {cleanup_error}",
                    flush=True,
                )


def start_sync(payload):
    global SYNC_THREAD, SYNC_PROGRESS

    validate_sync_payload(payload)

    with STATE_LOCK:
        if SYNC_THREAD and SYNC_THREAD.is_alive():
            raise APIError("busy", "A story sync is already running", 409)

        if SYNC_JOURNAL_FILE.is_symlink() or SYNC_JOURNAL_FILE.exists():
            raise APIError(
                "sync_recovery_required",
                "A pending sync transaction must be recovered before starting another sync",
                409,
            )

        SYNC_PROGRESS = {"sync_status": "syncing", "stories": []}
        SYNC_THREAD = threading.Thread(
            target=sync_worker,
            args=(payload,),
            daemon=True,
        )
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
    with STATE_LOCK:
        if SYNC_THREAD and SYNC_THREAD.is_alive():
            raise APIError(
                "busy",
                "Cannot reset device data while a story sync is running",
                409,
            )

        if SYNC_JOURNAL_FILE.is_symlink() or SYNC_JOURNAL_FILE.exists():
            raise APIError(
                "sync_recovery_required",
                "A pending sync transaction must be recovered before reset",
                409,
            )

        for path in (SETUP_FILE, SETTINGS_FILE, WIFI_FILE, SYNC_FILE):
            path.unlink(missing_ok=True)

        # Keep downloaded audio and the legacy local story library.
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
        supplied = self.headers.get("Authorization", "")
        if AUTH_FILE.exists():
            if supplied.startswith("Bearer ") and valid_login_token(supplied[7:]):
                return True
            self.send_json(401, {
                "error": "unauthorized",
                "message": "Log in to obtain a valid bearer token",
            })
            return False

        if not API_TOKEN:
            self.send_json(503, {
                "error": "api_not_configured",
                "message": "Initial registration requires the existing setup token",
            })
            return False

        if supplied != f"Bearer {API_TOKEN}":
            self.send_json(401, {
                "error": "unauthorized",
                "message": "The initial setup bearer token is required",
            })
            return False
        return True

    def dispatch(self):
        path = urlparse(self.path).path
        method = self.command

        if method == "POST" and path == "/auth/login":
            return 200, login_account(self.read_body())

        if method == "POST" and path == "/auth/register":
            if AUTH_FILE.exists():
                raise APIError("already_registered", "StoryBox account is already registered", 409)
            if not API_TOKEN or self.headers.get("Authorization", "") != f"Bearer {API_TOKEN}":
                raise APIError("unauthorized", "Initial setup bearer token is required", 401)
            return 201, register_account(self.read_body())

        if not self.authorized():
            return

        if method == "GET" and path == "/device/info":
            return 200, device_info()
        if method == "GET" and path == "/device/wifi/scan":
            return 200, scan_wifi()
        if method == "POST" and path == "/device/wifi/connect":
            return 202, start_wifi_connect(self.read_body())
        if method == "GET" and path == "/device/wifi/connect/status":
            return 200, get_wifi_connect_status(urlparse(self.path).query)
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
        if urlparse(self.path).path == "/console":
            page = Path(__file__).parent / "web" / "api_console.html"
            try:
                body = page.read_bytes()
            except OSError:
                self.send_json(500, {
                    "error": "console_unavailable",
                    "message": "API console page is unavailable",
                })
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

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
    try:
        recover_sync_transaction()
        recover_wifi_connect_operation(force=True)
    except Exception as exc:
        raise SystemExit(f"StoryBox sync recovery failed; API startup stopped: {exc}") from exc

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
