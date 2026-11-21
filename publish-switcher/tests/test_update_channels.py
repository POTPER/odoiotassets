from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.packaging.legacy.core import SyncError
from publish_switcher.repositories.catalog import DEFAULT_PROFILES
from publish_switcher.repositories.discovery import discover
from publish_switcher.updates.channels import channel_name, selected_channel
from publish_switcher.updates import bootstrap as tool_update


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.rows = [{"url": "https://gitee.com/potper/odoiotassets", "branch": "main"},
                     {"url": "https://github.com/POTPER/odoiotassets", "branch": "main"},
                     {"url": "https://jihulab.com/group/subgroup/assets", "branch": "devices/rk"}]

    def test_channel_numbers_and_default_first_address(self):
        self.assertEqual([channel_name(i) for i in (0, 1, 2, 15)], ["通道一", "通道二", "通道三", "通道十六"])
        rows, address = selected_channel(self.rows, 0, tool_update.DEFAULT_UPDATE_URL)
        self.assertEqual(rows, self.rows[:1])
        self.assertEqual(address, tool_update.DEFAULT_UPDATE_URL)

    def test_selected_github_and_jihu_map_metadata_to_that_repository_only(self):
        rows, address = selected_channel(self.rows, 1, tool_update.DEFAULT_UPDATE_URL)
        self.assertEqual(rows, [self.rows[1]])
        self.assertEqual(address, "https://raw.githubusercontent.com/POTPER/odoiotassets/main/publish-switcher/release/switcher-update.json")
        rows, address = selected_channel(self.rows, 2, tool_update.DEFAULT_UPDATE_URL)
        self.assertEqual(rows, [self.rows[2]])
        self.assertIn("/-/raw/devices%2Frk/publish-switcher/release/", address)

    def test_canonical_package_url_is_remapped_to_the_selected_channel_too(self):
        rows, address = selected_channel(self.rows, 1, tool_update.DEFAULT_UPDATE_URL)
        package_url = "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/publish-switcher.zip"
        self.assertEqual(tool_update.mirror_locations(package_url, rows),
                         ["https://raw.githubusercontent.com/POTPER/odoiotassets/main/publish-switcher/release/publish-switcher.zip"])

    def test_reordered_settings_define_channel_numbers_without_mutating_input(self):
        reordered = [self.rows[1], self.rows[0]]
        rows, address = selected_channel(reordered, 0, tool_update.DEFAULT_UPDATE_URL)
        self.assertEqual(rows, [self.rows[1]])
        self.assertIn("raw.githubusercontent.com", address)
        self.assertEqual(reordered, [self.rows[1], self.rows[0]])

    def test_custom_repository_path_maps_but_external_release_url_is_preserved(self):
        rows, address = selected_channel(self.rows, 1, "https://gitee.com/potper/odoiotassets/raw/main/custom/release.json")
        self.assertEqual(address, "https://raw.githubusercontent.com/POTPER/odoiotassets/main/custom/release.json")
        rows, address = selected_channel(self.rows, 1, "https://updates.example.org/release.json")
        self.assertEqual(address, "https://updates.example.org/release.json")
        self.assertEqual(rows, [self.rows[1]])

    def test_invalid_channel_is_rejected(self):
        for index in (-1, len(self.rows), True, "1"):
            with self.subTest(index=index), self.assertRaises(SyncError):
                selected_channel(self.rows, index, tool_update.DEFAULT_UPDATE_URL)

    def test_selected_channel_discovery_failure_never_tries_other_channels(self):
        rows, address = selected_channel(self.rows, 0, tool_update.DEFAULT_UPDATE_URL)
        with patch("publish_switcher.repositories.discovery.Source.remote", side_effect=urllib.error.HTTPError(address, 403, "Forbidden", {}, None)) as connect:
            with self.assertRaises(SyncError):
                discover(rows, DEFAULT_PROFILES)
        connect.assert_called_once_with(self.rows[0]["url"], "main")

    def test_selected_program_metadata_failure_never_tries_another_channel(self):
        rows, address = selected_channel(self.rows, 1, tool_update.DEFAULT_UPDATE_URL)
        with patch("publish_switcher.updates.release.remote_file", side_effect=urllib.error.HTTPError(address, 403, "Forbidden", {}, None)) as locate:
            with self.assertRaises(tool_update.UpdateError):
                tool_update.check_release(address, Path("unused"), "2026.11.20.8", repositories=rows)
        locate.assert_called_once_with(address)
