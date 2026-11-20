import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import bootstrap
bootstrap.configure()
from core import Source, SyncError
from program_sync import ProgramEngine, repository_release, compare_release
import tool_update

ROOT = Path(__file__).resolve().parents[1]


class RepositoryUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.install = self.base / "installed"
        self.install.mkdir()
        (self.install / "obsolete.py").write_bytes(b"old")
        (self.install / "debs").mkdir()
        (self.install / "debs/keep.deb").write_bytes(b"offline dependency")
        self.version = "2026.11.20.9"
        for name in tool_update.REQUIRED_FILES:
            path = self.repo / "aiot-workbench" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# fixture\n", encoding="utf-8")
        (self.repo / "aiot-workbench/version.py").write_text("VERSION = {!r}\n".format(self.version), encoding="utf-8")
        (self.repo / "aiot-workbench/workbench.py").write_text("print({!r})\n".format("AIoT Workbench " + self.version), encoding="utf-8")
        (self.repo / "publish_RK").mkdir()
        (self.repo / "publish_RK/demo.py").write_bytes(b"print('publish')\n")
        (self.repo / "aiot-workbench/release").mkdir()
        (self.repo / "aiot-workbench/release/big.zip").write_bytes(b"not needed")
        self.source = Source(local=self.repo, commit="f" * 40)
        self.settings = self.base / "settings.json"
        self.settings.write_text(json.dumps({"repo": "https://gitee.com/potper/odoiotassets"}), encoding="utf-8")

    def tree(self):
        nodes = []
        for path in self.repo.rglob("*"):
            name = path.relative_to(self.repo).as_posix()
            if path.is_dir():
                nodes.append({"path": name, "type": "tree", "mode": "040000"})
            else:
                raw = path.read_bytes()
                nodes.append({"path": name, "type": "blob", "mode": "100644", "size": len(raw),
                    "sha": hashlib.sha1("blob {}\0".format(len(raw)).encode() + raw).hexdigest()})
        return json.dumps({"tree": nodes}).encode()

    def release(self):
        with patch.object(Source, "fetch_bytes", return_value=self.tree()):
            return repository_release({}, source=self.source)

    def test_directory_discovery_shared_comparison_staging_and_commit(self):
        # Old private modules left in the remote folder cannot reintroduce duplicates.
        for base in (self.repo / "aiot-workbench", self.install):
            (base / "launcher").mkdir(exist_ok=True)
            (base / "launcher/core.py").write_bytes(b"# obsolete private core\n")
        release = self.release()
        self.assertEqual(release["version"], self.version)
        paths = {e["path"] for e in release["manifest"]["entries"]}
        self.assertIn("shared/core.py", paths)
        self.assertNotIn("launcher/core.py", paths)
        self.assertFalse(any("publish_RK" in p or p.startswith("release/") for p in paths))
        preview = compare_release(self.install, tool_update.update_state(self.install), release)
        self.assertIn(("删除", "obsolete.py"), preview["changes"])
        record = tool_update.prepare_online(self.install, release, "2026.11.20.2", None, lambda n: None)
        self.assertTrue(record["replace_program"])
        self.assertEqual((self.install / "obsolete.py").read_bytes(), b"old")
        state = tool_update.update_state(self.install)
        stage = state / record["stage"]
        self.assertFalse((stage / "obsolete.py").exists())
        self.assertFalse((stage / "launcher/core.py").exists())
        self.assertEqual((stage / "debs/keep.deb").read_bytes(), b"offline dependency")
        tool_update.commit_update(self.install)
        self.assertEqual(tool_update.package_version(self.install / "version.py"), self.version)
        self.assertEqual((state / record["backup"] / "obsolete.py").read_bytes(), b"old")

    def test_same_version_content_changes_are_detected_and_older_version_never_installed(self):
        release = self.release()
        with patch("program_sync.Source.remote", return_value=self.source), patch.object(Source, "fetch_bytes", return_value=self.tree()):
            found, newer = tool_update.check_repository(self.settings, self.install, self.version)
        self.assertTrue(newer)
        self.assertTrue(found["changes"])
        self.assertIsNone(tool_update.prepare_online(self.install, release, "2026.11.21.1", None, lambda n: None))
        with self.assertRaisesRegex(SyncError, "只能准备"):
            ProgramEngine(self.install).apply(release["manifest"], self.source)

    def test_truncated_tree_and_missing_required_files_cannot_replace_install(self):
        with patch.object(Source, "fetch_bytes", return_value=b'{"tree":[],"truncated":true}'):
            with self.assertRaisesRegex(SyncError, "不完整"):
                repository_release({}, source=self.source)
        (self.repo / "aiot-workbench/shared/core.py").unlink()
        release = self.release()
        with self.assertRaisesRegex(tool_update.UpdateError, "缺少完整"):
            tool_update.prepare_online(self.install, release, "2026.11.20.2", None, lambda n: None)
        self.assertEqual((self.install / "obsolete.py").read_bytes(), b"old")
        self.assertFalse((tool_update.update_state(self.install) / "pending.json").exists())

    def test_one_update_uses_the_same_repository_for_program_and_publish(self):
        from generate import generate
        from workbench_updates import update_all
        from program_sync import runtime_file
        # Existing installed runtime executes the resource worker while the new
        # workbench is staged, exactly as on the device.
        for source in ROOT.rglob("*"):
            relative = source.relative_to(ROOT)
            if source.is_file() and runtime_file(relative.as_posix()) and source.suffix == ".py":
                destination = self.install / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        target = self.base / "publish"
        target.mkdir()
        (target / "demo.py").write_bytes(b"old script")
        (target / "extra.json").write_bytes(b"obsolete")
        pub_source = self.base / "publish-source"
        pub_source.mkdir()
        (pub_source / "demo.py").write_bytes(b"print('updated')\n")
        generate(pub_source, self.repo, "rk", "RK", "1")
        self.settings.write_text(json.dumps({"publish_dir": str(target), "home_update_profile": "rk"}), encoding="utf-8")
        release = self.release()
        with patch("workbench_updates.subprocess.Popen", wraps=subprocess.Popen) as launch:
            result = update_all(self.install, self.settings, "2026.11.20.2", release=release)
        command = launch.call_args.args[0]
        pinned = json.loads(command[command.index("--source-json") + 1])
        self.assertEqual(pinned["commit"], release["commit"])
        self.assertEqual(pinned["local"], str(self.repo))
        self.assertFalse((target / "extra.json").exists())
        self.assertEqual((target / "demo.py").read_bytes(), b"print('updated')\n")
        self.assertTrue(result["program_record"]["replace_program"])
        self.assertTrue((self.install / "obsolete.py").exists())
        tool_update.recover_update(self.install)


class IndependentEntryTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Linux parent-process verification")
    def test_session_recognizes_workbench_host_with_explicit_publish_argument(self):
        import session_cli
        command = (sys.executable + "\0" + str(ROOT / "workbench.py") + "\0gui\0--publish-dir\0/tmp/publish\0").encode()
        actual_readlink = os.readlink
        def readlink(path, *args, **kwargs):
            if str(path) == "/proc/12345/exe":
                return sys.executable
            if str(path) == "/proc/12345/cwd":
                return str(ROOT)
            return actual_readlink(path, *args, **kwargs)
        with patch("session_cli.os.getppid", return_value=12345), \
             patch("session_cli.os.readlink", side_effect=readlink), \
             patch("pathlib.Path.read_bytes", return_value=command):
            self.assertEqual(session_cli.verified_parent(), (12345,))

    def test_backend_version_from_another_directory_without_pythonpath(self):
        from version import VERSION
        with tempfile.TemporaryDirectory() as directory:
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            for script in ("launcher/session_cli.py", "engineer/switcher.py", "workbench.py"):
                result = subprocess.run([sys.executable, "-I", str(ROOT / script), "--version"], cwd=directory,
                    env=environment, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(VERSION, result.stdout)

    def test_no_private_copies_of_shared_modules(self):
        for source in (ROOT / "shared").glob("*.py"):
            self.assertFalse((ROOT / "launcher" / source.name).exists(), source.name)
            self.assertFalse((ROOT / "engineer" / source.name).exists(), source.name)

    @unittest.skipUnless(sys.platform == "linux", "Linux shell session")
    def test_real_launcher_shell_check_without_pythonpath_or_gui(self):
        from launcher_install import render_launcher
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "publish"
            target.mkdir()
            app = target / "AIotApp"
            app.write_bytes(b"fixture, check only, never executed")
            app.chmod(0o755)
            settings = base / "settings.json"
            settings.write_text(json.dumps({"publish_dir": str(target)}), encoding="utf-8")
            wrapper = base / "launcher.sh"
            wrapper.write_text(render_launcher(ROOT / "launcher", settings_path=settings), encoding="utf-8")
            environment = dict(os.environ, XDG_CONFIG_HOME=str(base / "config"))
            environment.pop("PYTHONPATH", None)
            process = subprocess.Popen(["bash", str(wrapper), "--events-json", "--check"], cwd=base,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
            events = []
            for line in process.stdout:
                events.append(json.loads(line))
            self.assertEqual(process.wait(timeout=20), 0, process.stderr.read())
            self.assertEqual(events[-1]["event"], "ready")
            self.assertIsNone(events[-1]["data"]["error"])
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()
