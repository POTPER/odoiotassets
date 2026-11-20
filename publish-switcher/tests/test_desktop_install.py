"""Exercise desktop installation in an isolated XDG home, without apt or sudo."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


class DesktopInstallTests(unittest.TestCase):
    def run_installer(self, source, directory, data, home, lookup=None):
        installer = (source / "install.sh").read_text(encoding="utf-8")
        code = installer.split('<<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
        # Only isolated filesystem writes; never invoke the real user's XDG/GIO services.
        wrapper = ("import pathlib, os, shutil, subprocess\n"
                   "pathlib.Path.home = classmethod(lambda cls: pathlib.Path(os.environ['HOME']))\n")
        if lookup is None:
            wrapper += "shutil.which = lambda name: None\n"
        else:
            wrapper += ("shutil.which = lambda name: '/mock/xdg-user-dir' if name == 'xdg-user-dir' else None\n"
                        "subprocess.run = lambda *args, **kw: subprocess.CompletedProcess(args[0], 0, " +
                        repr(str(lookup) + "\n") + ", '')\n")
        env = dict(os.environ, XDG_DATA_HOME=str(data), XDG_CONFIG_HOME=str(home / '.config'),
                   HOME=str(home), USERPROFILE=str(home))
        result = subprocess.run([sys.executable, "-c", wrapper + code, str(directory)], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
        return result

    def test_installs_icons_and_relocates_shortcut_in_isolated_home(self):
        source = Path(__file__).resolve().parents[1]
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            base = Path(temporary).resolve()
            data = base / "isolated data"
            home = base / "home"
            desktop_folder = home / "桌面"
            desktop_folder.mkdir(parents=True)
            shortcut = desktop_folder / 'publish-switcher.desktop'
            shortcut.write_text('old installation', encoding='utf-8')
            unrelated = desktop_folder / 'AIOT.desktop'
            unrelated.write_text('unrelated app', encoding='utf-8')
            tool = base / "中文 工具"
            shutil.copytree(source / "icons", tool / "icons")
            for directory in (tool, base / "新版 工具"):
                if directory != tool:
                    shutil.copytree(tool, directory)
                self.run_installer(source, directory, data, home)
                desktop = (data / "applications/publish-switcher.desktop").read_text(encoding="utf-8")
                icon_path = data / "icons/hicolor/256x256/apps/publish-switcher.png"
                self.assertIn("Icon=" + str(icon_path).replace("\\", "\\\\") + "\n", desktop)
                self.assertIn("StartupWMClass=PublishSwitcher\n", desktop)
                self.assertIn(str(directory / "switcher.py").replace("\\", "\\\\"), desktop)
                self.assertIn("Path=" + str(directory).replace("\\", "\\\\") + "\n", desktop)
                self.assertEqual(shortcut.read_text(encoding='utf-8'), desktop)
                self.assertEqual(unrelated.read_text(encoding='utf-8'), 'unrelated app')
                if os.name != 'nt':
                    self.assertEqual(shortcut.stat().st_mode & 0o777, 0o755)
                for icon in (source / "icons").glob("*.png"):
                    size = icon.stem.rsplit("-", 1)[1]
                    installed = data / "icons/hicolor" / ("{0}x{0}/apps/publish-switcher.png".format(size))
                    self.assertEqual(installed.read_bytes(), icon.read_bytes())
                self.assertEqual((data / "icons/hicolor/scalable/apps/publish-switcher.svg").read_bytes(),
                                 (source / "icons/publish-switcher.svg").read_bytes())

    def test_custom_xdg_desktop_and_disabled_desktop(self):
        source = Path(__file__).resolve().parents[1]
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as temporary:
            base = Path(temporary).resolve()
            home = base / 'home'
            fallback = home / 'Desktop'
            fallback.mkdir(parents=True)
            custom = base / '自定义 桌面'
            custom.mkdir()
            data = base / 'data'
            self.run_installer(source, source, data, home, lookup=custom)
            self.assertTrue((custom / 'publish-switcher.desktop').is_file())
            self.assertFalse((fallback / 'publish-switcher.desktop').exists())
            # Disabled XDG desktop must not create a launcher in HOME or fallback.
            self.run_installer(source, source, data, home, lookup=home)
            self.assertFalse((home / 'publish-switcher.desktop').exists())
            self.assertFalse((fallback / 'publish-switcher.desktop').exists())

    def test_update_aware_desktop_uses_bootstrap_outside_tool_directory(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            tool = base / "switcher"
            shutil.copytree(source / "icons", tool / "icons")
            shutil.copyfile(source / "tool_update.py", tool / "tool_update.py")
            home = base / "home"
            home.mkdir()
            data = base / "data"
            self.run_installer(source, tool, data, home)
            content = (data / "applications/publish-switcher.desktop").read_text(encoding="utf-8")
            self.assertIn("--launch", content)
            bootstrap = base / ".switcher-updater/bootstrap.py"
            self.assertEqual(bootstrap.read_bytes(), (source / "tool_update.py").read_bytes())
            self.assertIn(str(bootstrap).replace("\\", "\\\\"), content)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Bash")
    def test_offline_cli_and_missing_tkinter_never_call_system_apt(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            for name in ("apt-get", "sudo"):
                command = base / name
                command.write_text("#!/bin/sh\necho apt-was-called >&2\nexit 77\n", encoding="utf-8")
                command.chmod(0o755)
            python = base / "python3"
            python.write_text("#!/bin/sh\ncase \"$2\" in *tkinter*) exit 1;; esac\nexec "
                              + shlex.quote(sys.executable) + ' "$@"\n', encoding="utf-8")
            python.chmod(0o755)
            env = dict(os.environ, PATH=str(base) + os.pathsep + os.environ["PATH"])
            command = ["bash", str(source / "install.sh"), "--offline", "--deb-dir", str(base / "missing")]
            cli = subprocess.run(command + ["--cli"], env=env, capture_output=True, text=True)
            self.assertEqual(cli.returncode, 0, cli.stderr)
            gui = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertNotEqual(gui.returncode, 0)
            self.assertIn("缺少离线依赖（python3-tk）", gui.stderr)
            self.assertNotIn("apt-was-called", cli.stderr + gui.stderr)
            python.write_text(python.read_text(encoding="utf-8").replace("*tkinter*) exit 1", "*tkinter*) exit 0"),
                              encoding="utf-8")
            (base / "home").mkdir()
            env.update(HOME=str(base / "home"), XDG_CONFIG_HOME=str(base / "home/.config"),
                       XDG_DATA_HOME=str(base / "data"))
            gui = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(gui.returncode, 0, gui.stderr)
            self.assertNotIn("apt-was-called", gui.stderr)
            self.assertTrue((base / "data/applications/publish-switcher.desktop").is_file())

    @unittest.skipUnless(sys.platform.startswith("linux") and shutil.which("dpkg-deb") and shutil.which("apt-get"),
                         "requires Ubuntu/Debian package tools")
    def test_local_apt_resolves_transitive_dependency_without_external_sources(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            packages = base / "local debs"
            packages.mkdir()
            def make_deb(name, dependency=None):
                control = base / name / "DEBIAN"
                control.mkdir(parents=True)
                fields = ("Package: {}\nVersion: 1.0\nArchitecture: all\nMaintainer: Test <test@example.org>\n"
                          "Description: Publish Switcher offline fixture\n").format(name)
                if dependency:
                    fields += "Depends: {}\n".format(dependency)
                (control / "control").write_text(fields, encoding="utf-8")
                destination = packages / (name + ".deb")
                subprocess.run(["dpkg-deb", "--build", str(control.parent), str(destination)], check=True,
                               capture_output=True)
                return destination
            main_package = "publish-switcher-test-app"
            dependency = make_deb("publish-switcher-test-dependency")
            make_deb(main_package, "publish-switcher-test-dependency")
            shim_dir = base / "bin"
            shim_dir.mkdir()
            apt = shim_dir / "apt-get"
            apt.write_text(
                '#!/bin/sh\nset -eu\n'
                'source_file="${APT_CONFIG%/*}/sources.list"\n'
                'grep -Eq \'^deb \\[trusted=yes\\] file:/tmp/publish-switcher-debs\\.[[:alnum:]]+/repo \\./$\' "$source_file"\n'
                'test "$(wc -l < "$source_file")" -eq 1\n'
                'if [ "$1" = "-y" ]; then\n'
                '  echo local-install-verified\n'
                '  shift\n'
                '  archives="${APT_CONFIG%/*}/archives"\n'
                '  mkdir -p "$archives/partial"\n'
                '  set -- -y --download-only -o Debug::NoLocking=1 -o "Dir::Cache::archives=$archives" "$@"\n'
                'fi\n'
                'exec ' + shlex.quote(shutil.which("apt-get")) + ' "$@"\n', encoding="utf-8")
            apt.chmod(0o755)
            sudo = shim_dir / "sudo"
            sudo.write_text('#!/bin/sh\nexec "$@"\n', encoding="utf-8")
            sudo.chmod(0o755)
            env = dict(os.environ, PATH=str(shim_dir) + os.pathsep + os.environ["PATH"])
            command = ["bash", str(source / "install_offline_debs.sh"), str(packages), main_package]
            marker = packages / "PLATFORM"
            marker.write_text("ubuntu 0.0 arm64\n", encoding="utf-8")
            incompatible = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(incompatible.returncode, 0)
            self.assertIn("请用 --deb-dir 指定匹配的依赖目录", incompatible.stderr)
            self.assertNotIn("local-install-verified", incompatible.stdout)
            marker.unlink()
            complete = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(complete.returncode, 0, complete.stdout + complete.stderr)
            self.assertIn("local-install-verified", complete.stdout)
            self.assertIn("Inst publish-switcher-test-dependency", complete.stdout)
            dependency.unlink()
            incomplete = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(incomplete.returncode, 0)
            self.assertIn("本地包无法满足依赖", incomplete.stderr)
            self.assertNotIn("local-install-verified", incomplete.stdout)
