import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import storybox.local_api as api



class ProvisioningTokenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.token_file = self.data_dir / "provisioning-token.txt"
        self.auth_file = self.data_dir / "auth.json"
        self.patches = [
            patch.object(api, "DATA_DIR", self.data_dir),
            patch.object(api, "PROVISIONING_TOKEN_FILE", self.token_file),
            patch.object(api, "AUTH_FILE", self.auth_file),
            patch.object(api, "API_TOKEN", ""),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_first_start_generates_secure_token_file(self):
        token = api.ensure_setup_token()

        self.assertGreaterEqual(len(token), 32)
        self.assertEqual(self.token_file.read_text().strip(), token)
        self.assertEqual(self.token_file.stat().st_mode & 0o777, 0o600)

    def test_token_is_stable_across_restarts(self):
        first = api.ensure_setup_token()
        with patch.object(api, "API_TOKEN", ""):
            second = api.ensure_setup_token()

        self.assertEqual(first, second)

    def test_registration_consumes_provisioning_token(self):
        api.ensure_setup_token()
        self.assertTrue(self.token_file.exists())

        api.register_account({"password": "Test-Password-2026!"})

        self.assertFalse(self.token_file.exists())
        self.assertTrue(self.auth_file.exists())

    def test_configured_environment_token_is_preserved(self):
        with patch.object(api, "API_TOKEN", "configured-installer-token"):
            token = api.ensure_setup_token()

        self.assertEqual(token, "configured-installer-token")
        self.assertFalse(self.token_file.exists())


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.auth_file = Path(self.temp.name) / "auth.json"
        self.patch = patch.object(api, "AUTH_FILE", self.auth_file)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_register_and_login(self):
        result = api.register_account({
            "password": "Test-Password-2026!"
        })
        self.assertTrue(self.auth_file.exists())

        login = api.login_account({
            "password": "Test-Password-2026!"
        })
        self.assertTrue(login.get("access_token"))
        self.assertTrue(api.valid_login_token(login["access_token"]))

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
