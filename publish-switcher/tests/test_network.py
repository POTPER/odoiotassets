import hashlib
import http.client
import io
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_sync
from tools.packaging.legacy.core import Source, SyncError


def response(payload, length=None):
    stream = io.BytesIO(payload)
    stream.headers = {} if length is None else {"Content-Length": str(length)}
    return stream


class NetworkTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def test_incomplete_metadata_retries_from_start(self):
        with patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener, patch("publish_switcher.repositories.source.retry_pause") as pause:
            opener.return_value.open.side_effect = [http.client.IncompleteRead(b"partial", 100), response(b"complete")]
            self.assertEqual(Source.fetch_bytes("https://example.com/meta"), b"complete")
            self.assertEqual(opener.return_value.open.call_count, 2)
            pause.assert_called_once()

    def test_short_content_length_retries(self):
        with patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener, patch("publish_switcher.repositories.source.retry_pause"):
            opener.return_value.open.side_effect = [response(b"short", 100), response(b"full", 4)]
            self.assertEqual(Source.fetch_bytes("https://example.com/meta"), b"full")

    def test_404_does_not_retry(self):
        error = urllib.error.HTTPError("url", 404, "missing", {}, None)
        with patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener, patch("publish_switcher.repositories.source.retry_pause") as pause:
            opener.return_value.open.side_effect = error
            with self.assertRaises(urllib.error.HTTPError):
                Source.fetch_bytes("https://example.com/meta")
            pause.assert_not_called()

    def test_incomplete_metadata_exhausts_three_attempts(self):
        with patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener, patch("publish_switcher.repositories.source.retry_pause"):
            opener.return_value.open.side_effect = http.client.IncompleteRead(b"partial", 100)
            with self.assertRaises(http.client.IncompleteRead):
                Source.fetch_bytes("https://example.com/meta")
            self.assertEqual(opener.return_value.open.call_count, 3)

    def test_short_download_retries_without_using_partial_cache(self):
        payload = b"complete file"
        path = self.base / "downloaded"
        with patch("publish_switcher.repositories.source.urllib.request.build_opener") as opener, patch("publish_switcher.repositories.source.retry_pause"):
            opener.return_value.open.side_effect = [response(b"partial"), response(payload)]
            Source().download("https://example.com/file", path, len(payload), hashlib.sha256(payload).hexdigest(), None, lambda n: None)
        self.assertEqual(path.read_bytes(), payload)
        self.assertFalse(list(self.base.glob("*.part-*")))

    def test_ref_request_is_small_and_branch_specific(self):
        raw = b'{"ref":"refs/heads/feature/test","object":{"type":"commit","sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}'
        with patch.object(Source, "fetch_bytes", return_value=raw) as fetch:
            source = Source.github("https://github.com/example/repo", "feature/test")
        self.assertEqual(source.commit, "a" * 40)
        self.assertTrue(fetch.call_args[0][0].endswith("/git/ref/heads/feature%2Ftest"))
