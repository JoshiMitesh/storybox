from pathlib import Path
import unittest


class TestWifiConnect(unittest.TestCase):
    def test_both_profile_lookups_use_connection_uuid(self):
        source = (
            Path(__file__).parents[1]
            / "src/storybox/wifi/connect_wifi.py"
        ).read_text()

        self.assertEqual(
            source.count('"-g", "connection.uuid"'),
            2,
        )
        self.assertNotIn('"-g", "UUID"', source)


if __name__ == "__main__":
    unittest.main()
