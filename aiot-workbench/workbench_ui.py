"""Workbench hooks around the original launcher lifecycle, with isolated maintenance."""
import logging
import os
import queue
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

from aiot_launcher import LauncherWindow
from core import assert_stopped
from launcher_process import interpreter_for
from launcher_runtime import load_settings
from launcher_settings_store import read_settings
from launcher_style import LauncherButton, palette
import tool_update
from version import VERSION

ROOT = Path(__file__).resolve().parent


class WorkbenchWindow(LauncherWindow):
    restart_requested = False
    open_engineer_on_start = False

    def __init__(self, *args, **kwargs):
        self.update_checked = False
        self.update_busy = False
        self.update_events = queue.Queue()
        self.release = None
        self.engineer_process = None
        self.content_busy = False
        self.update_dialog = None
        self.update_message = "正在检查工作台版本…"
        self.update_detail = ""
        self.update_requested = False
        super().__init__(*args, **kwargs)
        self.update_button = LauncherButton(self.canvas, text="程序更新", command=self.request_update,
                                             family=self.family, width=160, theme=self.theme, sidebar=True)
        self.update_button.configure(state="normal")
        self.canvas.create_window(16, 408, window=self.update_button, anchor="nw")
        self.root.bind("<Control-Shift-F12>", self.open_engineer, add="+")
        self.root.after(250, self.check_update)
        if self.open_engineer_on_start:
            self.root.after(900, self.open_engineer)

    def blocked(self):
        return not self.update_checked or self.update_busy or self.engineer_process is not None or getattr(self, "content_busy", False)

    def start(self):
        if self.blocked():
            self.open_updates() if self.engineer_process is None else self.status.set("请先关闭工程师面板。")
            return
        return super().start()

    def begin_config(self, action, version=None):
        if self.blocked():
            self.status.set("请先完成程序版本检查，并关闭工程师面板。")
            return False
        return super().begin_config(action, version)

    def open_settings(self):
        if self.blocked():
            self.open_updates() if self.engineer_process is None else self.status.set("请先关闭工程师面板。")
            return
        return super().open_settings()

    def apply_theme(self, theme):
        super().apply_theme(theme)
        if hasattr(self, "update_button"):
            self.update_button.set_theme(theme)

    def safe_to_maintain(self):
        if self.busy or self.config_busy or self.external_stopping or self.closing or self.destroyed:
            raise RuntimeError("请先停止 AIoT，并等待当前操作结束。停止按钮仍可使用。")
        if self.content_busy:
            raise RuntimeError("请等待文件更新结束，或在更新窗口取消准备。")
        if self.results_panel is not None and self.results_panel.submitting:
            raise RuntimeError("请等待成果提交完成。")
        if self.opening_results:
            raise RuntimeError("请等待成果目录打开。")
        assert_stopped(self.settings["publish_dir"])

    def open_engineer(self, event=None):
        if self.engineer_process is not None:
            self.status.set("工程师面板已打开，请切换到维护窗口。")
            return "break"
        try:
            self.safe_to_maintain()
            if self.update_busy:
                raise RuntimeError("请等待程序更新操作结束。")
            if self.settings_dialog is not None and self.settings_dialog.window.winfo_exists():
                raise RuntimeError("请先关闭设置窗口。")
            command = [interpreter_for("engineer"), str(ROOT / "engineer_entry.py"),
                       "--hosted", str(self.settings_path), "engineer"]
            # The maintained settings file is independent of the installation.
            if not self.settings_path.exists():
                from launcher_settings_store import write_settings
                write_settings(self.settings_path, self.settings)
            logdir = self.settings_path.parent / "logs"
            logdir.mkdir(parents=True, exist_ok=True)
            with (logdir / "engineer-startup.log").open("a", encoding="utf-8") as log:
                self.engineer_process = subprocess.Popen(command, cwd=str(ROOT), stdout=log, stderr=log,
                    env=dict(os.environ, AIOT_WORKBENCH_HOST_PID=str(os.getpid())))
            self.status.set("工程师面板已打开；关闭后返回工作台。")
            self.start_button.configure(state="disabled")
            if self.update_dialog is not None and self.update_dialog.winfo_exists():
                self.update_dialog.destroy()
        except Exception as exc:
            messagebox.showinfo("暂时无法打开工程师面板", str(exc), parent=self.root)
        return "break"

    def job(self, function, kind):
        if self.update_busy:
            return
        self.update_busy = True
        def worker():
            try:
                result = function()
                self.update_events.put((kind, result, None))
            except Exception as exc:
                logging.exception("程序更新操作失败")
                self.update_events.put((kind, None, str(exc)))
        threading.Thread(target=worker, daemon=True).start()
        self.render_updates()

    def check_update(self):
        if self.destroyed or self.update_busy or self.engineer_process is not None or self.content_busy:
            return
        self.update_checked = False
        self.update_message = "正在检查工作台版本…"
        self.job(lambda: tool_update.check_repository(self.settings_path, ROOT, VERSION), "checked")

    def request_update(self):
        try:
            self.safe_to_maintain()
            if self.engineer_process is not None:
                raise RuntimeError("请先关闭工程师面板。")
            self.open_updates()
            self.update_requested = True
            if not self.update_busy:
                if self.update_checked or self.release:
                    self.update_requested = False
                    self.download_update()
                else:
                    self.check_update()
        except Exception as exc:
            messagebox.showinfo("暂时无法更新", str(exc), parent=self.root)

    def download_update(self):
        try:
            self.safe_to_maintain()
            if self.engineer_process is not None:
                raise RuntimeError("请先关闭工程师面板。")
            if not self.update_checked and not self.release:
                self.check_update()
                return
            if not self.settings_path.exists():
                from launcher_settings_store import write_settings
                write_settings(self.settings_path, self.settings)
            from workbench_updates import update_all
            self.update_message = "正在更新工作台与应用文件…"
            self.content_busy = True
            self.job(lambda: update_all(ROOT, self.settings_path, VERSION, release=self.release,
                report=lambda message: self.update_events.put(("update_progress", message, None))), "combined")
        except Exception as exc:
            messagebox.showinfo("暂时无法更新", str(exc), parent=self.root)

    def offline_update(self):
        try:
            self.safe_to_maintain()
            if self.engineer_process is not None:
                raise RuntimeError("请先关闭工程师面板。")
            path = filedialog.askopenfilename(parent=self.root, title="选择与安装包同目录的 workbench-update.json", filetypes=[("发布信息", "*.json")])
            if not path:
                return
            self.update_message = "正在验证离线工作台安装包…"
            release = tool_update.validate_release(tool_update.read_json(path))
            if release["version"] == VERSION:
                # First-run offline verification can unlock an existing deployment.
                self.job(lambda: tool_update.prepare_offline(ROOT, path, VERSION), "prepared")
            else:
                from workbench_updates import update_all
                self.content_busy = True
                self.job(lambda: update_all(ROOT, self.settings_path, VERSION, offline_manifest=path,
                    report=lambda message: self.update_events.put(("update_progress", message, None))), "combined")
        except Exception as exc:
            messagebox.showinfo("暂时无法更新", str(exc), parent=self.root)

    def poll_events(self):
        super().poll_events()
        if self.destroyed:
            return
        if self.engineer_process is not None and self.engineer_process.poll() is not None:
            code = self.engineer_process.returncode
            self.engineer_process = None
            new = load_settings(self.settings_path)
            if new.get("publish_dir") != self.settings.get("publish_dir"):
                type(self).restart_requested = True
                self.close(force=True, reason="publish-directory-changed")
                return
            self.settings = new
            if code:
                messagebox.showerror("维护窗口异常退出", "请查看日志：" + str(self.settings_path.parent / "logs/engineer-startup.log"), parent=self.root)
            self.check_update()
        try:
            while True:
                kind, value, error = self.update_events.get_nowait()
                if kind == "update_progress":
                    self.update_message = value
                    self.render_updates()
                    continue
                self.update_busy = False
                self.content_busy = False
                if error:
                    self.update_checked = False
                    self.update_message = "版本检查或更新未完成；请重试或导入离线包。"
                    self.update_detail = error
                elif kind == "checked":
                    release, newer = value
                    self.release = release
                    self.update_checked = not newer
                    self.update_message = "发现新版本 {}，更新后方可使用。".format(release["version"]) if newer else "当前版本已确认，可以使用。"
                    self.update_detail = release["notes"]
                elif kind == "combined":
                    record = value["program_record"]
                    if record and (record.get("replace_program") or record["version"] != VERSION):
                        try:
                            self.safe_to_maintain()
                            tool_update.launch_update_helper(ROOT)
                            self.close(force=True, reason="program-update")
                            return
                        except Exception as exc:
                            tool_update.recover_update(ROOT)
                            self.update_checked = False
                            self.update_message = "应用文件已更新，启动器更新未完成，请重试。"
                            self.update_detail = str(exc)
                    else:
                        if record:
                            tool_update.recover_update(ROOT)
                        self.update_checked = True
                        self.update_message = "程序与应用文件已更新，可以使用。"
                        self.update_detail = ""
                        self.status.set(self.update_message)
                elif kind == "prepared":
                    if value["version"] == VERSION:
                        tool_update.recover_update(ROOT)
                        self.release = None
                        self.update_checked = True
                        self.update_message = "已通过离线安装包验证当前版本，可以使用。"
                        self.update_detail = ""
                    else:
                        try:
                            self.safe_to_maintain()
                            tool_update.launch_update_helper(ROOT)
                            self.close(force=True, reason="program-update")
                            return
                        except Exception as exc:
                            tool_update.recover_update(ROOT)
                            self.update_detail = str(exc)
                            self.update_message = "程序尚未更新，请停止运行中的任务后重试。"
                self.render_updates()
                if kind == "checked" and not error and self.update_requested:
                    self.update_requested = False
                    self.download_update()
                if not self.update_checked and self.engineer_process is None:
                    self.open_updates()
        except queue.Empty:
            pass
        if self.blocked() and not self.busy:
            self.start_button.configure(state="disabled")
        elif not self.busy and not self.config_busy and not self.status_error:
            self.start_button.configure(state="normal", text="启动")
        if self.settings_dialog is not None and self.settings_dialog.window.winfo_exists():
            self.settings_dialog.config_panel.set_running(self.busy or self.blocked())

    def open_updates(self):
        if self.update_dialog is not None and self.update_dialog.winfo_exists():
            self.update_dialog.lift()
            return
        colors = palette(self.theme)
        window = self.update_dialog = tk.Toplevel(self.root)
        window.title("AIoT 工作台 · 程序更新")
        window.geometry("620x330")
        window.transient(self.root)
        def close_dialog():
            self.update_requested = False
            if not self.content_busy:
                window.destroy()
        window.protocol("WM_DELETE_WINDOW", close_dialog)
        window.configure(background=colors["sidebar"], padx=24, pady=22)
        tk.Label(window, text="AIoT 工作台  " + VERSION, font=(self.family, 17, "bold"), bg=colors["sidebar"], fg=colors["text"]).pack(anchor="w")
        self.update_label = tk.Label(window, wraplength=565, justify="left", bg=colors["sidebar"], fg=colors["text"], font=(self.family, 11))
        self.update_label.pack(fill="x", pady=(18, 8))
        self.update_note = tk.Label(window, wraplength=565, justify="left", bg=colors["sidebar"], fg=colors["muted"], font=(self.family, 10))
        self.update_note.pack(fill="both", expand=True)
        actions = tk.Frame(window, bg=colors["sidebar"])
        actions.pack(fill="x", pady=(14, 0))
        self.check_btn = tk.Button(actions, text="检查更新 / 重试", command=self.check_update)
        self.check_btn.pack(side="left")
        self.apply_btn = tk.Button(actions, text="立即更新", command=self.download_update)
        self.apply_btn.pack(side="left", padx=10)
        self.offline_btn = tk.Button(actions, text="导入离线包", command=self.offline_update)
        self.offline_btn.pack(side="left")
        self.render_updates()

    def render_updates(self):
        if self.update_dialog is None or not self.update_dialog.winfo_exists():
            return
        self.update_label.configure(text=self.update_message)
        self.update_note.configure(text=self.update_detail)
        available = not self.update_busy and self.engineer_process is None and not self.content_busy
        self.check_btn.configure(state="normal" if available else "disabled")
        self.offline_btn.configure(state="normal" if available else "disabled")
        self.apply_btn.configure(state="normal" if available and (self.release or self.update_checked) else "disabled")

    def close(self, force=False, reason="window-close"):
        if self.content_busy:
            self.status.set("请先等待文件更新结束，或在更新窗口取消准备。")
            return
        if self.engineer_process is not None:
            self.status.set("请先关闭工程师面板，再退出工作台。")
            return
        if self.update_busy:
            self.status.set("请等待程序版本检查或下载完成后再退出。")
            return
        return super().close(force=force, reason=reason)
