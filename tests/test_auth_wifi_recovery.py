import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import storybox.local_api as api



class RegistrationWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.window_file = self.root / "registration-window.json"
        self.auth_file = self.root / "auth.json"
        self.patches = [
            patch.object(api, "REGISTRATION_WINDOW_FILE", self.window_file),
            patch.object(api, "AUTH_FILE", self.auth_file),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_first_start_creates_ten_minute_window(self):
        self.assertTrue(api.initialize_registration_window(now=1000))
        state = json.loads(self.window_file.read_text())
        self.assertEqual(state["opened_at"], 1000)
        self.assertEqual(state["expires_at"], 1000 + 600)
        self.assertEqual(self.window_file.stat().st_mode & 0o777, 0o600)

    def test_restart_does_not_extend_registration_window(self):
        api.initialize_registration_window(now=1000)
        self.assertTrue(api.initialize_registration_window(now=1100))
        state = json.loads(self.window_file.read_text())
        self.assertEqual(state["expires_at"], 1600)

    def test_expired_window_stays_closed_after_restart(self):
        api.initialize_registration_window(now=1000)
        self.assertFalse(api.initialize_registration_window(now=1600))
        self.assertFalse(api.registration_window_open(now=1600))

    def test_registration_consumes_window(self):
        api.initialize_registration_window()
        api.register_account({"password": "Test-Password-2026!"})
        self.assertTrue(self.auth_file.exists())
        self.assertFalse(self.window_file.exists())

    def test_invalid_window_state_fails_closed(self):
        self.window_file.write_text('{"expires_at":"later"}')
        with self.assertRaises(api.APIError):
            api.initialize_registration_window(now=1000)

    def test_registration_rejected_after_deadline(self):
        api.initialize_registration_window(now=1000)
        with patch.object(api.time, "time", return_value=1600):
            with self.assertRaises(api.APIError) as raised:
                api.register_account({"password": "Test-Password-2026!"})
        self.assertEqual(raised.exception.code, "registration_closed")
        self.assertFalse(self.auth_file.exists())



class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.auth_file = Path(self.temp.name) / "auth.json"
        self.window_file = Path(self.temp.name) / "registration-window.json"
        self.auth_patch = patch.object(api, "AUTH_FILE", self.auth_file)
        self.window_patch = patch.object(api, "REGISTRATION_WINDOW_FILE", self.window_file)
        self.auth_patch.start()
        self.window_patch.start()
        api.initialize_registration_window()

    def tearDown(self):
        self.window_patch.stop()
        self.auth_patch.stop()
        self.temp.cleanup()

    def test_register_and_login(self):
        result = api.register_account({
            "username": "ignored-user",
            "password": "Test-Password-2026!",
            "password_confirmation": "Test-Password-2026!",
        })
        self.assertTrue(self.auth_file.exists())
        self.assertEqual(result["username"], "admin")
        self.assertTrue(result["registered"])
        self.assertTrue(result.get("access_token"))
        self.assertTrue(api.valid_login_token(result["access_token"]))

        saved = json.loads(self.auth_file.read_text())
        self.assertEqual(saved["username"], "admin")
        self.assertNotIn("password", saved)

        login = api.login_account({
            "password": "Test-Password-2026!"
        })
        self.assertEqual(login["username"], "admin")
        self.assertTrue(login.get("access_token"))
        self.assertTrue(api.valid_login_token(login["access_token"]))

    def test_registration_rejects_password_confirmation_mismatch(self):
        with self.assertRaises(api.APIError) as raised:
            api.register_account({
                "password": "Test-Password-2026!",
                "password_confirmation": "Different-Password-2026!",
            })
        self.assertEqual(raised.exception.code, "password_mismatch")
        self.assertFalse(self.auth_file.exists())

    def test_duplicate_registration_rejected(self):
        api.register_account({"password": "Test-Password-2026!"})

        with self.assertRaises(api.APIError):
            api.register_account({"password": "Another-Password-2026!"})

    def test_wrong_password_rejected(self):
        api.register_account({"password": "Test-Password-2026!"})

        with self.assertRaises(api.APIError):
            api.login_account({"password": "Wrong-Password-2026!"})

    def test_short_password_rejected(self):
        with self.assertRaises(api.APIError):
            api.register_account({"password": "short"})

    def test_password_is_not_stored_as_plain_text(self):
        api.register_account({"password": "Test-Password-2026!"})

        saved = self.auth_file.read_text()
        self.assertNotIn("Test-Password-2026!", saved)


class WifiRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.operation_file = Path(self.temp.name) / "wifi-operation.json"
        self.patch = patch.object(api, "WIFI_CONNECT_FILE", self.operation_file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_wifi_operation_result_is_persisted(self):
        operation_id = str(uuid.uuid4())

        with patch.object(api, "connect_wifi", return_value={
            "connected": False,
            "success": True,
            "dry_run": True,
            "message": "Dry run successful",
        }):
            api.run_wifi_connect_operation(operation_id, {
                "ssid": "StoryBox-Test",
                "password": "temporary-secret",
                "dry_run": True,
            })

        saved = json.loads(self.operation_file.read_text())

        self.assertEqual(saved["operation_id"], operation_id)
        self.assertEqual(saved["status"], "success")
        self.assertEqual(saved["message"], "Dry run successful")
        self.assertNotIn("temporary-secret", self.operation_file.read_text())

    def test_wifi_operation_failure_is_persisted(self):
        operation_id = str(uuid.uuid4())

        with patch.object(api, "connect_wifi", side_effect=api.APIError(
            "wifi_connect_failed",
            "Test connection failed",
        )):
            api.run_wifi_connect_operation(operation_id, {
                "ssid": "StoryBox-Test",
                "password": "temporary-secret",
                "dry_run": True,
            })

        saved = json.loads(self.operation_file.read_text())
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["message"], "Test connection failed")

    def test_status_retrieval_rejects_invalid_operation_id(self):
        with self.assertRaises(api.APIError):
            api.get_wifi_connect_status("operation_id=invalid")

    def test_restart_recovers_interrupted_wifi_operation(self):
        operation_id = str(uuid.uuid4())

        self.operation_file.write_text(json.dumps({
            "operation_id": operation_id,
            "status": "pending",
            "ssid": "StoryBox-Test",
            "message": "Wi-Fi connection is in progress",
            "created_at": 100,
        }))

        recovered = api.recover_wifi_connect_operation(force=True)

        saved = json.loads(self.operation_file.read_text())

        self.assertTrue(recovered)
        self.assertEqual(saved["operation_id"], operation_id)
        self.assertEqual(saved["status"], "failed")
        self.assertEqual(saved["error"], "wifi_connect_interrupted")

if __name__ == "__main__":
    unittest.main()
