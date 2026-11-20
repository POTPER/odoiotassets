from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "launcher"))
from core import SyncError
from gitee_download import download_blob


class PackageTransportTests(unittest.TestCase):
    def test_offline_dependency_sized_package_can_reach_the_public_blob_transport(self):
        source = Mock(api_base="https://gitee.com/api/v5/repos/example/resources")
        source.fetch_bytes.side_effect = RuntimeError("transport reached")
        with patch("gitee_download.blob_sha", return_value="a" * 40):
            with self.assertRaisesRegex(RuntimeError, "transport reached"):
                download_blob(source, "aiot-workbench.zip", "unused.zip", 36 * 1024**2, "b" * 64, None, lambda n: None)
        source.fetch_bytes.assert_called_once()

    def test_excessive_blob_response_remains_bounded(self):
        with self.assertRaisesRegex(SyncError, "64 MiB"):
            download_blob(Mock(), "too-large.zip", "unused.zip", 65 * 1024**2, "b" * 64, None, lambda n: None)
