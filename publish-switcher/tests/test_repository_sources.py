import json
import sys
import tempfile
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.packaging.legacy.core import Source, SyncError, Cancelled
from publish_switcher.repositories.catalog import DEFAULT_PROFILES, DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY
from publish_switcher.repositories.discovery import candidates, discover, normalize
from publish_switcher.updates import bootstrap as tool_update


class GitLabTests(unittest.TestCase):
    def test_jihu_subgroups_default_branch_and_cached_descriptor(self):
        replies = [b'{"default_branch":"develop"}', json.dumps({"name": "develop", "commit": {"id": "a" * 40}}).encode()]
        with patch.object(Source, "fetch_bytes", side_effect=replies) as fetch:
            source = Source.remote("https://jihulab.com/group/subgroup/project.git")
        self.assertEqual(source.provider, "gitlab")
        self.assertIn("group%2Fsubgroup%2Fproject", fetch.call_args_list[0].args[0])
        self.assertEqual(Source(**source.descriptor()).url("IoT/字体.ttf"), source.url("IoT/字体.ttf"))
        self.assertIn("ref=" + "a" * 40, source.url("IoT/demo.py"))
        self.assertIn("/repository/files/IoT%2F", source.url("IoT/demo.py"))

    def test_custom_gitlab_host_and_slash_branch(self):
        with patch.object(Source, "fetch_bytes", return_value=json.dumps({"name": "feature/demo", "commit": {"id": "b" * 40}}).encode()) as fetch:
            source = Source.remote("https://git.example.org/team/project", "feature/demo")
        self.assertIn("/branches/feature%2Fdemo", fetch.call_args.args[0])
        self.assertEqual(source.base_url, "https://git.example.org")

    def test_tree_pagination_and_head_sizes_without_downloading_blobs(self):
        source = Source(owner="group", repo="project", commit="a" * 40, provider="gitlab")
        page1 = [{"path": "dir{}".format(i), "type": "tree", "id": "a" * 40, "mode": "040000"} for i in range(100)]
        page2 = [{"path": "dir0/demo.py", "type": "blob", "id": "b" * 40, "mode": "100644"}]
        with patch.object(source, "fetch_bytes", side_effect=[json.dumps(page1).encode(), json.dumps(page2).encode(), b'[]']) as fetch, \
             patch.object(source, "head", return_value={"x-gitlab-size": "900000000", "x-gitlab-blob-id": "b" * 40}) as head:
            result = source.tree()
        self.assertEqual(len(result["tree"]), 101)
        self.assertEqual(result["tree"][-1]["size"], 900000000)
        self.assertIn("page=2", fetch.call_args_list[1].args[0])
        self.assertIn("page=3", fetch.call_args.args[0])
        self.assertIn("ref=" + "a" * 40, head.call_args.args[0])
        self.assertFalse(result["truncated"])

    def test_incomplete_or_inconsistent_tree_is_rejected(self):
        source = Source(owner="group", repo="project", commit="a" * 40, provider="gitlab")
        page = [{"path": "dir{}".format(i), "type": "tree", "id": "a" * 40, "mode": "040000"} for i in range(100)]
        with patch.object(source, "fetch_bytes", return_value=json.dumps(page).encode()):
            with self.assertRaisesRegex(SyncError, "重复"):
                source.tree()
        with patch.object(source, "fetch_bytes", return_value=b'[{"path":"x.py","type":"blob","id":"a","mode":"100644"}]'), \
             patch.object(source, "head", return_value={"x-gitlab-size": "1", "x-gitlab-blob-id": "different"}):
            with self.assertRaisesRegex(SyncError, "不一致"):
                source.tree()

    def test_gitlab_native_manifest_sync_and_offline_descriptor(self):
        import hashlib
        from tools.packaging.legacy.core import Engine
        from publish_switcher.repositories.catalog import remote_profiles, directory_manifest
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            remote = base / "repo"
            (remote / "publish_RK").mkdir(parents=True)
            payload = b"print('gitlab')\n"
            (remote / "publish_RK/demo.py").write_bytes(payload)
            sha = hashlib.sha1("blob {}\0".format(len(payload)).encode() + payload).hexdigest()
            source = Source(local=remote, owner="group", repo="project", commit="a" * 40, provider="gitlab", base_url="https://jihulab.com")
            page = [{"path": "publish_RK", "type": "tree", "mode": "040000", "id": "c" * 40},
                    {"path": "publish_RK/demo.py", "type": "blob", "mode": "100644", "id": sha}]
            with patch.object(source, "metadata", side_effect=urllib.error.HTTPError("catalog", 404, "missing", {}, None)), \
                 patch.object(source, "fetch_bytes", side_effect=[json.dumps(page).encode(), b'[]']), \
                 patch.object(source, "head", return_value={"x-gitlab-size": str(len(payload)), "x-gitlab-blob-id": sha}):
                items = remote_profiles(source, DEFAULT_PROFILES)
            manifest = directory_manifest(source, items[0]["directory_preset"], items[0]["git_tree"])
            target = base / "publish"
            target.mkdir()
            engine = Engine(target)
            engine.apply(manifest, source)
            self.assertEqual((target / "demo.py").read_bytes(), payload)
            cached = Source(**engine.profiles()[0]["source"])
            self.assertEqual(cached.base_url, "https://jihulab.com")
            with patch.object(cached, "download", side_effect=AssertionError("must reuse")):
                self.assertTrue(engine.apply(manifest, cached)["unchanged"])
