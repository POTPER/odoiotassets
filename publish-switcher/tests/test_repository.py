import hashlib
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.packaging.legacy.core import Engine, Source, SyncError
from publish_switcher.repositories.catalog import DEFAULT_PROFILES, DEFAULT_REPOSITORY, directory_manifest, remote_profiles, validate_presets
import test_sync


class RepositoryTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp
    def native(self, empty=False):
        self.repo.mkdir()
        (self.repo / "publish_RK").mkdir()
        data = b"" if empty else b"native binary"
        (self.repo / "publish_RK/AIotApp").write_bytes(data)
        (self.repo / "publish_RK/sync.py").write_bytes(data)
        nodes = [{"path": "publish_RK", "type": "tree", "mode": "040000"},
                 {"path": "publish_RK/AIotApp", "type": "blob", "mode": "100644", "size": len(data),
                  "sha": hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()}]
        nodes.append(dict(nodes[1], path="publish_RK/sync.py"))
        source = Source(local=self.repo, owner="owner", repo="repo", commit="a" * 40)
        return source, nodes

    def test_native_git_hash_apply(self):
        source, nodes = self.native()
        manifest = directory_manifest(source, DEFAULT_PROFILES[1], nodes)
        engine = Engine(self.target)
        engine.apply(manifest, source)
        self.assertEqual((self.target / "AIotApp").read_bytes(), b"")
        self.assertEqual((self.target / "sync.py").read_bytes(), b"native binary")
        self.assertEqual(engine.preview(manifest)["download_bytes"], 0)
        self.assertFalse(engine.preview(manifest)["changes"])
        self.assertTrue(list((engine.state / "objects").glob("git-*")))

    def test_zero_remote_blocks_without_modifying_target(self):
        source, nodes = self.native(empty=True)
        manifest = directory_manifest(source, DEFAULT_PROFILES[1], nodes)
        self.assertIn("sync.py", manifest["blocked_reason"])
        with self.assertRaises(SyncError):
            Engine(self.target).apply(manifest, source)
        self.assertTrue((self.target / "app.log").exists())

    def test_discovery_and_custom_names(self):
        source, nodes = self.native()
        nodes += [{"path": "publish_jetson", "type": "tree", "mode": "040000"},
                  {"path": "publish_extra", "type": "tree", "mode": "040000"}]
        presets = json.loads(json.dumps(DEFAULT_PROFILES))
        presets[1]["name"] = "RK 自定义"
        missing = urllib.error.HTTPError("https://example.com/catalog", 404, "missing", {}, None)
        with patch.object(source, "metadata", side_effect=missing), patch.object(source, "fetch_bytes", return_value=json.dumps({"tree": nodes, "truncated": False}).encode()):
            items = remote_profiles(source, presets)
        self.assertEqual([p["profile"]["name"] for p in items], ["Jetson", "RK 自定义", "extra"])

    def test_incomplete_tree_and_server_error_never_fallback(self):
        source, nodes = self.native()
        missing = urllib.error.HTTPError("url", 404, "missing", {}, None)
        with patch.object(source, "metadata", side_effect=missing), patch.object(source, "fetch_bytes", return_value=b'{"tree":[],"truncated":true}'):
            with self.assertRaises(SyncError):
                remote_profiles(source, DEFAULT_PROFILES)
        server_error = urllib.error.HTTPError("url", 503, "down", {}, None)
        with patch.object(source, "metadata", side_effect=server_error), patch.object(source, "fetch_bytes") as fetch:
            with self.assertRaises(urllib.error.HTTPError):
                remote_profiles(source, DEFAULT_PROFILES)
            fetch.assert_not_called()

    def test_explicit_catalog_stays_supported(self):
        source, nodes = self.native()
        catalog = {"schema_version": 1, "profiles": [{"id": "catalog", "name": "清单方案", "version": "1", "manifest": "manifest.json", "sha256": "a" * 64}]}
        with patch.object(source, "metadata", return_value=json.dumps(catalog).encode()):
            items = remote_profiles(source, DEFAULT_PROFILES)
        self.assertEqual(items[0]["profile"]["id"], "catalog")
        self.assertNotIn("git_tree", items[0])

    def test_invalid_settings(self):
        with self.assertRaises(SyncError):
            validate_presets([{"id": "rk", "name": "RK", "directory": "../outside"}])
        with self.assertRaises(SyncError):
            validate_presets([{"id": None, "name": "RK", "directory": "publish_RK"}])

