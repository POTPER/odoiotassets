import json
import contextlib
import io
import os
from pathlib import Path
import queue
import signal
import shlex
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import launcher_runtime as runtime
import launcher_install as installer
from config_versions import CONFIG_NAMES
from core import Engine, SyncError


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(os.environ.get("PUBLISH_SWITCHER_TEST_TMP", str(Path(__file__).parent / ".tmp")))
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.target = self.base / "publish space"
        self.target.mkdir()
        self.source = self.target / "config" / runtime.VERSION
        self.source.mkdir(parents=True)
        self.old, self.new = {}, {}
        for name in CONFIG_NAMES:
            self.old[name] = b'[{"old":true}]'
            self.new[name] = ('\ufeff[ {"new": "' + name + '"} ]\r\n').encode("utf-8")
            (self.target / name).write_bytes(self.old[name])
            (self.source / name).write_bytes(self.new[name])
        self.app = self.target / "AIotApp"
        self.app.write_text("print('mock-aiot')\n", encoding="utf-8")
        self.app.chmod(0o755)
        self.script = self.target / "StartApp.sh"
        self.script.write_text("#!/bin/bash\n# --managed\n", encoding="utf-8")
        self.controller = runtime.SessionController(self.target, self.base / "logs", stable_seconds=0.15,
                                                    apply_config_enabled=True)
        self.addCleanup(self.cleanup_worker)
        self.command = patch("launcher_runtime.managed_command", return_value=[sys.executable, "-u", str(self.app)])
        self.command.start()
        self.addCleanup(self.command.stop)

    def cleanup_worker(self):
        self.controller.request_stop()
        if self.controller.thread:
            self.controller.thread.join(timeout=10)
            self.assertFalse(self.controller.thread.is_alive())

    def event(self, kind, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event, data = self.controller.events.get(timeout=0.1)
            except queue.Empty:
                continue
            if event == kind:
                return data
            if event == "finished" and kind != "finished":
                self.fail("unexpected finish: " + repr(data))
        self.fail("missing event " + kind)

    def active(self, expected):
        for name, raw in expected.items():
            self.assertEqual((self.target / name).read_bytes(), raw)

    def run_once(self):
        self.assertTrue(self.controller.start())
        result = self.event("finished")
        self.controller.thread.join(1)
        return result

    def test_apply_before_launch_exact_bytes_backup_and_unchanged_sources(self):
        self.app.write_text("from pathlib import Path\nprint(Path('TrainTaskInfo.json').read_bytes())\n", encoding="utf-8")
        result = self.run_once()
        self.assertIsNone(result["error"])
        self.assertEqual(result["returncode"], 0)
        self.active(self.new)
        for name in CONFIG_NAMES:
            self.assertEqual((self.source / name).read_bytes(), self.new[name])
        backup = next((Engine(self.target).state / "config-backups").iterdir())
        for name in CONFIG_NAMES:
            self.assertEqual((backup / name).read_bytes(), self.old[name])
        self.assertIn("TrainTaskInfo.json", Path(result["logfile"]).read_text(encoding="utf-8"))

    def test_initialize_checks_but_does_not_apply_or_launch(self):
        with patch("launcher_runtime.subprocess.Popen") as spawn:
            self.assertTrue(self.controller.initialize())
            result = self.event("ready")
        self.assertIsNone(result["error"])
        spawn.assert_not_called()
        self.active(self.old)

    def test_already_running_aiot_skips_recovery_replacement_and_second_spawn(self):
        with patch('launcher_runtime.find_running_aiot', return_value=[12345]), \
                patch('launcher_runtime.Engine', side_effect=AssertionError('must not recover or modify running installation')), \
                patch('launcher_runtime.subprocess.Popen') as spawn:
            result = self.run_once()
        self.assertIsNone(result['error'])
        self.assertEqual(result['already_running'], [12345])
        spawn.assert_not_called()
        self.active(self.old)

    def test_monitoring_external_aiot_keeps_operation_lock_free_and_stops_without_signals(self):
        self.controller = runtime.SessionController(self.target, self.base / 'logs', monitor_existing=True)
        with patch('launcher_runtime.find_running_aiot', return_value=[12345]), \
                patch('launcher_runtime.stop_owned_process') as stop:
            self.controller.initialize()
            self.assertEqual(self.event('external_running')['pids'], [12345])
            with Engine(self.target).lock():
                pass
            self.controller.request_stop()
            result = self.event('ready')
            self.controller.thread.join(2)
        self.assertIsNone(result['error'])
        self.assertTrue(result['stopped'])
        stop.assert_not_called()
        self.active(self.old)

    def test_monitor_finishes_after_external_process_exits(self):
        self.controller = runtime.SessionController(self.target, self.base / 'logs', monitor_existing=True)
        with patch('launcher_runtime.find_running_aiot', side_effect=[[12345], []]), \
                patch('launcher_runtime.subprocess.Popen') as spawn:
            self.controller.initialize()
            self.event('external_running')
            result = self.event('ready')
            self.controller.thread.join(2)
        self.assertIsNone(result['error'])
        spawn.assert_not_called()
        self.active(self.old)

    def test_explicit_external_stop_backend_works_while_managed_session_holds_operation_lock(self):
        import session_cli
        output = io.StringIO()
        with Engine(self.target).lock(), \
                patch('launcher_runtime.config_directory', return_value=self.base / 'user-config'), \
                patch('session_cli.load_settings', side_effect=AssertionError('stop must not apply settings')), \
                patch('running_aiot.stop_existing_aiot', return_value={'stopped_pids': [12345], 'remaining_pids': []}) as stop, \
                contextlib.redirect_stdout(output):
            code = session_cli.main(['--publish-dir', str(self.target), '--stop-existing', '--events-json'])
        self.assertEqual(code, 0)
        event = json.loads(output.getvalue())
        self.assertEqual(event['event'], 'finished')
        self.assertIsNone(event['data']['error'])
        self.assertEqual(event['data']['stopped_pids'], [12345])
        self.assertTrue(Path(event['data']['logfile']).is_file())
        self.assertEqual(stop.call_args.args[0], self.target.resolve())
        self.active(self.old)

    def test_external_stop_backend_reports_permission_failure_without_touching_config(self):
        import session_cli
        output = io.StringIO()
        with patch('launcher_runtime.config_directory', return_value=self.base / 'user-config'), \
                patch('running_aiot.stop_existing_aiot', side_effect=SyncError('没有权限停止')), \
                contextlib.redirect_stdout(output):
            code = session_cli.main(['--publish-dir', str(self.target), '--stop-existing', '--events-json'])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())['data']
        self.assertEqual(result['error'], '没有权限停止')
        self.assertIn('没有权限停止', Path(result['logfile']).read_text(encoding='utf-8'))
        self.active(self.old)

    def test_external_start_during_preflight_is_reported_as_running_without_replacement(self):
        with patch('launcher_runtime.find_running_aiot', side_effect=[[], [12345]]), \
                patch('launcher_runtime.Engine.preflight', side_effect=SyncError('publish 仍被程序使用')), \
                patch('launcher_runtime.subprocess.Popen') as spawn:
            result = self.run_once()
        self.assertIsNone(result['error'])
        self.assertEqual(result['already_running'], [12345])
        spawn.assert_not_called()
        self.active(self.old)

    def test_default_start_uses_existing_configuration_without_template(self):
        # A missing or broken competition bundle must not block the default flow.
        for name in CONFIG_NAMES:
            (self.source / name).unlink()
        self.source.rmdir()
        self.controller = runtime.SessionController(self.target, self.base / "logs", collection_enabled=False)
        self.app.write_text("from pathlib import Path\nassert Path('TrainTaskInfo.json').read_bytes() == b'[{\"old\":true}]'\n", encoding="utf-8")
        with patch("launcher_runtime.preview_version", side_effect=AssertionError("must not read template")), \
                patch("launcher_runtime.activate_version_locked", side_effect=AssertionError("must not copy config")):
            result = self.run_once()
        self.assertIsNone(result["error"])
        self.assertEqual(result["returncode"], 0)
        self.active(self.old)
        self.assertFalse((Engine(self.target).state / "config-backups").exists())

    def test_default_start_without_task_json_or_collection(self):
        for name in CONFIG_NAMES:
            (self.target / name).unlink()
        self.controller = runtime.SessionController(self.target, self.base / "logs")
        with patch("collection_config.prepare_overlay", side_effect=AssertionError("collection must stay off")):
            result = self.run_once()
        self.assertIsNone(result["error"])
        self.assertEqual(result["returncode"], 0)
        self.assertTrue(all(not (self.target / name).exists() for name in CONFIG_NAMES))
        self.assertFalse((Engine(self.target).state / "python-wrappers").exists())

    def test_aiot_process_does_not_inherit_the_launchers_desktop_registration(self):
        from desktop_identity import LAUNCH_METADATA
        self.app.write_text("import os\n"
                            "assert os.environ['LIBGL_ALWAYS_SOFTWARE'] == '1'\n"
                            "assert os.environ['AIOT_TEST_SESSION'] == 'preserved'\n"
                            "assert not any(key in os.environ for key in " + repr(LAUNCH_METADATA) + ")\n",
                            encoding="utf-8")
        environment = {name: 'launcher-metadata' for name in LAUNCH_METADATA}
        environment['AIOT_TEST_SESSION'] = 'preserved'
        with patch.dict(os.environ, environment):
            result = self.run_once()
        self.assertIsNone(result['error'])
        self.assertEqual(result['returncode'], 0)

    def test_running_holds_shared_lock_rejects_duplicates_and_stop_releases_it(self):
        self.app.write_text("import time\nprint('running', flush=True)\ntime.sleep(60)\n", encoding="utf-8")
        self.assertTrue(self.controller.start())
        self.event("started")
        self.event("stable")
        self.assertFalse(self.controller.start())
        with self.assertRaisesRegex(SyncError, "另一个"):
            Engine(self.target).activate_config_version(runtime.VERSION)
        self.controller.request_stop()
        result = self.event("finished")
        self.assertTrue(result["stopped"])
        self.assertIsNone(result["error"])
        Engine(self.target).activate_config_version(runtime.VERSION)
        self.assertTrue(self.controller.start())
        self.controller.request_stop()
        self.event("finished")

    def test_bad_json_missing_file_and_empty_app_do_not_apply_or_spawn(self):
        for bad in ("invalid-json", "missing-json", "empty-app"):
            with self.subTest(bad=bad):
                self.app.write_text("print('mock')\n", encoding="utf-8")
                (self.source / CONFIG_NAMES[0]).write_bytes(self.new[CONFIG_NAMES[0]])
                self.script.write_text("# --managed\n", encoding="utf-8")
                if bad == "invalid-json":
                    (self.source / CONFIG_NAMES[0]).write_bytes(b"{broken")
                elif bad == "missing-json":
                    (self.source / CONFIG_NAMES[0]).unlink()
                elif bad == "empty-app":
                    self.app.write_bytes(b"")
                else:
                    self.script.write_text("gnome-terminal\n", encoding="utf-8")
                with patch("launcher_runtime.subprocess.Popen") as spawn:
                    result = self.run_once()
                self.assertIsNotNone(result["error"])
                spawn.assert_not_called()
                self.active(self.old)

    def test_unreadable_app_prevents_changes(self):
        access = os.access
        with patch("launcher_runtime.os.access", side_effect=lambda p, mode: False if Path(p) == self.app else access(p, mode)), \
                patch("launcher_runtime.subprocess.Popen") as spawn:
            result = self.run_once()
        self.assertIn("无法读取", result["error"])
        spawn.assert_not_called()
        self.active(self.old)

    def test_replace_failure_rolls_back_and_does_not_spawn(self):
        replace = os.replace
        def fail(src, dst):
            if Path(src).parent.name.startswith("config-stage-") and Path(src).name == CONFIG_NAMES[1]:
                raise PermissionError("injected failure")
            return replace(src, dst)
        with patch("config_versions.os.replace", side_effect=fail), patch("launcher_runtime.subprocess.Popen") as spawn:
            result = self.run_once()
        self.assertIn("injected failure", result["error"])
        spawn.assert_not_called()
        self.active(self.old)

    def test_spawn_failure_keeps_applied_configuration_and_can_retry(self):
        with patch("launcher_runtime.subprocess.Popen", side_effect=OSError("injected exec failure")):
            result = self.run_once()
        self.assertIn("exec failure", result["error"])
        self.active(self.new)
        self.assertIsNone(self.run_once()["error"])

    def test_nonzero_and_large_output_are_saved_without_pipe_deadlock(self):
        self.app.write_text("import sys\nsys.stdout.write('x'*2000000)\nprint('\\nmock-failure', file=sys.stderr)\nsys.exit(7)\n", encoding="utf-8")
        result = self.run_once()
        self.assertEqual(result["returncode"], 7)
        self.assertIn("7", result["error"])
        logfile = Path(result["logfile"])
        self.assertGreater(logfile.stat().st_size, 2000000)
        self.assertIn("mock-failure", logfile.read_text(encoding="utf-8"))
        self.active(self.new)

    def test_stop_during_configuration_finishes_transaction_without_spawn(self):
        apply = runtime.activate_version_locked
        def stopping(*args, **kwargs):
            result = apply(*args, **kwargs)
            self.controller.request_stop()
            return result
        with patch("launcher_runtime.activate_version_locked", side_effect=stopping), patch("launcher_runtime.subprocess.Popen") as spawn:
            result = self.run_once()
        self.assertTrue(result["stopped"])
        spawn.assert_not_called()
        self.active(self.new)

    def test_group_stop_escalates_only_for_owned_session(self):
        process = Mock(pid=54321)
        alive = [True]
        sent = []
        def killpg(pid, sig):
            self.assertEqual(pid, process.pid)
            sent.append(sig)
            if sig == 9:
                alive[0] = False
            if sig == 0 and not alive[0]:
                raise ProcessLookupError()
        with patch.object(runtime.os, "name", "posix"), \
                patch.object(runtime.os, "killpg", side_effect=killpg, create=True), \
                patch.object(runtime, 'owned_group_alive', side_effect=lambda process: alive[0]), \
                patch.object(runtime.signal, "SIGKILL", 9, create=True):
            runtime.stop_owned_process(process, timeout=0.01)
        self.assertIn(signal.SIGTERM, sent)
        self.assertIn(9, sent)
        process.wait.assert_called_once_with(timeout=2)

    def test_managed_stop_retry_keeps_lock_and_waits_for_remaining_cleanup(self):
        self.app.write_text('import time\ntime.sleep(30)\n', encoding='utf-8')
        stop_owned = runtime.stop_owned_process
        engine = Engine(self.target)
        def stop_with_retry(process):
            if stop.call_count == 1:
                raise OSError('injected stop failure')
            stop_owned(process)

        with patch('launcher_runtime.stop_owned_process', side_effect=stop_with_retry) as stop, \
                patch('collection_config.recover_overlay', side_effect=[None, OSError('injected overlay cleanup failure'), None]):
            self.controller.start()
            try:
                self.event('started')
                self.controller.request_stop()
                self.assertIn('injected stop failure', self.event('stop_failed')['error'])
                with self.assertRaises(SyncError):
                    with engine.lock():
                        pass
                self.controller.request_stop()
                self.assertIn('injected overlay cleanup failure', self.event('stop_failed')['error'])
                with self.assertRaises(SyncError):
                    with engine.lock():
                        pass
                self.controller.request_stop()
                self.assertIsNone(self.event('finished')['error'])
                self.assertEqual(stop.call_count, 2)
            finally:
                self.controller.close_input()
                self.controller.thread.join(8)
        with engine.lock():
            self.active(self.new)

    def test_doctor_uses_saved_publish_without_repairing_or_creating_state(self):
        try:
            import tkinter
        except ImportError:
            self.skipTest("Tkinter unavailable in the headless Linux test environment")
        from aiot_launcher import main
        settings = self.base / 'settings.json'
        settings.write_bytes(b'broken json')
        settings.with_suffix('.json.bak').write_text(json.dumps({'publish_dir': str(self.target)}), encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch('tkinter.Tk', side_effect=RuntimeError('no display')):
            code = main(['--doctor', '--settings-file', str(settings)])
        self.assertEqual(code, 1)
        self.assertIn('no display', output.getvalue())
        self.assertIn(str(self.target), output.getvalue())
        self.assertEqual(settings.read_bytes(), b'broken json')
        self.assertFalse((self.base / ('.publish-switcher-' + self.target.name)).exists())

    @unittest.skipUnless(sys.platform == "linux", "Requires /proc and Linux sessions")
    def test_external_program_is_not_stopped_or_reconfigured(self):
        other = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"], cwd=self.target,
                                 start_new_session=True)
        self.addCleanup(lambda: runtime.stop_owned_process(other, timeout=0.2))
        result = self.run_once()
        self.assertIn("仍被程序使用", result["error"])
        self.assertIsNone(other.poll())
        self.active(self.old)

    @unittest.skipUnless(sys.platform == "linux", "Requires /proc and Linux sessions")
    def test_stop_cleans_child_in_same_group(self):
        self.app.write_text("import subprocess,sys,time\nfrom pathlib import Path\n"
                            "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
                            "Path('child.pid').write_text(str(p.pid))\ntime.sleep(60)\n", encoding="utf-8")
        self.controller.start()
        self.event("stable")
        pid = int((self.target / "child.pid").read_text())
        self.controller.request_stop()
        self.event("finished")
        state = Path("/proc") / str(pid) / "stat"
        self.assertTrue(not state.exists() or state.read_text().split(") ", 1)[1].startswith("Z"))

    def test_installer_backs_up_script_writes_settings_and_shortcuts(self):
        original = self.script.read_bytes()
        tool = Path(installer.__file__).resolve().parent
        result = installer.install(self.target, tool_dir=tool, config_dir=self.base / "config/aiot-launcher",
                                   applications=self.base / "apps", desktop_dir=self.base / "desktop",
                                   shortcut_dir=self.base / "当前目录 space")
        self.assertIsNone(result["backup"])
        self.assertEqual(Path(result["script"]), self.target.parent / "launcher.sh")
        self.assertEqual(self.script.read_bytes(), original)
        self.assertIn("session_cli.py", (self.target.parent / "launcher.sh").read_text(encoding="utf-8"))
        settings = runtime.load_settings(self.base / "config/aiot-launcher/settings.json")
        self.assertEqual(settings["publish_dir"], str(self.target))
        self.assertIs(settings["apply_config_enabled"], False)
        self.assertIs(settings["collection_enabled"], False)
        self.assertIs(settings["submission_enabled"], False)
        self.assertEqual(settings["submission_dir"], "")
        self.assertIn("Terminal=false", Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertIn("Name=2026金砖赛事\\n物联传感技术应用\n", Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertIn(installer.desktop_quote(tool / "desktop_bootstrap.py"), Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertIn("--settings-file " + installer.desktop_quote(self.base / "config/aiot-launcher/settings.json"),
                      Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertIn("Icon=" + (tool / "assets/icon.png").as_posix(), Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertIn("StartupWMClass=Aiotlauncher", Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertTrue((self.base / "desktop/aiot-workbench.desktop").is_file())
        local = Path(result["local_entry"])
        self.assertEqual(local, self.base / "当前目录 space/aiot-workbench.desktop")
        self.assertEqual(local.read_bytes(), Path(result["entry"]).read_bytes())
        if os.name == "posix":
            self.assertTrue(os.access(local, os.X_OK))
        self.active(self.old)
        settings["apply_config_enabled"] = True
        (self.base / "config/aiot-launcher/settings.json").write_text(json.dumps(settings), encoding="utf-8")
        installer.install(self.target, tool_dir=tool, config_dir=self.base / "config/aiot-launcher",
                          applications=self.base / "apps", shortcut_dir=local.parent)
        self.assertEqual(local.read_bytes(), Path(result["entry"]).read_bytes())
        self.assertIs(runtime.load_settings(self.base / "config/aiot-launcher/settings.json")["apply_config_enabled"], True)
        settings.update(apply_config_enabled=True, collection_enabled=True, custom="preserved")
        (self.base / "config/aiot-launcher/settings.json").write_text(json.dumps(settings), encoding="utf-8")
        installer.install(self.target, tool_dir=tool, config_dir=self.base / "config/aiot-launcher",
                          applications=self.base / "apps", basic=True)
        settings = runtime.load_settings(self.base / "config/aiot-launcher/settings.json")
        self.assertIs(settings["apply_config_enabled"], False)
        self.assertIs(settings["collection_enabled"], False)
        self.assertEqual(settings["custom"], "preserved")
        with Engine(self.target).lock(), self.assertRaises(SyncError):
            installer.install(self.target, config_dir=self.base / "config/aiot-launcher", applications=self.base / "apps")

    def test_installer_rejects_destinations_inside_publish(self):
        with self.assertRaisesRegex(SyncError, "publish 外"):
            installer.install(self.target, config_dir=self.target / "settings", applications=self.base / "apps")
        with self.assertRaisesRegex(SyncError, "publish 外"):
            installer.install(self.target, config_dir=self.base / "settings", applications=self.base / "apps",
                              shortcut_dir=self.target)

    def test_installer_uses_distinct_runtime_entrypoints_for_desktop_and_backend(self):
        aliases = {role: str(self.base / 'config/runtime' / name) for role, name in
                   {'desktop': 'aiot-desktop', 'gui': 'aiot-launcher', 'session': 'aiot-session'}.items()}
        with patch('launcher_install.install_interpreters', return_value=aliases):
            result = installer.install(self.target, config_dir=self.base / 'config', applications=self.base / 'apps')
        desktop = Path(result['entry']).read_text(encoding='utf-8')
        script = Path(result['script']).read_text(encoding='utf-8')
        self.assertIn('Exec=' + installer.desktop_quote(aliases['desktop']), desktop)
        self.assertIn(shlex.quote(aliases['session']), script)

    @unittest.skipUnless(sys.platform == "linux", "Requires Linux /proc and Bash exec")
    def test_bash_install_does_not_detect_its_own_shell_as_publish_user(self):
        # Available dependencies exercise the offline Bash -> installer handoff
        # without requesting sudo or requiring an offline-debs directory.
        tools = self.base / "bin"
        tools.mkdir()
        helpers = {
            "id": "#!/bin/sh\necho 1000\n",
            "python3": '#!/bin/sh\nif [ "$1" = "-c" ]; then exit 0; fi\nexec ' +
                       shlex.quote(sys.executable) + ' "$@"\n',
            "xdg-user-dir": "#!/bin/sh\nprintf '%s\\n' " + shlex.quote(str(self.base / "desktop")) + "\n",
            "gio": "#!/bin/sh\nexit 0\n",
            "pkexec": "#!/bin/sh\nexit 0\n",
            "sudo": "#!/bin/sh\nexit 99\n",
        }
        for name, content in helpers.items():
            helper = tools / name
            helper.write_text(content, encoding="utf-8")
            helper.chmod(0o755)
        current = self.base / "当前目录"
        current.mkdir()
        settings_path = self.base / "config/aiot-workbench/settings.json"
        from core import atomic_json
        atomic_json(settings_path, {"publish_dir": str(self.target), "collection_enabled": True,
                                    "apply_config_enabled": True})
        env = dict(os.environ, PATH=str(tools) + os.pathsep + os.defpath,
                   HOME=str(self.base / "home"), XDG_CONFIG_HOME=str(self.base / "config"),
                   XDG_DATA_HOME=str(self.base / "data"))
        result = subprocess.run(["/bin/bash", str(Path(installer.__file__).resolve().parents[1] / "install.sh"),
                                 str(self.target), "--offline"], cwd=current, env=env,
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((current / "aiot-workbench.desktop").is_file())
        settings = runtime.load_settings(settings_path)
        self.assertIs(settings["collection_enabled"], True)
        self.assertIs(settings["apply_config_enabled"], True)
        self.active(self.old)

    def test_settings_fallback_and_invalid_deployment_configuration(self):
        path = self.base / "config/aiot-launcher/settings.json"
        self.assertEqual(runtime.load_settings(path)["publish_dir"], runtime.DEFAULT_PUBLISH)
        switcher = path.parent.parent / "publish-switcher/settings.json"
        switcher.parent.mkdir(parents=True)
        switcher.write_text(json.dumps({"target": str(self.target)}), encoding="utf-8")
        self.assertEqual(runtime.load_settings(path)["publish_dir"], str(self.target))
        path.parent.mkdir()
        path.write_text('{"publish_dir": ""}', encoding="utf-8")
        with self.assertRaises(SyncError):
            runtime.load_settings(path)

    def test_desktop_exec_quotes_shell_metacharacters_and_percent(self):
        quoted = installer.desktop_quote('folder $cash `cmd` %f "quote"')
        self.assertIn('\\$', quoted)
        self.assertIn('\\`', quoted)
        self.assertIn('%%f', quoted)
        self.assertIn('\\"', quoted)
        with self.assertRaises(SyncError):
            installer.desktop_quote("bad\npath")

    def test_deployed_and_packaged_start_scripts_are_identical(self):
        root = Path(__file__).resolve().parents[2]
        source = root / "项目结构/linux-arm64/publish/StartApp.sh"
        if source.exists():
            template = Path(__file__).resolve().parents[1] / "launcher_assets/StartApp.sh"
            self.assertEqual(source.read_bytes(), template.read_bytes())


if __name__ == "__main__":
    unittest.main()
