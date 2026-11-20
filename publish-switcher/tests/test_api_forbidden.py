import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Source, AccessDenied
import tool_update


class ForbiddenTests(unittest.TestCase):
    def test_api_403_preserves_status_and_displays_endpoint_without_query(self):
        url = "https://gitee.com/api/v5/repos/potper/odoiotassets/branches/main?token=private"
        with patch("core.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            with self.assertRaises(AccessDenied) as failure:
                Source.fetch_bytes(url)
        self.assertEqual(failure.exception.code, 403)
        self.assertIn("/branches/main", str(failure.exception))
        self.assertNotIn("private", str(failure.exception))
        self.assertEqual(opener.return_value.open.call_count, 1)

    def test_program_check_uses_public_file_when_branch_api_is_forbidden(self):
        url = "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/switcher-update.json"
        release = {"schema_version": 1, "product": "publish-switcher", "version": "2026.11.20.4",
                   "url": "https://example.org/switcher.zip", "package_file": "switcher.zip",
                   "size": 100, "sha256": "a" * 64}
        refused = urllib.error.HTTPError("https://gitee.com/api/v5/repos/potper/odoiotassets/branches/main", 403, "Forbidden", {}, None)
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory) / "switcher"
            install.mkdir()
            with patch.object(Source, "remote", side_effect=refused), \
                 patch.object(Source, "metadata", return_value=json.dumps(release).encode()) as fetch:
                actual, newer = tool_update.check_release(url, install, "2026.11.20.3")
            fetch.assert_called_once_with(url)
            self.assertTrue(newer)
            self.assertEqual(actual["version"], release["version"])

    def test_package_direct_fallback_does_not_apply_to_other_http_errors(self):
        url = "https://gitee.com/potper/odoiotassets/raw/main/package.zip"
        with patch.object(Source, "remote", side_effect=urllib.error.HTTPError("api", 404, "missing", {}, None)):
            with self.assertRaises(urllib.error.HTTPError):
                tool_update.remote_file(url)

    def test_raw_forbidden_still_fails_instead_of_unlocking_the_program(self):
        url = "https://gitee.com/potper/odoiotassets/raw/main/update.json"
        refused = lambda: urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory) / "switcher"
            install.mkdir()
            with patch.object(Source, "remote", side_effect=refused()), patch.object(Source, "metadata", side_effect=refused()):
                with self.assertRaises(urllib.error.HTTPError):
                    tool_update.check_release(url, install, "2026.11.20.3")
            self.assertFalse((tool_update.update_state(install) / "required.json").exists())
