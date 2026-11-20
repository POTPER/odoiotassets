import hashlib
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import Engine, Source, SyncError
from repository import (DEFAULT_REPOSITORY, DEFAULT_PROFILES, LEGACY_DEFAULT_REPOSITORY,
                        directory_manifest, remote_profiles, repository_from_settings)
import test_sync


class GiteeTests(unittest.TestCase):
    setUp = test_sync.SyncTests.setUp

    def test_default_and_settings_migration(self):
        self.assertEqual(DEFAULT_REPOSITORY, "https://gitee.com/potper/odoiotassets")
        self.assertEqual(repository_from_settings({}), DEFAULT_REPOSITORY)
        self.assertEqual(repository_from_settings({"repo": LEGACY_DEFAULT_REPOSITORY}), DEFAULT_REPOSITORY)
        self.assertEqual(repository_from_settings({"repo": "https://github.com/custom/repo"}), "https://github.com/custom/repo")
        self.assertEqual(repository_from_settings({"repo": LEGACY_DEFAULT_REPOSITORY, "repository_default_version": 2}), LEGACY_DEFAULT_REPOSITORY)

    def test_gitee_branch_resolution_and_pinned_url(self):
        data = [b'{"default_branch":"main"}', json.dumps({"name": "main", "commit": {"sha": "a" * 40}}).encode()]
        with patch.object(Source, "fetch_bytes", side_effect=data) as fetch:
            source = Source.remote(DEFAULT_REPOSITORY)
        self.assertEqual(source.provider, "gitee")
        self.assertTrue(fetch.call_args[0][0].endswith("/branches/main"))
        self.assertEqual(source.url("publish_RK/中文.py"), "https://gitee.com/potper/odoiotassets/raw/" + "a" * 40 + "/publish_RK/%E4%B8%AD%E6%96%87.py")
        self.assertIn("gitee.com/api/v5/repos/potper/odoiotassets/git/trees/", source.tree_url())
        self.assertEqual(Source(**source.descriptor()).provider, "gitee")

    def test_legacy_cached_source_remains_github(self):
        source = Source(**{"owner": "example", "repo": "repo", "commit": "a" * 40, "local": None})
        self.assertEqual(source.provider, "github")
        self.assertTrue(source.url("file.py").startswith("https://raw.githubusercontent.com/"))

    def test_reject_wrong_gitee_branch(self):
        with patch.object(Source, "fetch_bytes", return_value=b'{"name":"other","commit":{"sha":"a"}}'):
            with self.assertRaises(SyncError):
                Source.remote(DEFAULT_REPOSITORY, "main")

    def test_gitee_discovery_apply_and_offline_cache(self):
        self.repo.mkdir()
        (self.repo / "publish_RK").mkdir()
        payload = b'[{"TrainTaskId":24}]'
        (self.repo / "publish_RK/TrainTaskInfo.json").write_bytes(payload)
        nodes = [{"path": "publish_RK", "type": "tree", "mode": "040000"},
                 {"path": "publish_RK/TrainTaskInfo.json", "type": "blob", "mode": "100644", "size": len(payload),
                  "sha": hashlib.sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()}]
        source = Source(local=self.repo, owner="potper", repo="odoiotassets", commit="a" * 40, provider="gitee")
        missing = urllib.error.HTTPError("url", 404, "missing", {}, None)
        with patch.object(source, "metadata", side_effect=missing), patch.object(source, "fetch_bytes", return_value=json.dumps({"tree": nodes, "truncated": False}).encode()) as fetch:
            items = remote_profiles(source, DEFAULT_PROFILES)
            self.assertIn("gitee.com/api/v5", fetch.call_args[0][0])
        manifest = directory_manifest(source, items[0]["directory_preset"], nodes)
        engine = Engine(self.target)
        engine.apply(manifest, source)
        self.assertEqual((self.target / "TrainTaskInfo.json").read_bytes(), payload)
        cached = engine.profiles()[0]
        self.assertEqual(cached["source"]["provider"], "gitee")
        restored_source = Source(**cached["source"])
        with patch.object(restored_source, "download", side_effect=AssertionError("must reuse")):
            engine.apply(cached["manifest"], restored_source)
