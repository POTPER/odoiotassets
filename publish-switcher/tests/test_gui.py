"""Hidden Tk smoke tests; never load the user's actual settings or publish."""
import sys
import time
import tempfile
try:
    import tkinter as tk
except ImportError:
    tk = None
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if tk is not None:
    import app
from core import Source
from core import Engine


@unittest.skipIf(tk is None, "Tkinter is not installed")
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"没有可用的图形桌面：{exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        from tkinter import font
        original = font.nametofont
        # Exact CPython 3.8.10 signature: no extra positional OR keyword arguments.
        def python38_nametofont(name):
            return original(name)
        with patch.object(app, "CONFIG", Path(__file__).parent / "nonexistent-settings.json"), \
                patch("tkinter.font.nametofont", side_effect=python38_nametofont):
            self.ui = app.Application(self.root)

    def wait_job(self):
        limit = time.monotonic() + 5
        while self.ui.busy and time.monotonic() < limit:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.ui.busy, "UI worker did not finish")

    def test_window_and_sidebar_keep_bundled_icons_alive(self):
        import gc
        self.assertEqual(set(self.ui.icons), {16, 32, 48, 64, 128, 256})
        self.assertIs(self.root._switcher_icons, self.ui.icons)
        for size, image in self.ui.icons.items():
            self.assertEqual((image.width(), image.height()), (size, size))
        gc.collect()
        for compact in (False, True):
            self.ui.sidebar_compact = compact
            self.ui.draw_brand()
            items = self.ui.brand.find_withtag("app-icon")
            self.assertEqual(len(items), 1)
            self.assertEqual(self.ui.brand.itemcget(items[0], "image"), str(self.ui.icons[32]))
        names = self.root.tk.splitlist(self.root.tk.call("image", "names"))
        self.assertTrue(all(str(image) in names for image in self.ui.icons.values()))

    def test_user_mode_requires_version_check_and_engineer_shortcut_controls_parameters(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / ".tmp") as directory:
            base = Path(directory)
            window = tk.Toplevel(self.root)
            window.withdraw()
            release = {"version": app.VERSION, "notes": "checked"}
            settings = base / "settings.json"
            settings.write_text(json.dumps({"custom_setting": True}), encoding="utf-8")
            with patch.object(app, "CONFIG", settings), patch("tool_update.check_release", return_value=(release, False)):
                ui = app.Application(window, engineer=False, updates=True)
                window.after_cancel(ui.program_check_id)
                ui.program_check_id = None
                self.assertEqual(ui.pages.select(), str(ui.program_page))
                self.assertEqual(ui.pages.tab(ui.config_page, "state"), "hidden")
                called = []
                ui.run(lambda: called.append(True), lambda value: None)
                self.assertFalse(called)
                ui.program_check_finished((ui.program_source.get(), (release, False), None))
                self.assertEqual(ui.pages.tab(ui.config_page, "state"), "normal")
                self.assertEqual(ui.pages.tab(ui.settings_page, "state"), "hidden")
                self.assertEqual(ui.location_bar.winfo_manager(), "")
                self.assertEqual(ui.diff_tree.cget("displaycolumns"), ("status", "path"))
                ui.toggle_engineer()
                self.assertEqual(ui.pages.select(), str(ui.settings_page))
                self.assertEqual(ui.location_bar.winfo_manager(), "pack")
                ui.program_source.set("https://example.org/new-update.json")
                ui.save_program_source()
                self.assertFalse(ui.program_checked)
                self.assertTrue(json.loads(settings.read_text())["custom_setting"])
                self.assertEqual(json.loads(settings.read_text())["program_update_url"], ui.program_source.get())
                target = base / "publish"
                target.mkdir()
                ui.target.set(str(target))
                ui.update_mode.set("strict")
                ui.connect()
                deadline = time.monotonic() + 6
                while ui.busy and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.01)
                self.assertFalse(ui.busy)
                saved = json.loads(settings.read_text())
                self.assertEqual(saved["update_mode"], "strict")
                self.assertEqual(saved["program_update_url"], ui.program_source.get())
                ui.toggle_engineer()
                self.assertEqual(ui.pages.select(), str(ui.program_page))
                self.assertEqual(ui.pages.tab(ui.tools_page, "state"), "hidden")
            window.destroy()

    def test_program_new_version_and_check_failure_keep_user_operations_blocked(self):
        window = tk.Toplevel(self.root)
        window.withdraw()
        with patch.object(app, "CONFIG", Path(__file__).parent / "nonexistent-settings.json"):
            ui = app.Application(window, engineer=False, updates=True)
        release = {"version": "2099.1", "notes": "Required release"}
        ui.program_check_finished((ui.program_source.get(), (release, True), None))
        self.assertFalse(ui.program_checked)
        self.assertEqual(ui.pages.tab(ui.demo_page, "state"), "hidden")
        self.assertEqual(str(ui.program_apply_button.cget("state")), "normal")
        ui.program_check_finished((ui.program_source.get(), None, "network unavailable"))
        self.assertFalse(ui.program_checked)
        self.assertIn("network unavailable", ui.program_notes.get())
        window.destroy()

    def test_format_checkboxes_discover_save_and_invalidate_preview(self):
        from generate import generate
        from core import read_json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp') as directory:
            base = Path(directory)
            original = base / 'source'
            original.mkdir()
            (original / 'font.TTF').write_bytes(b'font')
            (original / 'extra.otf').write_bytes(b'other font')
            target = base / 'publish'
            target.mkdir()
            manifest_path = generate(original, base / 'repo', 'rk', 'RK', '1')
            self.ui.target.set(str(target))
            self.ui.engine = Engine(target)
            settings = base / 'settings.json'
            settings.write_text('{"repo":"keep me","other":123}', encoding='utf-8')
            with patch.object(app, 'CONFIG', settings):
                dialog = self.ui.show_formats(read_json(manifest_path))
                self.assertTrue(dialog.format_variables['.ttf'].get())
                self.assertFalse(dialog.format_variables['.otf'].get())
                dialog.format_variables['.ttf'].set(False)
                dialog.format_variables['.otf'].set(True)
                self.ui.checked = {'old': 'preview'}
                dialog.save_selection()
            saved = read_json(settings)
            self.assertIn('.otf', saved['file_extensions'])
            self.assertNotIn('.ttf', saved['file_extensions'])
            self.assertEqual(saved['other'], 123)
            self.assertEqual(saved['repo'], 'keep me')
            self.assertEqual(saved['format_inventory']['id'], 'rk')
            self.assertIsNone(self.ui.checked)
            self.assertIn('.otf', self.ui.engine.extensions)
            self.assertNotIn('.ttf', self.ui.engine.extensions)

    def test_window_and_catalog_render(self):
        catalog = {"profiles": [{"id": "test", "name": "比赛版", "version": "1", "manifest": "manifest.json", "sha256": "a" * 64}]}
        self.ui.receive_catalog((Source(local=Path(__file__).parent), catalog))
        self.root.update()
        self.assertEqual(len(self.ui.tree.get_children()), 1)
        self.assertIn("比赛版", self.ui.tree.item("0")["values"])

    def test_defaults_remain_editable(self):
        self.assertEqual(self.ui.repo.get(), "https://gitee.com/potper/odoiotassets")
        self.assertEqual([p["name"] for p in self.ui.presets], ["Jetson", "RK"])
        self.assertEqual(len(self.ui.tree.get_children()), 2)
        self.ui.repo.set("https://github.com/example/another")
        self.assertEqual(self.ui.repo.get(), "https://github.com/example/another")

    def test_sidebar_navigation_matches_pages_and_resizes(self):
        self.root.geometry("1240x780")
        self.root.deiconify()
        self.root.update()
        self.assertFalse(self.ui.sidebar_compact)
        self.ui.nav_buttons[str(self.ui.assets_page)].invoke()
        self.root.update()
        self.assertEqual(self.ui.pages.select(), str(self.ui.assets_page))
        self.assertEqual(self.ui.page_title.get(), "Assets 资源")
        self.assertTrue(self.ui.nav_buttons[str(self.ui.assets_page)].selected)
        self.assertEqual(sum(b.selected for b in self.ui.nav_buttons.values()), 1)
        self.ui.pages.select(self.ui.config_page)
        self.root.update()
        self.assertTrue(self.ui.nav_buttons[str(self.ui.config_page)].selected)
        self.root.geometry("900x640")
        self.root.update()
        self.assertTrue(self.ui.sidebar_compact)
        self.assertTrue(all(b.compact for b in self.ui.nav_buttons.values()))
        self.root.focus_force()
        self.root.update()
        self.ui.nav_buttons[str(self.ui.settings_page)].focus_set()
        self.root.update()
        self.ui.nav_buttons[str(self.ui.settings_page)].event_generate("<Return>")
        self.root.update()
        self.assertEqual(self.ui.pages.select(), str(self.ui.settings_page))
        self.ui.run(lambda: None, lambda _: None)
        self.assertEqual(self.ui.phase_badge.phase, "busy")
        self.wait_job()
        self.assertEqual(self.ui.phase_badge.phase, "idle")

    def test_dark_theme_keeps_text_and_diff_colours_readable(self):
        from tkinter import ttk
        def brightness(colour):
            channels = [int(colour[i:i+2], 16) / 255 for i in (1, 3, 5)]
            linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4 for value in channels]
            return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))
        def contrast(a, b):
            light, dark = sorted((brightness(a), brightness(b)), reverse=True)
            return (light + .05) / (dark + .05)
        for text in (self.ui.text, self.ui.demo_text):
            self.assertGreater(contrast(text.cget("foreground"), text.cget("background")), 4.5)
        style = ttk.Style(self.root)
        self.assertGreater(contrast(style.lookup("Treeview", "foreground"), style.lookup("Treeview", "background")), 4.5)
        for tag in ("same", "different", "permission"):
            options = self.ui.diff_tree.tag_configure(tag)
            self.assertGreater(contrast(options["foreground"], options["background"]), 4.5)
        self.assertNotIn("Notebook.label", str(style.layout("Workspace.TNotebook.Tab")))
        self.assertIn("Notebook.label", str(style.layout("TNotebook.Tab")))  # Dialog tabs remain visible.

    def test_theme_accepts_python38_font_lookup_signature(self):
        import switcher_style
        original = switcher_style.font.nametofont
        # Verified against CPython v3.8.10/Lib/tkinter/font.py: def nametofont(name).
        def legacy_nametofont(name):
            return original(name)
        with patch("switcher_style.font.nametofont", side_effect=legacy_nametofont):
            family = switcher_style.apply_theme(self.root)
            self.root.update()
        self.assertTrue(family)
        self.assertIn("TkDefaultFont", self.root.tk.splitlist(self.root.tk.call("font", "names")))
        self.assertEqual(self.ui.nav_buttons[str(self.ui.settings_page)].label, "设置")

    def test_pages_and_update_requires_check_then_choice(self):
        from generate import generate
        from core import read_json, load_profile
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            base = Path(directory)
            source, target, repo = base / "source", base / "publish", base / "repo"
            source.mkdir()
            target.mkdir()
            (source / "script.py").write_bytes(b"remote")
            (target / "script.py").write_bytes(b"local")
            (target / "extra.json").write_bytes(b"[]")
            generate(source, repo, "rk", "RK", "1")
            origin = Source(local=repo)
            profile = read_json(repo / "catalog.json")["profiles"][0]
            manifest = load_profile(origin, profile)
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.profiles = [{"manifest": manifest, "source": origin}]
            self.ui.show_profiles()
            self.ui.tree.selection_set("0")
            self.root.update()
            self.assertEqual([self.ui.pages.tab(t, "text") for t in self.ui.pages.tabs()],
                             ["更新文件", "Assets 资源", "配置切换", "IoT Demo", "辅助工具", "设置"])
            self.assertEqual(str(self.ui.apply_button.cget("state")), "disabled")
            self.ui.preview()
            self.wait_job()
            self.root.update()
            self.assertIsNotNone(self.ui.checked)
            self.assertEqual(str(self.ui.apply_button.cget("state")), "normal")
            self.assertEqual(len(self.ui.diff_tree.get_children()), 2)
            self.assertIn("增量更新", self.ui.update_summary.get())
            self.ui.mode_buttons[1].invoke()
            self.assertEqual(self.ui.update_mode.get(), "strict")
            self.assertIn("严格更新", self.ui.update_summary.get())
            with patch("app.messagebox.askyesno", return_value=True):
                self.ui.apply()
                self.wait_job()
            self.assertEqual((target / "script.py").read_bytes(), b"remote")
            self.assertFalse((target / "extra.json").exists())
            self.assertIsNone(self.ui.checked)

    def test_small_window_keeps_actions_visible_and_log_retains_output(self):
        self.root.geometry("900x640")
        self.root.deiconify()
        self.root.update()
        self.assertFalse(self.ui.log_visible)
        self.ui.append("折叠期间也记录日志")
        for page, widgets in (
                (self.ui.update_page, (self.ui.check_button, self.ui.apply_button, self.ui.diff_tree)),
                (self.ui.assets_page, (self.ui.assets_check_button, self.ui.assets_apply_button, self.ui.assets_tree)),
                (self.ui.config_page, (self.ui.config_apply_button, self.ui.config_compare_button, self.ui.config_mapping)),
                (self.ui.demo_page, (self.ui.demo_run_button, self.ui.demo_checked_button, self.ui.demo_skip_button, self.ui.demo_stop_button,
                                     self.ui.demo_queue_bar, self.ui.demo_log_filter, self.ui.demo_grid, self.ui.demo_text)),
                (self.ui.tools_page, tuple(self.ui.permission_preset_buttons)),
                (self.ui.settings_page, ())):
            self.ui.pages.select(page)
            self.root.update()
            if page == self.ui.demo_page:
                self.assertGreaterEqual(self.ui.demo_grid.winfo_width(), 180)
                self.assertGreaterEqual(self.ui.demo_output.winfo_width(), 260)
            for widget in widgets + (self.ui.log_button, self.ui.cancel_button):
                self.assertTrue(widget.winfo_viewable(), str(widget))
                self.assertGreater(widget.winfo_height(), 15)
                bottom = widget.winfo_rooty() + widget.winfo_height()
                self.assertLessEqual(bottom, self.root.winfo_rooty() + self.root.winfo_height())
                right = widget.winfo_rootx() + widget.winfo_width()
                self.assertLessEqual(right, self.root.winfo_rootx() + self.root.winfo_width())
        self.ui.pages.select(self.ui.update_page)
        self.ui.log_button.invoke()
        self.root.update()
        self.assertTrue(self.ui.text.winfo_viewable())
        self.assertIn("折叠期间也记录日志", self.ui.text.get("1.0", "end"))
        self.assertTrue(self.ui.apply_button.winfo_viewable())
        self.assertGreater(self.ui.diff_tree.winfo_height(), 80,
                           "body={}, pane={}, schemes={}, log={}, status={}".format(
                               self.ui.pages.winfo_height(), self.ui.update_pane.winfo_height(), self.ui.tree.winfo_height(),
                               self.ui.log_output.winfo_height(), self.ui.status_label.winfo_height()))
        self.ui.log_button.invoke()
        self.root.update()
        self.assertFalse(self.ui.text.winfo_viewable())
        self.assertIn("折叠期间也记录日志", self.ui.text.get("1.0", "end"))

    def test_config_versions_are_dynamic_and_apply_three_files(self):
        from test_config_versions import write_bundle
        temp_root = Path(__file__).resolve().parent / ".tmp"
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as directory:
            target = Path(directory) / "publish"
            target.mkdir()
            raw = write_bundle(target, "福建农职", "_福建农职")
            (target / "config/空版本").mkdir()
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.refresh_config_choices()
            self.wait_job()
            self.assertEqual(set(self.ui.config_tree.get_children()), {"福建农职", "空版本"})
            self.ui.config_tree.selection_set("空版本")
            self.root.update()
            self.wait_job()
            self.assertEqual(str(self.ui.config_apply_button.cget("state")), "disabled")
            self.ui.config_tree.selection_set("福建农职")
            self.root.update()
            self.wait_job()
            self.assertEqual(len(self.ui.config_mapping.get_children()), 3)
            self.assertEqual(str(self.ui.config_apply_button.cget("state")), "normal")
            with patch("app.messagebox.askyesno", return_value=True):
                self.ui.apply_config()
                self.wait_job()
                self.root.update()
                if self.ui.busy:
                    self.wait_job()
            for name, data in raw.items():
                self.assertEqual((target / name).read_bytes(), data)
            self.assertEqual(self.ui.task_mode.get(), "配置版本：福建农职")
            write_bundle(target, "新加入版本")
            self.ui.refresh_config_choices()
            self.wait_job()
            self.root.update()
            if self.ui.busy:
                self.wait_job()
            self.assertIn("新加入版本", self.ui.config_tree.get_children())

    def test_worker_completes_on_tk_thread(self):
        results = []
        self.ui.run(lambda: 42, results.append)
        self.wait_job()
        self.assertEqual(results, [42])

    def test_assets_page_compares_content_and_downloads_only_missing(self):
        from generate import generate
        from core import read_json, load_profile
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, target, repo = base / "source", base / "publish", base / "repo"
            (source / "Assets").mkdir(parents=True)
            (target / "Assets").mkdir(parents=True)
            for name, raw in (("same.png", b"same"), ("different.png", b"BBBB"), ("missing.avi", b"video")):
                (source / "Assets" / name).write_bytes(raw)
            (target / "Assets/same.png").write_bytes(b"same")
            (target / "Assets/different.png").write_bytes(b"AAAA")
            generate(source, repo, "rk", "RK", "1")
            origin = Source(local=repo)
            profile = read_json(repo / "catalog.json")["profiles"][0]
            manifest = load_profile(origin, profile)
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.profiles = [{"manifest": manifest, "source": origin}]
            self.ui.show_profiles()
            self.ui.pages.select(self.ui.assets_page)
            self.ui.assets_combo.current(0)
            self.ui.preview_assets()
            self.wait_job()
            self.assertEqual(self.ui.assets_tree.item("Assets/same.png", "tags"), ("same",))
            self.assertEqual(self.ui.assets_tree.item("Assets/different.png", "values")[4], "跳过")
            self.assertEqual(str(self.ui.assets_apply_button.cget("state")), "normal")
            self.ui.assets_tree.selection_set("Assets/different.png")
            self.root.update()
            self.ui.show_assets_details()
            self.assertIn("sha256", self.ui.diagnostic_window.summary_text.get("1.0", "end"))
            with patch("app.messagebox.askyesno", return_value=True):
                self.ui.download_assets()
                self.wait_job()
            self.assertEqual((target / "Assets/missing.avi").read_bytes(), b"video")
            self.assertEqual((target / "Assets/different.png").read_bytes(), b"AAAA")
            self.assertIsNone(self.ui.assets_checked)
            self.ui.preview_assets()
            self.wait_job()
            self.assertEqual(str(self.ui.assets_apply_button.cget("state")), "disabled")
            self.assertEqual(str(self.ui.assets_combo.cget("state")), "readonly")

    def test_config_json_comparison_tabs_colors_and_stale_preview(self):
        from test_config_versions import write_bundle
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "publish"
            target.mkdir()
            write_bundle(target, "福建农职", "_福建农职")
            active = target / "TrainTaskInfo.json"
            active.write_bytes(b'[{"PythonScriptPath":"old-sensitive-script.py"}]')
            template = target / "config/福建农职/TrainTaskInfo_福建农职.json"
            template.write_bytes(b'[{"PythonScriptPath":"new-sensitive-script.py"}]')
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.refresh_config_choices()
            self.wait_job()
            self.ui.config_tree.selection_set("福建农职")
            self.root.update()
            self.wait_job()
            self.root.update()
            self.assertEqual(str(self.ui.config_compare_button.cget("state")), "normal")
            self.ui.config_compare_button.invoke()
            self.wait_job()
            window = self.ui.config_diff_window
            self.assertEqual([window.pages.tab(t, "text") for t in window.pages.tabs()],
                             ["对比摘要", "JSON 内容差异（格式化）", "原始文本差异"])
            self.assertTrue(window.json_diff_text.tag_ranges("add"))
            self.assertTrue(window.json_diff_text.tag_ranges("delete"))
            self.assertIn("old-sensitive-script.py", window.json_diff_text.get("1.0", "end"))
            self.assertIn("new-sensitive-script.py", window.raw_diff_text.get("1.0", "end"))
            self.assertNotIn("sensitive-script.py", self.ui.text.get("1.0", "end"))
            self.assertIn(b'old-sensitive-script.py', active.read_bytes())
            self.assertEqual(str(self.ui.config_apply_button.cget("state")), "normal")
            template.write_bytes(b'[]')
            with patch("app.messagebox.showerror") as error:
                self.ui.config_compare_button.invoke()
                self.wait_job()
                error.assert_called_once()
            self.assertIsNone(self.ui.config_preview)
            self.assertEqual(str(self.ui.config_compare_button.cget("state")), "disabled")

    def test_demo_page_discovers_and_runs_selected_task_with_logs(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "publish"
            script = target / "IoT/测试/demo.py"
            script.parent.mkdir(parents=True)
            script.write_text("print('GUI-demo-ok')\n", encoding="utf-8")
            task = {"TrainTaskId": 2, "TrainTaskName": "测试模块", "PythonExePath": sys.executable,
                    "ScriptFloderPath": "IoT/测试", "PythonScriptPath": "demo.py"}
            (target / "TrainTaskInfo.json").write_text(json.dumps([task]), encoding="utf-8")
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.pages.select(self.ui.demo_page)
            self.root.update()
            self.wait_job()
            self.assertEqual(tuple(self.ui.demo_grid.cards), ("2",))
            self.ui.demo_grid.select("2")
            self.root.update()
            self.assertEqual(str(self.ui.demo_run_button.cget("state")), "normal")
            with patch.object(app, "CONFIG", base / "settings.json"), patch("app.messagebox.askyesno", return_value=True):
                self.ui.start_demo()
                self.assertTrue(self.ui.demo_running)
                self.assertEqual(str(self.ui.demo_stop_button.cget("state")), "normal")
                self.assertEqual(str(self.ui.check_button.cget("state")), "disabled")
                self.wait_job()
            self.assertFalse(self.ui.demo_running)
            self.assertIn("GUI-demo-ok", self.ui.demo_text.get("1.0", "end"))
            logfile = Path(self.ui.demo_log_path.get())
            self.assertTrue(logfile.is_file())
            self.assertIn("GUI-demo-ok", logfile.read_text(encoding="utf-8"))
            self.assertIn("正常结束", self.ui.demo_status.get())
            self.assertEqual(self.ui.demo_grid.cards['2'].phase.cget('text'), '已完成')
            self.assertEqual(str(self.ui.demo_stop_button.cget("state")), "disabled")
            script.unlink()
            self.ui.update_current()
            self.wait_job()
            self.root.update()
            self.assertEqual(str(self.ui.demo_run_button.cget("state")), "disabled")

    def test_demo_all_sequential_cards_follow_current_module_then_cancel_queue(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp') as directory:
            base = Path(directory)
            target = base / 'publish'
            tasks = []
            for key, name in ((1, '模块A'), (3, '模块B')):
                script = target / 'IoT' / name / 'demo.py'
                script.parent.mkdir(parents=True)
                script.write_text("import time\nprint('GUI-batch-ready',flush=True)\ntime.sleep({})\n".format('.2' if key == 1 else '30'), encoding='utf-8')
                tasks.append({'TrainTaskId': key, 'TrainTaskName': name, 'PythonExePath': sys.executable,
                              'ScriptFloderPath': 'IoT/' + name, 'PythonScriptPath': 'demo.py'})
            tasks.insert(1, dict(tasks[0], TrainTaskId=2, TrainTaskName='模块A别名'))
            tasks.append(dict(tasks[0], TrainTaskId=4, TrainTaskName='缺失模块', PythonScriptPath='missing.py'))
            tasks.append(dict(tasks[2], TrainTaskId=5, TrainTaskName='后续模块'))
            (target / 'TrainTaskInfo.json').write_text(json.dumps(tasks), encoding='utf-8')
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.root.geometry('1240x780')
            self.root.deiconify()
            self.ui.pages.select(self.ui.demo_page)
            self.root.update()
            self.wait_job()
            self.ui.demo_pane.sashpos(0, 540)
            self.root.update()
            self.assertEqual(str(self.ui.demo_all_button.cget('state')), 'normal')
            self.assertGreaterEqual(self.ui.demo_grid.columns, 2)
            self.assertGreater(self.ui.demo_text.winfo_rootx(), self.ui.demo_grid.winfo_rootx() + self.ui.demo_grid.winfo_width())
            with patch.object(app, 'CONFIG', base / 'settings.json'), patch('app.messagebox.askyesno', return_value=True) as confirm:
                self.ui.demo_all_button.invoke()
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        self.root.update()
                        if '运行中' in self.ui.demo_grid.cards['3'].phase.cget('text'):
                            break
                        time.sleep(.01)
                    for key in ('1', '2', '3'):
                        card = self.ui.demo_grid.cards[key]
                        self.assertIn('运行中' if key == '3' else '已完成', card.phase.cget('text'))
                        self.assertIn('PID', card.details.get('1.0', 'end'))
                        self.assertIn('IoT/', card.details.get('1.0', 'end'))
                    first = next(iter(self.ui.demo_grid.cards['1'].scripts.values()))
                    second = next(iter(self.ui.demo_grid.cards['2'].scripts.values()))
                    self.assertNotEqual(first['pid'], second['pid'])
                    self.assertIn('运行 1', self.ui.demo_count.cget('text'))
                    self.assertIn('完成 2', self.ui.demo_count.cget('text'))
                    self.assertEqual(self.ui.demo_grid.selected, '3')
                    self.assertIn('等待启动', self.ui.demo_grid.cards['5'].phase.cget('text'))
                    self.assertIn('不可运行', self.ui.demo_grid.cards['4'].phase.cget('text'))
                    self.assertIn('跳过', confirm.call_args.args[1])
                    self.assertEqual(str(self.ui.check_button.cget('state')), 'disabled')
                    self.ui.demo_grid.select('3')
                    self.assertEqual(str(self.ui.demo_run_button.cget('state')), 'disabled')
                finally:
                    self.ui.stop_demo()
                    self.wait_job()
            for key in ('1', '2'):
                self.assertEqual(self.ui.demo_grid.cards[key].phase.cget('text'), '已完成')
            self.assertEqual(self.ui.demo_grid.cards['3'].phase.cget('text'), '已停止')
            self.assertEqual(self.ui.demo_grid.cards['5'].phase.cget('text'), '未启动')
            self.assertFalse(self.ui.demo_running)
            self.assertEqual(str(self.ui.demo_all_button.cget('state')), 'normal')
            self.assertTrue(Path(self.ui.demo_log_path.get()).is_file())

    def test_demo_grid_reflows_and_scrolls_without_losing_selection(self):
        self.root.geometry('1240x780')
        self.root.deiconify()
        self.ui.pages.select(self.ui.demo_page)
        self.root.update()
        self.ui.demo_grid.set_tasks([(str(index), '模块' + str(index), ['IoT/test/demo.py'], None) for index in range(12)])
        self.ui.demo_pane.sashpos(0, 530)
        self.root.update()
        self.ui.demo_grid.select('3')
        self.assertEqual(self.ui.demo_grid.columns, 2)
        self.ui.demo_grid.canvas.yview_moveto(1)
        self.assertGreater(self.ui.demo_grid.canvas.yview()[0], 0)
        self.ui.demo_pane.sashpos(0, 280)
        self.root.update()
        self.assertEqual(self.ui.demo_grid.columns, 1)
        self.assertEqual(self.ui.demo_grid.selected, '3')
        self.assertTrue(self.ui.demo_grid.cards['3'].selected)

    def test_demo_skip_advances_queue_progress_and_clicking_cards_filters_logs(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp') as directory:
            base, tasks = Path(directory), []
            target = base / 'publish'
            for key in (1, 2):
                script = target / 'IoT' / ('模块' + str(key)) / 'demo.py'
                script.parent.mkdir(parents=True)
                script.write_text("import time\nprint('only-module-{}',flush=True)\ntime.sleep(30)\n".format(key), encoding='utf-8')
                tasks.append({'TrainTaskId': key, 'TrainTaskName': '模块' + str(key), 'PythonExePath': sys.executable,
                              'ScriptFloderPath': 'IoT/模块' + str(key), 'PythonScriptPath': 'demo.py'})
            (target / 'TrainTaskInfo.json').write_text(json.dumps(tasks), encoding='utf-8')
            self.ui.target.set(str(target))
            self.ui.engine = Engine(target)
            self.ui.refresh_demo_tasks()
            self.wait_job()
            def wait_output(text):
                limit = time.monotonic() + 7
                while text not in self.ui.demo_text.get('1.0', 'end') and time.monotonic() < limit:
                    self.root.update()
                    time.sleep(.01)
                self.assertIn(text, self.ui.demo_text.get('1.0', 'end'))
            with patch.object(app, 'CONFIG', base / 'settings.json'), patch('app.messagebox.askyesno', return_value=True):
                self.ui.start_all_demos()
                try:
                    wait_output('only-module-1')
                    self.assertIn('第 1 / 2', self.ui.demo_progress_text.get())
                    self.assertEqual(str(self.ui.demo_skip_button.cget('state')), 'normal')
                    self.ui.demo_skip_button.invoke()
                    self.assertEqual(str(self.ui.demo_skip_button.cget('state')), 'disabled')
                    wait_output('only-module-2')
                    self.assertEqual(self.ui.demo_grid.cards['1'].phase.cget('text'), '已跳过')
                    self.assertIn('第 2 / 2', self.ui.demo_progress_text.get())
                    self.assertEqual(float(self.ui.demo_queue_bar['value']), 1)
                    self.assertEqual(self.ui.demo_grid.selected, '2')
                    self.assertIn('总用时', self.ui.demo_elapsed_text.get())
                    self.assertIn('00:', self.ui.demo_grid.cards['1'].subtitle.cget('text'))
                    self.ui.demo_log_mode.set('当前模块日志')
                    self.ui.render_demo_logs()
                    self.assertIn('only-module-2', self.ui.demo_text.get('1.0', 'end'))
                    self.assertNotIn('only-module-1', self.ui.demo_text.get('1.0', 'end'))
                    self.assertEqual(Path(self.ui.demo_log_path.get()), self.ui.demo_module_logs['2'])
                    self.ui.demo_grid.select('1')
                    self.root.update()
                    self.assertIn('only-module-1', self.ui.demo_text.get('1.0', 'end'))
                    self.assertNotIn('only-module-2', self.ui.demo_text.get('1.0', 'end'))
                    # Card selection affects log viewing, never the target of Skip current.
                    self.ui.demo_skip_button.invoke()
                    self.wait_job()
                finally:
                    if self.ui.busy:
                        self.ui.stop_demo()
                        self.wait_job()
            self.assertEqual(self.ui.demo_grid.cards['2'].phase.cget('text'), '已跳过')
            self.assertIn('已跳过 2 个', self.ui.demo_status.get())
            self.assertIn('已处理 2 / 2', self.ui.demo_progress_text.get())
            self.assertEqual(float(self.ui.demo_queue_bar['value']), 2)
            self.assertEqual(str(self.ui.demo_skip_button.cget('state')), 'disabled')
            self.ui.demo_log_mode.set('全部日志')
            self.ui.render_demo_logs()
            self.assertIn('only-module-1', self.ui.demo_text.get('1.0', 'end'))
            self.assertIn('only-module-2', self.ui.demo_text.get('1.0', 'end'))
            self.assertEqual(Path(self.ui.demo_log_path.get()), self.ui.demo_all_log)

    def test_demo_log_copy_export_is_full_and_view_buffer_is_bounded(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp') as directory:
            base = Path(directory)
            all_log, module_log = base / 'all.log', base / 'module.log'
            all_log.write_text('full-all-log\n' * 3200, encoding='utf-8')
            module_log.write_text('full-module-log\n' * 3200, encoding='utf-8')
            self.ui.demo_grid.set_tasks([('1', '模块', ['IoT/a.py'], None), ('2', '模块2', ['IoT/b.py'], None)])
            self.ui.demo_tasks = {'1': {'task': {'TrainTaskName': '模块'}, 'valid': True}}
            self.ui.append_demo({'task_id': None, 'line': 'aggregate', 'log_path': str(all_log)})
            for index in range(3100):
                self.ui.append_demo({'task_id': '1', 'line': 'line-' + str(index), 'module_log_path': str(module_log) if index == 0 else None})
            self.assertEqual(len(self.ui.demo_log_entries), 3000)
            self.ui.demo_grid.select('1')
            self.ui.demo_log_mode.set('当前模块日志')
            self.ui.render_demo_logs()
            self.assertNotIn('line-99\n', self.ui.demo_text.get('1.0', 'end'))
            self.assertIn('line-3099', self.ui.demo_text.get('1.0', 'end'))
            with patch.object(self.root, 'clipboard_clear') as clear, patch.object(self.root, 'clipboard_append') as copy:
                self.ui.copy_demo_logs()
            clear.assert_called_once_with()
            copy.assert_called_once_with(self.ui.demo_text.get('1.0', 'end-1c'))
            self.assertEqual(Path(self.ui.demo_log_path.get()), module_log)
            export = base / 'export.log'
            with patch('app.filedialog.asksaveasfilename', return_value=str(export)):
                self.ui.export_demo_logs()
            self.assertEqual(export.read_bytes(), module_log.read_bytes(), 'export must not truncate to visible buffer')
            self.ui.demo_log_mode.set('全部日志')
            self.ui.render_demo_logs()
            with patch('app.filedialog.asksaveasfilename', return_value=str(export)):
                self.ui.export_demo_logs()
            self.assertEqual(export.read_bytes(), all_log.read_bytes())
            self.ui.demo_log_mode.set('当前模块日志')
            self.ui.demo_grid.select('2')
            self.root.update()
            self.assertEqual(self.ui.demo_text.get('1.0', 'end-1c'), '')
            self.assertIn('尚无', self.ui.demo_log_path.get())
            with patch('app.messagebox.showinfo') as info, patch('app.filedialog.asksaveasfilename') as choose:
                self.ui.export_demo_logs()
            info.assert_called_once()
            choose.assert_not_called()

    def test_demo_checked_queue_reports_failure_and_retries_only_remaining_modules(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp') as directory:
            base = Path(directory)
            target = base / 'publish'
            folder = target / 'IoT' / 'test'
            folder.mkdir(parents=True)
            (folder / 'first.py').write_text(
                "from pathlib import Path\np = Path('first-run')\n"
                "if not p.exists():\n    p.touch()\n    print('first-failed')\n    raise SystemExit(130)\n"
                "print('retry-success')\n", encoding='utf-8')
            (folder / 'second.py').write_text("print('second-ran')\n", encoding='utf-8')
            (folder / 'other.py').write_text("raise AssertionError('unchecked module ran')\n", encoding='utf-8')
            tasks = [
                {'TrainTaskId': key, 'TrainTaskName': name, 'PythonExePath': sys.executable,
                 'ScriptFloderPath': 'IoT/test', 'PythonScriptPath': script}
                for key, name, script in ((2, '先运行', 'first.py'), (1, '后运行', 'second.py'), (3, '不勾选', 'other.py'))
            ]
            (target / 'TrainTaskInfo.json').write_text(json.dumps(tasks), encoding='utf-8')
            self.ui.target.set(str(target))
            self.ui.engine = Engine(target)
            self.ui.pages.select(self.ui.demo_page)
            self.root.update()
            self.wait_job()
            self.ui.demo_grid.cards['1'].check.invoke()
            self.ui.demo_grid.cards['2'].check.invoke()
            self.assertEqual(str(self.ui.demo_checked_button.cget('state')), 'normal')
            with patch.object(app, 'CONFIG', base / 'settings.json'), patch('app.messagebox.askyesno', return_value=True):
                self.ui.demo_checked_button.invoke()
                self.wait_job()
                self.assertIn('异常退出（130）', self.ui.demo_status.get())
                self.assertEqual(self.ui.demo_results.get_children(), ('2', '1'))
                self.assertEqual(self.ui.demo_results.set('2', 'exit'), '130')
                self.assertEqual(self.ui.demo_results.set('1', 'result'), '未启动')
                self.assertEqual(str(self.ui.demo_retry_button.cget('state')), 'normal')
                self.assertIn('IoT/test/first.py · 异常 · 退出码 130',
                              self.ui.demo_result_detail.get('1.0', 'end'))
                self.ui.demo_results.selection_set('1')
                self.root.update()
                self.assertIn('前一模块异常，未启动', self.ui.demo_result_detail.get('1.0', 'end'))
                self.assertEqual(str(self.ui.demo_result_log_button.cget('state')), 'disabled')
                self.ui.demo_results.selection_set('2')
                self.root.update()
                self.ui.demo_log_entries.clear()  # Model a module whose output was evicted by later logs.
                self.ui.demo_result_log_button.invoke()
                self.assertEqual(self.ui.demo_output.select(), str(self.ui.demo_log_page))
                self.assertIn('first-failed', self.ui.demo_text.get('1.0', 'end'))
                self.ui.demo_output.select(self.ui.demo_result_page)
                self.ui.demo_retry_button.invoke()
                self.wait_job()
            self.assertEqual(self.ui.demo_results.get_children(), ('2', '1'))
            self.assertEqual(self.ui.demo_results.set('2', 'result'), '已完成')
            self.assertEqual(self.ui.demo_results.set('1', 'result'), '已完成')
            self.assertIn('second-ran', self.ui.demo_module_logs['1'].read_text(encoding='utf-8'))
            self.assertNotIn('3', self.ui.demo_module_logs)
            self.assertEqual(str(self.ui.demo_retry_button.cget('state')), 'disabled')

    def test_demo_preflight_explains_missing_script_and_empty_config_inline(self):
        import json
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent / '.tmp') as directory:
            base = Path(directory)
            target = base / 'publish'
            script = target / 'IoT/test/demo.py'
            script.parent.mkdir(parents=True)
            script.write_text("raise AssertionError('should not run')\n", encoding='utf-8')
            config = target / 'TrainTaskInfo.json'
            config.write_text(json.dumps([{
                'TrainTaskId': 4, 'TrainTaskName': '模型校验', 'PythonExePath': sys.executable,
                'ScriptFloderPath': 'IoT/test', 'PythonScriptPath': 'demo.py',
            }]), encoding='utf-8')
            self.ui.target.set(str(target))
            self.ui.engine = Engine(target)
            self.ui.pages.select(self.ui.demo_page)
            self.root.update()
            self.wait_job()
            self.assertIn('运行模块后', self.ui.demo_result_hint.get())
            script.unlink()
            with patch.object(app, 'CONFIG', base / 'settings.json'), patch('app.messagebox.askyesno', return_value=True), \
                    patch('app.messagebox.showerror') as error:
                self.ui.demo_all_button.invoke()
                self.wait_job()
            error.assert_called_once()
            self.assertIn('启动检查失败', self.ui.demo_result_hint.get())
            self.assertEqual(self.ui.demo_results.set('4', 'result'), '未启动')
            detail = self.ui.demo_result_detail.get('1.0', 'end')
            self.assertIn('模块 #4 模型校验 无法启动', detail)
            self.assertIn('点击左侧“刷新”', detail)
            self.assertEqual(str(self.ui.demo_retry_button.cget('state')), 'disabled')
            self.assertEqual(str(self.ui.demo_all_button.cget('state')), 'disabled')
            script.write_text("print('ready again')\n", encoding='utf-8')
            self.ui.refresh_demo_tasks()
            self.wait_job()
            self.assertEqual(str(self.ui.demo_retry_button.cget('state')), 'normal')
            self.assertIn('脚本不存在', self.ui.demo_result_detail.get('1.0', 'end'))
            with patch('app.messagebox.showerror') as error:
                config.write_text('[]', encoding='utf-8')
                self.ui.refresh_demo_tasks()
                self.wait_job()
                self.assertIn('没有 IoT 模块', self.ui.demo_grid.empty.cget('text'))
                self.assertFalse(self.ui.demo_results.get_children())
                config.write_text('{', encoding='utf-8')
                self.ui.refresh_demo_tasks()
                self.wait_job()
                self.assertIn('无法读取配置', self.ui.demo_grid.empty.cget('text'))
            error.assert_not_called()

    def test_demo_new_output_respects_scrolled_view_until_latest_is_clicked(self):
        self.root.geometry('900x640')
        self.root.deiconify()
        self.ui.pages.select(self.ui.demo_page)
        self.root.update()
        for i in range(100):
            self.ui.append_demo('line {}'.format(i))
        self.root.update_idletasks()
        self.assertTrue(self.ui.demo_log_at_end())
        self.ui.demo_text.yview_moveto(0)
        self.root.update_idletasks()
        self.assertFalse(self.ui.demo_log_at_end())
        self.ui.append_demo('new output while reading')
        self.root.update_idletasks()
        self.assertEqual(self.ui.demo_text.index('@0,0'), '1.0')
        self.ui.demo_latest_button.invoke()
        self.root.update_idletasks()
        self.assertTrue(self.ui.demo_log_at_end())

    def test_demo_clock_finishes_and_log_routing_does_not_parse_script_text(self):
        self.ui.demo_grid.set_tasks([('1', '模块', ['IoT/a.py'], None), ('2', '模块2', ['IoT/b.py'], None)])
        self.ui.demo_tasks = {key: {'task': {'TrainTaskName': '模块' + key}, 'scripts': ['IoT/a.py'], 'valid': True} for key in ('1', '2')}
        self.ui.begin_demo(['1', '2'])
        now = time.monotonic()
        self.ui.demo_started_at = now - 3661
        self.ui.demo_progress_event({'task_id': '1', 'index': 1, 'total': 2, 'phase': 'running', 'started': now - 65, 'elapsed': 65})
        self.assertIn('01:05', self.ui.demo_progress_text.get())
        self.assertIn('1:01:01', self.ui.demo_elapsed_text.get())
        self.ui.demo_grid.select('1')
        self.ui.demo_log_mode.set('当前模块日志')
        self.ui.append_demo({'task_id': '1', 'line': '[2 模块2] 日志：fake.log', 'level': 'error'})
        self.ui.append_demo({'task_id': '2', 'line': '[1 模块1] wrong-module'})
        self.ui.render_demo_logs()
        self.assertIn('fake.log', self.ui.demo_text.get('1.0', 'end'))
        self.assertNotIn('wrong-module', self.ui.demo_text.get('1.0', 'end'))
        self.assertIsNone(self.ui.demo_all_log)
        self.assertTrue(self.ui.demo_text.tag_ranges('error'))
        self.ui.demo_running = False
        self.ui.finish_demo_cards("stopped")
        finished = self.ui.demo_elapsed_text.get()
        with patch('app.time.monotonic', return_value=self.ui.demo_finished_at + 60):
            self.ui.update_demo_clock()
        self.assertEqual(finished, self.ui.demo_elapsed_text.get())

    def test_gui_stop_and_close_wait_for_demo_cleanup(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = base / "publish"
            script = target / "IoT/test/demo.py"
            script.parent.mkdir(parents=True)
            script.write_text("import time\nprint('demo-started',flush=True)\ntime.sleep(30)\n", encoding="utf-8")
            task = {"TrainTaskId": 1, "PythonExePath": sys.executable,
                    "ScriptFloderPath": "IoT/test", "PythonScriptPath": "demo.py"}
            (target / "TrainTaskInfo.json").write_text(json.dumps([task]), encoding="utf-8")
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.refresh_demo_tasks()
            self.wait_job()
            self.ui.demo_grid.select("1")
            self.root.update()
            def wait_started():
                deadline = time.monotonic() + 5
                while "demo-started" not in self.ui.demo_text.get("1.0", "end") and time.monotonic() < deadline:
                    self.root.update()
                    time.sleep(.02)
                self.assertIn("demo-started", self.ui.demo_text.get("1.0", "end"))
            with patch.object(app, "CONFIG", base / "settings.json"), patch("app.messagebox.askyesno", return_value=True):
                self.ui.start_demo()
                wait_started()
                self.ui.demo_stop_button.invoke()
                self.wait_job()
                self.assertIn("已停止", self.ui.demo_status.get())
                self.ui.start_demo()
                wait_started()
                with patch.object(self.root, "destroy") as destroy:
                    self.ui.close()
                    self.assertTrue(self.ui.cancel.is_set())
                    self.wait_job()
                    destroy.assert_called_once()
            self.assertFalse(self.ui.demo_running)

    def test_green_same_row_and_selected_file_diagnostic(self):
        from generate import generate
        from core import read_json, load_profile
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, target, repo = base / "source", base / "publish", base / "repo"
            source.mkdir()
            target.mkdir()
            for folder in (source, target):
                (folder / "same.py").write_bytes(b"print('same')\n")
            generate(source, repo, "rk", "RK", "1")
            origin = Source(local=repo)
            manifest = load_profile(origin, read_json(repo / "catalog.json")["profiles"][0])
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.ui.profiles = [{"manifest": manifest, "source": origin}]
            self.ui.show_profiles()
            self.ui.tree.selection_set("0")
            self.root.update()
            self.ui.preview()
            self.wait_job()
            row = self.ui.diff_tree.get_children()[0]
            self.assertEqual(self.ui.diff_tree.item(row, "tags"), ("same",))
            self.assertEqual(str(self.ui.diagnose_button.cget("state")), "disabled")
            self.ui.diff_tree.selection_set(row)
            self.root.update()
            self.assertEqual(str(self.ui.diagnose_button.cget("state")), "normal")
            with patch.object(self.ui, "show_diagnostic") as display:
                self.ui.diagnose_selected()
                self.wait_job()
                self.assertIn("字节完全一致", display.call_args[0][0]["reason"])
            self.assertEqual((target / "same.py").read_bytes(), b"print('same')\n")
            self.assertFalse(self.ui.sync_permissions.get())
            self.ui.permissions_button.invoke()
            self.assertTrue(self.ui.sync_permissions.get())
            self.assertIsNone(self.ui.checked)
            self.assertEqual(str(self.ui.apply_button.cget("state")), "disabled")
            self.ui.preview()
            self.wait_job()
            self.assertTrue(self.ui.checked["sync_permissions"])

    def test_worker_failure_unblocks_controls(self):
        def fail():
            raise ValueError("expected test failure")
        with patch("app.messagebox.showerror") as error:
            self.ui.run(fail, lambda _: self.fail("unexpected success"))
            self.wait_job()
            error.assert_called_once()
        self.assertIn("expected test failure", self.ui.status.get())
        self.assertTrue(self.ui.log_visible)
        self.assertIn("expected test failure", self.ui.text.get("1.0", "end"))

    def test_permission_presets_use_selected_target_and_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "publish"
            target.mkdir()
            self.ui.engine = Engine(target)
            self.ui.target.set(str(target))
            self.assertEqual(len(self.ui.permission_preset_buttons), 3)
            with patch("app.sys.platform", "linux"), patch("app.messagebox.askyesno", return_value=False), patch("app.launch_preset") as launcher:
                self.ui.apply_permission_preset("root-and-777")
                launcher.assert_not_called()
            with patch("app.sys.platform", "linux"), patch("app.messagebox.askyesno", return_value=True) as confirmation, \
                    patch("app.launch_preset", return_value={"target": str(target), "preset": "root-and-777"}) as launcher:
                self.ui.apply_permission_preset("root-and-777")
                self.wait_job()
                if self.ui.busy:
                    self.wait_job()
                self.assertIs(launcher.call_args.args[0], self.ui.engine)
                self.assertIn(str(target), confirmation.call_args.args[1])
                self.assertIn("不生成备份", confirmation.call_args.args[1])
                self.assertIn("root:root", confirmation.call_args.args[1])
            self.assertIsNone(self.ui.checked)

    def test_diagnostic_window_colors_additions_and_deletions(self):
        from generate import generate
        from core import read_json, load_profile
        from file_compare import diagnose_file
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source, target, repo = base / "source", base / "publish", base / "repo"
            source.mkdir()
            target.mkdir()
            (source / "script.py").write_bytes(b"first\nremote value\nlast\n")
            (target / "script.py").write_bytes(b"first\nlocal value\nlast\n")
            generate(source, repo, "rk", "RK", "1")
            origin = Source(local=repo)
            manifest = load_profile(origin, read_json(repo / "catalog.json")["profiles"][0])
            report = diagnose_file(Engine(target), manifest, origin, "script.py")
            self.ui.show_diagnostic(report)
            window = self.ui.diagnostic_window
            text = window.diff_text
            self.assertTrue(text.tag_ranges("add"))
            self.assertTrue(text.tag_ranges("delete"))
            self.assertEqual(text.tag_cget("add", "foreground"), "#91e2bb")
            self.assertEqual(text.tag_cget("delete", "foreground"), "#ffaaa6")
            self.assertIn("-local value", text.get("1.0", "end"))
            self.assertIn("+remote value", text.get("1.0", "end"))
            self.assertNotIn("local value", self.ui.text.get("1.0", "end"))
            self.assertEqual((target / "script.py").read_bytes(), b"first\nlocal value\nlast\n")


if __name__ == "__main__":
    unittest.main()