class RepositoryChainTests(unittest.TestCase):
    def test_known_defaults_and_project_url_validation(self):
        values = candidates({})
        self.assertEqual([value["url"] for value in values], [DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY])
        self.assertEqual(len(candidates({}, "https://gitlab.com/user/project", explicit=True)), 1)
        promoted = candidates({"repository_sources": values}, LEGACY_DEFAULT_REPOSITORY)
        self.assertEqual(promoted[0]["url"], LEGACY_DEFAULT_REPOSITORY)
        self.assertEqual(len(promoted), 2)
        self.assertEqual(candidates({"repository_sources": list(reversed(values))})[0]["url"], LEGACY_DEFAULT_REPOSITORY)
        with self.assertRaises(SyncError):
            normalize(["https://jihulab.com/"])
        with self.assertRaises(SyncError):
            normalize(["https://user:password@gitlab.com/group/project"])

    def test_403_then_next_repository_and_no_extra_queries_after_success(self):
        values = normalize([DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY, "https://jihulab.com/group/project"])
        source = Source(owner="POTPER", repo="odoiotassets", commit="b" * 40)
        items = [{"source": source, "profile": {"id": "rk", "version": "1"}}]
        with patch.object(Source, "remote", side_effect=[urllib.error.HTTPError("api", 403, "Forbidden", {}, None), source]) as connect, \
             patch("publish_switcher.repositories.discovery.remote_profiles", return_value=items):
            actual = discover(values, DEFAULT_PROFILES)
        self.assertIs(actual, items)
        self.assertEqual(connect.call_count, 2)
        self.assertEqual(connect.call_args.args[0], LEGACY_DEFAULT_REPOSITORY)
        self.assertEqual(actual[0]["source"].commit, "b" * 40)

    def test_catalog_failure_and_missing_profile_move_to_next_candidate(self):
        values = normalize([DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY])
        a, b = Source(commit="a" * 40), Source(commit="b" * 40)
        items = [{"source": b, "profile": {"id": "rk", "version": "2"}}]
        with patch.object(Source, "remote", side_effect=[a, b]), patch("publish_switcher.repositories.discovery.remote_profiles", side_effect=[ValueError("invalid catalog"), items]):
            self.assertEqual(discover(values, DEFAULT_PROFILES, profile="rk")[0]["source"].commit, "b" * 40)
        with patch.object(Source, "remote", side_effect=Cancelled("cancel")) as connect:
            with self.assertRaises(Cancelled):
                discover(values, DEFAULT_PROFILES)
        self.assertEqual(connect.call_count, 1)

    def test_every_failure_is_reported_and_all_results_checks_every_entry(self):
        values = normalize([DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY])
        with patch.object(Source, "remote", side_effect=SyncError("unreachable")):
            with self.assertRaises(SyncError) as failure:
                discover(values, DEFAULT_PROFILES)
        self.assertIn(DEFAULT_REPOSITORY, str(failure.exception))
        self.assertIn(LEGACY_DEFAULT_REPOSITORY, str(failure.exception))
        with patch.object(Source, "remote", side_effect=SyncError("unreachable")):
            results = discover(values, DEFAULT_PROFILES, all_results=True)
        self.assertEqual([row["status"] for row in results], ["失败", "失败"])

    def test_program_metadata_tries_same_folder_on_next_mirror(self):
        values = normalize([DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY])
        release = {"schema_version": 1, "product": "publish-switcher", "version": "2026.11.20.5",
                   "url": "https://example.org/file.zip", "size": 1, "sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory) / "switcher"
            install.mkdir()
            source = Source()
            with patch("publish_switcher.updates.release.remote_file", side_effect=[urllib.error.HTTPError("raw", 403, "Forbidden", {}, None), (source, "metadata")]) as locate, \
                 patch.object(source, "metadata", return_value=json.dumps(release).encode()):
                result, newer = tool_update.check_release(tool_update.DEFAULT_UPDATE_URL, install, "2026.11.20.4", repositories=values)
            self.assertTrue(newer)
            self.assertEqual(result["version"], "2026.11.20.5")
            self.assertIn("raw.githubusercontent.com/POTPER/odoiotassets/main/publish-switcher/release/", locate.call_args.args[0])
        self.assertEqual(tool_update.mirror_locations("https://external.example/update.json", values), ["https://external.example/update.json"])


if __name__ == "__main__":
    unittest.main()
