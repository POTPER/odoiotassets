import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
import urllib.error
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from install import install_online as installer


class OnlineInstallTests(unittest.TestCase):
    def setUp(self):
        root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.target = self.base / "中文 install"
        self.output = io.StringIO()
        context = redirect_stdout(self.output)
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)

    def package(self, extra=()):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name in ("switcher.py", "install.sh", "version.py", "app.py", "core.py", "tool_update.py"):
                archive.writestr("publish-switcher/" + name,
                                 'VERSION = "2026.11.20.6"\n' if name == "version.py" else "# fixture\n")
            for name, payload in extra:
                archive.writestr(name, payload)
        data = stream.getvalue()
        release = {"schema_version": 1, "product": "publish-switcher", "version": "2026.11.20.6",
                   "url": "https://example.org/publish-switcher.zip",
                   "package_file": "publish-switcher.zip", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        return data, release

    def test_primary_forbidden_falls_back_validates_and_invokes_cli_installer(self):
        data, release = self.package()

        def response(url):
            if url.startswith(installer.SOURCES[0]):
                raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
            return io.BytesIO(json.dumps(release).encode() if url.endswith(".json") else data)

        with patch.object(installer, "request", side_effect=response), patch("install.install_online.subprocess.run") as run:
            installer.install(self.target, cli=True)
        self.assertTrue((self.target / "switcher.py").is_file())
        self.assertEqual(run.call_args.args[0], ["bash", str(self.target / "install.sh"), "--cli"])
        self.assertEqual(run.call_args.kwargs["cwd"], str(self.target))
        self.assertIn("2026.11.20.6", self.output.getvalue())

    def test_wrong_hash_on_both_sources_never_creates_destination(self):
        data, release = self.package()
        release["sha256"] = "0" * 64
        with patch.object(installer, "request", side_effect=lambda url: io.BytesIO(json.dumps(release).encode() if url.endswith(".json") else data)):
            with self.assertRaisesRegex(RuntimeError, "两个仓库均失败"):
                installer.install(self.target)
        self.assertFalse(self.target.exists())

    def test_existing_installation_is_never_read_or_overwritten(self):
        self.target.mkdir()
        original = self.target / "user.py"
        original.write_bytes(b"keep")
        with patch.object(installer, "request") as request:
            with self.assertRaisesRegex(ValueError, "目录已存在"):
                installer.install(self.target)
        request.assert_not_called()
        self.assertEqual(original.read_bytes(), b"keep")

    def test_unsafe_archive_paths_and_links_rejected_before_extracting(self):
        link = zipfile.ZipInfo("publish-switcher/link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        backslash = zipfile.ZipInfo("placeholder")
        backslash.filename = "publish-switcher/a\\b"
        for name in ("publish-switcher/../../escape", "/publish-switcher/escape", backslash, link):
            data, release = self.package([(name, "unsafe")])
            package = self.base / "package.zip"
            package.write_bytes(data)
            with self.assertRaisesRegex(ValueError, "无效路径"):
                installer.extract(package, self.target)
            self.assertFalse(self.target.exists())
        self.assertFalse((self.base / "escape").exists())

    def test_dependency_install_failure_preserves_downloaded_tool_for_retry(self):
        data, release = self.package()
        with patch.object(installer, "request", side_effect=lambda url: io.BytesIO(json.dumps(release).encode() if url.endswith(".json") else data)), \
                patch("install.install_online.subprocess.run", side_effect=OSError("apt unavailable")):
            with self.assertRaisesRegex(OSError, "apt unavailable"):
                installer.install(self.target)
        self.assertTrue((self.target / "install.sh").is_file())

    def test_invalid_release_is_rejected_before_package_download(self):
        with patch.object(installer, "request", return_value=io.BytesIO(b'{"schema_version":1}')) as request:
            with self.assertRaisesRegex(ValueError, "发布信息"):
                installer.download(installer.SOURCES[0], self.base / "package.zip")
        request.assert_called_once()

    def test_default_destination_follows_installer_location_not_terminal_cwd(self):
        script = self.base / "音乐" / "install_online.py"
        script.parent.mkdir()
        script.write_text("# fixture\n", encoding="utf-8")
        elsewhere = self.base / "unrelated-terminal-directory"
        elsewhere.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(elsewhere)
            with patch.object(installer, "__file__", str(script)), patch.object(sys, "platform", "linux"), \
                    patch.object(sys, "argv", [str(script)]), patch.object(installer, "install") as install:
                installer.main()
            install.assert_called_once_with(str(script.parent.resolve() / "publish-switcher"), False)
        finally:
            os.chdir(previous)

    def test_explicit_directory_still_overrides_script_location(self):
        custom = str(self.base / "custom-tool-location")
        with patch.object(sys, "platform", "linux"), \
                patch.object(sys, "argv", ["install_online.py", "--directory", custom, "--cli"]), \
                patch.object(installer, "install") as install:
            installer.main()
        install.assert_called_once_with(custom, True)
