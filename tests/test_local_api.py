import unittest

from storybox.local_api import (
    APIError,
    safe_relative_path,
    validate_settings,
    validate_wifi_networks,
)


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


if __name__ == "__main__":
    unittest.main()
