import json
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import storybox.local_api as local_api

from storybox.local_api import (
    APIError,
    safe_relative_path,
    validate_settings,
    validate_wifi_networks,
)


class HandlerErrorTests(unittest.TestCase):
    def test_unexpected_error_does_not_leak_internal_details(self):
        handler = object.__new__(local_api.StoryBoxAPIHandler)
        output = StringIO()
        with (
            patch.object(
                local_api.StoryBoxAPIHandler,
                "dispatch",
                side_effect=RuntimeError("sensitive internal detail"),
            ),
            patch.object(local_api.StoryBoxAPIHandler, "send_json") as send_json,
            redirect_stdout(output),
        ):
            handler.handle_request()

        send_json.assert_called_once_with(500, {
            "error": "internal_error",
            "message": "An unexpected server error occurred",
        })
        self.assertIn("sensitive internal detail", output.getvalue())


class LocalAPITests(unittest.TestCase):
    def test_safe_relative_path_accepts_nested_path(self):
        self.assertEqual(
            str(safe_relative_path("audio/story.mp3")),
            "audio/story.mp3",
        )

    def test_safe_relative_path_rejects_parent_traversal(self):
        with self.assertRaises(APIError):
            safe_relative_path("../outside.mp3")

    def test_safe_relative_path_rejects_absolute_path(self):
        with self.assertRaises(APIError):
            safe_relative_path("/etc/passwd")

    def test_safe_relative_path_rejects_current_directory(self):
        with self.assertRaises(APIError):
            safe_relative_path(".")

    def test_safe_relative_path_rejects_normalized_aliases(self):
        for value in ("./story.mp3", "audio//story.mp3"):
            with self.subTest(value=value):
                with self.assertRaises(APIError):
                    safe_relative_path(value)

    def test_settings_reject_boolean_volume(self):
        for value in (True, False):
            with self.subTest(value=value):
                with self.assertRaises(APIError):
                    local_api.validate_settings({"max_volume": value})

    def test_sync_rejects_invalid_https_url_port(self):
        for url in (
            "https://example.com:invalid/story.mp3",
            "https://example.com:99999/story.mp3",
        ):
            with self.subTest(url=url):
                with self.assertRaises(APIError):
                    local_api.validated_https_origin(url)

    def test_redirect_chain_cannot_leave_original_origin(self):
        handler = local_api.SameOriginHTTPSRedirectHandler(
            ("trusted.example", 443)
        )
        intermediate_request = local_api.urllib.request.Request(
            "https://intermediate.example/redirect"
        )

        with self.assertRaises(APIError) as context:
            handler.redirect_request(
                intermediate_request,
                None,
                302,
                "Found",
                {},
                "https://attacker.example/story.mp3",
            )

        self.assertEqual(context.exception.code, "unsafe_redirect")

    def test_settings_volume_range(self):
        self.assertEqual(validate_settings({"max_volume": 80})["max_volume"], 80)
        with self.assertRaises(APIError):
            validate_settings({"max_volume": 101})

    def test_settings_language(self):
        self.assertEqual(validate_settings({"language": "en"})["language"], "en")
        with self.assertRaises(APIError):
            validate_settings({"language": "xx"})

    def test_wifi_network_validation(self):
        result = validate_wifi_networks([
            {"ssid": "Home Wi-Fi", "password": "password123"}
        ])
        self.assertEqual(result[0]["ssid"], "Home Wi-Fi")

    def test_wifi_network_rejects_short_password(self):
        with self.assertRaises(APIError):
            validate_wifi_networks([
                {"ssid": "Home Wi-Fi", "password": "short"}
            ])


class DevicePairingQRTests(unittest.TestCase):
    def test_qr_is_stable_for_same_persistent_device_identity(self):
        identity = {"device_id": "sb-00000000-0000-4000-8000-000000000001"}
        with patch.object(local_api, "get_device_identity", return_value=identity):
            first = local_api.device_pairing_qr_svg()
            second = local_api.device_pairing_qr_svg()

        self.assertEqual(first, second)
        self.assertIn(b"<svg", first)

    def test_qr_payload_excludes_network_and_auth_secrets(self):
        identity = {"device_id": "sb-00000000-0000-4000-8000-000000000001"}
        with patch.object(local_api, "get_device_identity", return_value=identity):
            first = local_api.device_pairing_qr_svg()

        self.assertNotIn(b"192.168.", first)
        self.assertNotIn(b"Bearer", first)
        self.assertNotIn(b"password", first.lower())


class SyncRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.library = self.root / "library"
        self.data_dir = self.root / "data"
        self.journal_file = self.data_dir / "sync-journal.json"
        self.state_file = self.data_dir / "sync-state.json"
        self.data_dir.mkdir()

        self.patches = [
            patch.object(local_api, "LIBRARY_DIR", self.library),
            patch.object(local_api, "SYNC_JOURNAL_FILE", self.journal_file),
            patch.object(local_api, "SYNC_FILE", self.state_file),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def write_journal(self, transaction_id, phase, had_library, stage_name, backup_name):
        self.journal_file.write_text(json.dumps({
            "transaction_id": transaction_id,
            "phase": phase,
            "had_library": had_library,
            "stage_name": stage_name,
            "backup_name": backup_name,
        }), encoding="utf-8")

    def test_interrupted_activation_restores_old_library(self):
        txid = str(uuid.uuid4())
        stage = f".library.stage-{txid}"
        backup_name = f".library.backup-{txid}"

        self.library.mkdir()
        (self.library / "new.txt").write_text("new")
        backup = self.root / backup_name
        backup.mkdir()
        (backup / "old.txt").write_text("old")

        self.write_journal(txid, "library_activated", True, stage, backup_name)

        self.assertTrue(local_api.recover_sync_transaction())
        self.assertEqual((self.library / "old.txt").read_text(), "old")
        self.assertFalse((self.library / "new.txt").exists())
        self.assertFalse(backup.exists())
        self.assertFalse(self.journal_file.exists())

    def test_committed_transaction_keeps_new_library(self):
        txid = str(uuid.uuid4())
        stage = f".library.stage-{txid}"
        backup_name = f".library.backup-{txid}"

        self.library.mkdir()
        (self.library / "new.txt").write_text("new")
        backup = self.root / backup_name
        backup.mkdir()
        (backup / "old.txt").write_text("old")

        self.state_file.write_text(json.dumps({
            "transaction_id": txid,
            "sync_version": 5,
        }))
        self.write_journal(txid, "state_committed", True, stage, backup_name)

        self.assertTrue(local_api.recover_sync_transaction())
        self.assertEqual((self.library / "new.txt").read_text(), "new")
        self.assertFalse(backup.exists())
        self.assertFalse(self.journal_file.exists())

    def test_uncommitted_new_library_is_removed(self):
        txid = str(uuid.uuid4())
        stage = f".library.stage-{txid}"

        self.library.mkdir()
        (self.library / "new.txt").write_text("new")
        self.write_journal(txid, "library_activated", False, stage, None)

        self.assertTrue(local_api.recover_sync_transaction())
        self.assertFalse(self.library.exists())
        self.assertFalse(self.journal_file.exists())

    def test_recovery_rejects_unsafe_journal_path(self):
        txid = str(uuid.uuid4())
        self.write_journal(txid, "prepared", False, "../outside", None)

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(self.journal_file.exists())

    def test_recovery_rejects_symlinked_journal(self):
        target = self.root / "journal-target.json"
        target.write_text("{}", encoding="utf-8")
        self.journal_file.symlink_to(target)

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(self.journal_file.is_symlink())
        self.assertTrue(target.is_file())

    def test_recovery_rejects_directory_as_journal(self):
        self.journal_file.mkdir()

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(self.journal_file.is_dir())

    def test_recovery_rejects_regular_file_as_stage(self):
        txid = str(uuid.uuid4())
        stage = f".library.stage-{txid}"
        stage_path = self.root / stage
        stage_path.write_text("not a directory", encoding="utf-8")
        self.write_journal(txid, "prepared", False, stage, None)

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(stage_path.is_file())
        self.assertTrue(self.journal_file.exists())

    def test_recovery_rejects_symlinked_backup(self):
        txid = str(uuid.uuid4())
        stage = f".library.stage-{txid}"
        backup = f".library.backup-{txid}"
        target = self.root / "backup-target"
        target.mkdir()
        backup_path = self.root / backup
        backup_path.symlink_to(target, target_is_directory=True)

        self.write_journal(txid, "prepared", True, stage, backup)

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(backup_path.is_symlink())
        self.assertTrue(target.is_dir())
        self.assertTrue(self.journal_file.exists())

    def test_recovery_rejects_path_with_different_transaction_id(self):
        txid = str(uuid.uuid4())
        other_txid = str(uuid.uuid4())
        stage = f".library.stage-{other_txid}"

        self.write_journal(txid, "prepared", False, stage, None)

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(self.journal_file.exists())

    def test_remove_transaction_path_rejects_regular_file(self):
        path = self.root / ".library.stage-test"
        path.write_text("not a directory", encoding="utf-8")

        with self.assertRaises(APIError):
            local_api.remove_transaction_path(path)

        self.assertTrue(path.is_file())

    def test_remove_transaction_path_rejects_symlink(self):
        target = self.root / "target"
        target.mkdir()
        link = self.root / ".library.stage-test"
        link.symlink_to(target, target_is_directory=True)

        with self.assertRaises(APIError):
            local_api.remove_transaction_path(link)

        self.assertTrue(link.is_symlink())
        self.assertTrue(target.is_dir())

    def test_recovery_rejects_regular_file_as_library(self):
        txid = str(uuid.uuid4())
        stage = f".library.stage-{txid}"

        self.library.write_text("not a library directory", encoding="utf-8")
        self.write_journal(txid, "prepared", False, stage, None)

        with self.assertRaises(APIError):
            local_api.recover_sync_transaction()

        self.assertTrue(self.library.is_file())
        self.assertTrue(self.journal_file.exists())


class SyncWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.library = self.root / "library"
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()

        self.patches = [
            patch.object(local_api, "LIBRARY_DIR", self.library),
            patch.object(local_api, "DATA_DIR", self.data_dir),
            patch.object(local_api, "SYNC_JOURNAL_FILE", self.data_dir / "sync-journal.json"),
            patch.object(local_api, "SYNC_FILE", self.data_dir / "sync-state.json"),
            patch.object(local_api, "SYNC_PROGRESS", {"sync_status": "idle", "stories": []}),
        ]
        for item in self.patches:
            item.start()

        self.payload = {
            "sync_version": 7,
            "stories": [{
                "id": "story_new",
                "title": "Test Story",
                "files": [{
                    "path": "audio/story.mp3",
                    "download_url": "https://example.invalid/story.mp3",
                    "size_bytes": 4,
                }],
            }],
        }

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    @staticmethod
    def fake_download(url, destination, expected_size, expected_sha):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"test")

    def test_start_sync_refuses_pending_recovery_journal(self):
        journal = local_api.SYNC_JOURNAL_FILE
        journal.write_text('{"pending": true}', encoding="utf-8")

        with (
            patch.object(local_api, "SYNC_THREAD", None),
            patch.object(local_api.threading, "Thread") as thread_mock,
        ):
            with self.assertRaises(APIError):
                local_api.start_sync(self.payload)

            thread_mock.assert_not_called()

        self.assertTrue(journal.is_file())
        self.assertEqual(
            journal.read_text(encoding="utf-8"),
            '{"pending": true}',
        )

    def test_failed_download_preserves_old_library_and_state(self):
        self.library.mkdir()
        (self.library / "old.txt").write_text("old")
        old_state = {"sync_version": 3, "stories": [{"id": "old_story"}]}
        local_api.atomic_json(local_api.SYNC_FILE, old_state)

        with patch.object(
            local_api, "download_file", side_effect=OSError("simulated download failure")
        ):
            local_api.sync_worker(self.payload)

        self.assertEqual((self.library / "old.txt").read_text(), "old")
        self.assertEqual(local_api.read_json(local_api.SYNC_FILE, {}), old_state)
        self.assertFalse(local_api.SYNC_JOURNAL_FILE.exists())
        self.assertEqual(local_api.SYNC_PROGRESS["sync_status"], "failed")
        self.assertEqual(list(self.root.glob(".library.stage-*")), [])

    def test_state_read_failure_still_marks_sync_failed(self):
        with (
            patch.object(
                local_api,
                "download_file",
                side_effect=OSError("simulated download failure"),
            ),
            patch.object(
                local_api,
                "read_json",
                side_effect=APIError("state_unavailable", "simulated state read failure", 500),
            ),
        ):
            local_api.sync_worker(self.payload)

        self.assertEqual(local_api.SYNC_PROGRESS["sync_status"], "failed")
        self.assertIn(
            "simulated download failure",
            local_api.SYNC_PROGRESS["error"],
        )
        self.assertIn(
            "simulated state read failure",
            local_api.SYNC_PROGRESS["error"],
        )

    def test_successful_sync_activates_snapshot_and_updates_version(self):
        self.library.mkdir()
        (self.library / "old.txt").write_text("old")
        local_api.atomic_json(
            local_api.SYNC_FILE,
            {"sync_version": 3, "stories": [{"id": "old_story"}]},
        )

        with patch.object(local_api, "download_file", side_effect=self.fake_download):
            local_api.sync_worker(self.payload)

        installed_file = self.library / "story_new" / "audio" / "story.mp3"
        self.assertEqual(installed_file.read_bytes(), b"test")
        self.assertFalse((self.library / "old.txt").exists())

        state = local_api.read_json(local_api.SYNC_FILE, {})
        self.assertEqual(state["sync_version"], 7)
        self.assertTrue(state.get("transaction_id"))
        self.assertEqual(local_api.SYNC_PROGRESS["sync_status"], "completed")
        self.assertFalse(local_api.SYNC_JOURNAL_FILE.exists())
        self.assertEqual(list(self.root.glob(".library.backup-*")), [])

    def test_cleanup_failure_does_not_mark_committed_sync_failed(self):
        self.library.mkdir()
        (self.library / "old.txt").write_text("old")

        with (
            patch.object(local_api, "download_file", side_effect=self.fake_download),
            patch.object(
                local_api,
                "recover_sync_transaction",
                side_effect=OSError("simulated cleanup failure"),
            ),
        ):
            local_api.sync_worker(self.payload)

        state = local_api.read_json(local_api.SYNC_FILE, {})
        self.assertEqual(state["sync_version"], 7)
        self.assertEqual(local_api.SYNC_PROGRESS["sync_status"], "completed")
        self.assertTrue(local_api.SYNC_JOURNAL_FILE.exists())
        self.assertEqual(len(list(self.root.glob(".library.backup-*"))), 1)


class SetupResetSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir()

        self.setup_file = self.data_dir / "setup.json"
        self.settings_file = self.data_dir / "settings.json"
        self.wifi_file = self.data_dir / "wifi-networks.json"
        self.sync_file = self.data_dir / "sync-state.json"
        self.journal_file = self.data_dir / "sync-journal.json"

        self.patches = [
            patch.object(local_api, "DATA_DIR", self.data_dir),
            patch.object(local_api, "SETUP_FILE", self.setup_file),
            patch.object(local_api, "SETTINGS_FILE", self.settings_file),
            patch.object(local_api, "WIFI_FILE", self.wifi_file),
            patch.object(local_api, "SYNC_FILE", self.sync_file),
            patch.object(local_api, "SYNC_JOURNAL_FILE", self.journal_file),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp_dir.cleanup()

    def test_setup_during_sync_does_not_partially_write(self):
        class RunningThread:
            def is_alive(self):
                return True

        with patch.object(local_api, "SYNC_THREAD", RunningThread()):
            with self.assertRaises(APIError):
                local_api.apply_setup({
                    "name": "Test StoryBox",
                    "settings": {"language": "en", "max_volume": 60},
                    "wifi_networks": [{
                        "ssid": "Test Wi-Fi",
                        "password": "temporary-password",
                    }],
                    "sync_version": 5,
                })

        self.assertFalse(self.setup_file.exists())
        self.assertFalse(self.settings_file.exists())
        self.assertFalse(self.wifi_file.exists())
        self.assertFalse(self.sync_file.exists())

    def test_setup_rejects_boolean_sync_version(self):
        with self.assertRaises(APIError):
            local_api.apply_setup({
                "name": "Test StoryBox",
                "sync_version": True,
            })

        self.assertFalse(self.setup_file.exists())
        self.assertFalse(self.sync_file.exists())

    def test_reset_during_sync_preserves_all_data(self):
        class RunningThread:
            def is_alive(self):
                return True

        files = (
            self.setup_file,
            self.settings_file,
            self.wifi_file,
            self.sync_file,
        )
        for file_path in files:
            file_path.write_text('{"keep": true}', encoding="utf-8")

        with patch.object(local_api, "SYNC_THREAD", RunningThread()):
            with self.assertRaises(APIError):
                local_api.reset_parent_data()

        for file_path in files:
            self.assertTrue(file_path.exists())
            self.assertEqual(
                file_path.read_text(encoding="utf-8"),
                '{"keep": true}',
            )

    def test_reset_refuses_broken_journal_symlink(self):
        self.journal_file.symlink_to(self.data_dir / "missing-journal.json")
        self.setup_file.write_text('{"name": "Test"}', encoding="utf-8")

        with self.assertRaises(APIError):
            local_api.reset_parent_data()

        self.assertTrue(self.journal_file.is_symlink())
        self.assertTrue(self.setup_file.exists())

    def test_reset_refuses_pending_recovery_journal(self):
        self.setup_file.write_text('{"name": "Keep"}', encoding="utf-8")
        self.sync_file.write_text('{"sync_version": 4}', encoding="utf-8")
        self.journal_file.write_text('{"pending": true}', encoding="utf-8")

        with self.assertRaises(APIError):
            local_api.reset_parent_data()

        self.assertTrue(self.setup_file.exists())
        self.assertTrue(self.sync_file.exists())
        self.assertTrue(self.journal_file.exists())


if __name__ == "__main__":
    unittest.main()
