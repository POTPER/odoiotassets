import io
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback
import unittest
import urllib.error
import urllib.response
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.packaging.legacy.core import Source, AccessDenied
from publish_switcher.updates import bootstrap as tool_update
from publish_switcher.repositories.catalog import DEFAULT_PROFILES
from publish_switcher.repositories.discovery import discover


def python38_http_error_init(self, url, code, msg, hdrs, fp):
    """CPython 3.8.10 initializes its response wrapper only when fp is not None."""
    self.code, self.msg, self.hdrs, self.fp, self.filename = code, msg, hdrs, fp, url
    if fp is not None:
        urllib.response.addinfourl.__init__(self, fp, hdrs, url, code)


class ForbiddenTests(unittest.TestCase):
    def test_python38_bodyless_error_is_printable_closable_and_preserves_http_contract(self):
        url = "https://gitee.com/api/v5/repos/potper/odoiotassets?token=private"
        with patch.object(urllib.error.HTTPError, "__init__", python38_http_error_init):
            error = AccessDenied(url, 403, "Forbidden", {}, None)
            message = str(error)
            self.assertIn("Gitee API", message)
            self.assertNotIn("private", message)
            self.assertEqual(error.geturl(), url)
            self.assertEqual(error.code, 403)
            self.assertIsInstance(error, urllib.error.HTTPError)
            self.assertNotIn("unprintable", "".join(traceback.format_exception_only(type(error), error)))
            error.close()
            error.close()
            self.assertIn("HTTP 403", str(error))

    def test_python38_actual_fetch_and_head_403_still_continue_to_next_repository(self):
        repositories = [{"url": "https://gitee.com/potper/odoiotassets"}, {"url": "https://github.com/POTPER/odoiotassets"}]
        github = Source(owner="POTPER", repo="odoiotassets", commit="a" * 40)
        items = [{"source": github, "profile": {"id": "rk", "version": "1"}}]
        real_remote = Source.remote
        def connect(address, branch):
            return real_remote(address, branch) if "gitee.com" in address else github
        for all_results in (False, True):
            with self.subTest(all_results=all_results), \
                    patch.object(urllib.error.HTTPError, "__init__", python38_http_error_init), \
                    patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener, \
                    patch.object(Source, "remote", side_effect=connect), \
                    patch("publish_switcher.repositories.discovery.remote_profiles", return_value=items):
                refused = urllib.error.HTTPError(repositories[0]["url"], 403, "Forbidden", {}, io.BytesIO(b"denied"))
                opener.return_value.open.side_effect = refused
                messages = []
                result = discover(repositories, DEFAULT_PROFILES, messages.append, all_results=all_results)
                self.assertTrue(refused.fp.closed)
                self.assertTrue(any("HTTP 403" in text for text in messages))
                if all_results:
                    self.assertEqual([row["status"] for row in result], ["失败", "可用"])
                else:
                    self.assertEqual(result, items)
        with patch.object(urllib.error.HTTPError, "__init__", python38_http_error_init), \
                patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = urllib.error.HTTPError("https://gitee.com/api/test", 403, "Forbidden", {}, io.BytesIO())
            with self.assertRaises(AccessDenied) as failure:
                Source.head("https://gitee.com/api/test")
            self.assertIn("HTTP 403", str(failure.exception))
            failure.exception.close()

    def test_python38_program_update_direct_fallback_can_close_access_denied(self):
        url = "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/switcher-update.json"
        with patch.object(urllib.error.HTTPError, "__init__", python38_http_error_init):
            error = AccessDenied("https://gitee.com/api/v5/repos/potper/odoiotassets/branches/main", 403, "Forbidden", {}, None)
            with patch.object(Source, "remote", side_effect=error):
                source, location = tool_update.remote_file(url)
            self.assertEqual(location, url)
            self.assertTrue(error.fp.closed)

    def test_python38_original_bodyless_http_error_is_supported_in_all_403_paths(self):
        url = "https://gitee.com/api/v5/repos/potper/odoiotassets"
        with patch.object(urllib.error.HTTPError, "__init__", python38_http_error_init):
            for fetch in (Source.fetch_bytes, Source.head):
                with self.subTest(fetch=fetch.__name__), patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener:
                    opener.return_value.open.side_effect = urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
                    with self.assertRaises(AccessDenied) as failure:
                        fetch(url)
                    self.assertIn("HTTP 403", str(failure.exception))
                    failure.exception.close()
            with patch.object(Source, "remote", side_effect=urllib.error.HTTPError(url, 403, "Forbidden", {}, None)):
                _, location = tool_update.remote_file("https://gitee.com/potper/odoiotassets/raw/main/file.json")
                self.assertTrue(location.endswith("file.json"))

    def test_api_403_preserves_status_and_displays_endpoint_without_query(self):
        url = "https://gitee.com/api/v5/repos/potper/odoiotassets/branches/main?token=private"
        with patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener:
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
