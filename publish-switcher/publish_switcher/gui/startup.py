"""Startup progress window. Tk stays on the main thread."""
import copy
import time
import tkinter as tk
from tkinter import ttk

from publish_switcher.updates import startup, unified
from publish_switcher.version import VERSION
from publish_switcher.gui.widgets.icons import WM_CLASS


class StartupWindow:
    BACKGROUND = "#172333"
    FOREGROUND = "#edf4fb"
    WIDTH, HEIGHT = 430, 200

    def __init__(self, app):
        self.app = app
        self.running = self.cancellable = False
        self.sample = None
        self.window = tk.Toplevel(app.root, class_=WM_CLASS)
        self.window.withdraw()
        self.window.transient("")
        if self.window.tk.call("tk", "windowingsystem") == "x11":
            # The hidden application root must not be the splash's group leader.
            self.window.wm_group(self.window)
            self.window.wm_attributes("-type", "normal")
        self.window.title("swicher")
        self.window.configure(background=self.BACKGROUND)
        self.window.resizable(False, False)
        x = max(0, (self.window.winfo_screenwidth() - self.WIDTH) // 2)
        y = max(0, (self.window.winfo_screenheight() - self.HEIGHT) // 2)
        self.window.geometry(f"{self.WIDTH}x{self.HEIGHT}+{x}+{y}")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        box = tk.Frame(self.window, background=self.BACKGROUND, padx=24, pady=18)
        box.pack(fill="both", expand=True)
        self.label(box, "程序更新", size=16).pack(anchor="w")
        self.message = self.label(box, "", size=11)
        self.message.pack(anchor="w", pady=(12, 8))
        style = ttk.Style(self.window)
        style.configure("Startup.Horizontal.TProgressbar", background="#6acaba", troughcolor="#33465a",
                        lightcolor="#6acaba", darkcolor="#6acaba", borderwidth=0, thickness=6)
        self.progress = ttk.Progressbar(box, style="Startup.Horizontal.TProgressbar")
        self.progress.pack(fill="x")
        self.details = self.label(box, "", color="#b9cadc")
        self.details.pack(fill="x", pady=(8, 0))
        self.actions = tk.Frame(box, background=self.BACKGROUND)
        self.actions.pack(side="bottom", fill="x")
        self.cancel_button = ttk.Button(self.actions, text="取消", command=self.close)

    def show(self, begin):
        def mapped(event):
            if event.widget is self.window:
                self.window.unbind("<Map>", binding)
                self.app.program_view.program_check_id = self.window.after_idle(begin)

        binding = self.window.bind("<Map>", mapped, add="+")
        self.window.deiconify()
        self.window.lift()

    def label(self, parent, text, size=10, color=FOREGROUND):
        return tk.Label(parent, text=text, font=(self.app.font_family, size),
                        background=self.BACKGROUND, foreground=color, anchor="w")

    def start(self, resume=False):
        if self.running:
            return
        self.running, self.cancellable = True, not resume
        self.sample = None
        self.app.quick_committing.clear()
        for child in self.actions.winfo_children():
            if child is not self.cancel_button:
                child.destroy()
        self.cancel_button.configure(state="normal" if self.cancellable else "disabled")
        self.cancel_button.pack(side="right")
        self.message.configure(text="正在完成更新…" if resume else "正在连接…")
        self.details.configure(text="")
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(15)
        app = self.app
        target, settings_path = app.target.get().strip(), app.settings_file
        if resume:
            app.run(lambda: startup.resume_startup_update(app.install_directory, VERSION, target, settings_path),
                    self.finish, cancellable=False, system_update=True)
            return
        try:
            values = dict(install=app.install_directory, current=VERSION, target=target,
                          repositories=app.settings_view.repository_list(), presets=copy.deepcopy(app.presets),
                          extensions=list(app.file_extensions), release_url=app.program_source.get().strip(),
                          profile_id=app.quick_profile.get().strip(), sync_permissions=app.sync_permissions.get(),
                          cancel=app.cancel, settings_path=settings_path)
        except Exception as exc:
            failure = dict(success=False, error=str(exc))
            app.run(lambda: startup.include_local_option(failure, app.install_directory, VERSION, target, settings_path),
                    self.finish, cancellable=False, system_update=True)
            return

        def event(value):
            if value["phase"] in ("publish-commit", "prepared"):
                app.quick_committing.set()
            app.events.put(("startup_progress", value))

        app.run(lambda: startup.run_startup_update(event=event, **values), self.finish,
                cancellable=False, system_update=True)

    def update(self, value):
        app = self.app
        self.cancellable = value["cancellable"] and not app.cancel.is_set() and not app.quick_committing.is_set()
        self.cancel_button.configure(state="normal" if self.cancellable else "disabled")
        if app.cancel.is_set() and value["cancellable"]:
            return
        phase = value["phase"]
        captions = {
            "checking": "正在连接…", "connected": "连接成功", "preparing": "正在下载程序…",
            "publish": "正在更新文件…", "publish-download": "正在下载文件…",
            "publish-commit": "正在应用更新…", "prepared": "正在重启…",
        }
        if phase == "publish" and self.sample and self.sample[0] == "publish-download":
            # Per-file log lines do not replace an active transfer display.
            return
        if phase not in captions:
            return
        self.message.configure(text=captions[phase])
        total = value.get("total", 0)
        if total:
            now = time.monotonic()
            received = min(value["received"], total)
            previous = self.sample
            speed = 0
            if previous and previous[0] == phase and not value.get("reset") and received >= previous[1]:
                speed = (received - previous[1]) / max(0.001, now - previous[2])
            self.sample = (phase, received, now)
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=total, value=received)
            rate = f" · {speed / 1024:.0f} KiB/s" if speed else ""
            self.details.configure(text=f"{received / 2**20:.1f} / {total / 2**20:.1f} MiB{rate}")
        else:
            self.sample = None
            if str(self.progress["mode"]) != "indeterminate":
                self.progress.configure(mode="indeterminate", value=0)
                self.progress.start(15)
            self.details.configure(text="")

    def finish(self, result):
        self.running = False
        self.progress.stop()
        self.cancel_button.pack_forget()
        self.details.configure(text="")
        app = self.app
        if result["success"]:
            if result.get("restart"):
                self.message.configure(text="正在重启…")
                try:
                    unified.start_restart(app.install_directory, result, startup=True)
                except Exception as exc:
                    app.logger.exception("启动更新助手失败")
                    result["success"] = False
                    result.setdefault("error", str(exc))
                else:
                    app.root.after_idle(app.root.destroy)
                    return
            else:
                changed = "更新成功" in (result.get("publish"), result.get("program"))
                self.message.configure(text="更新成功" if changed else "已是最新版本")
                self.progress.configure(mode="determinate", maximum=1, value=1)
                self.window.after(650, lambda: self.open_main(result.get("target"), result.get("channel"),
                                                             checked_at=result.get("program_checked_at")))
                return
        self.progress.pack_forget()
        status = "更新失败"
        if result.get("cancelled"):
            status = "已取消更新"
        elif result.get("retry_source") and not result.get("program_checked_at"):
            status = "连接失败"
        self.message.configure(text=status)
        error = result.get("error", "")
        if result.get("local_error") and result["local_error"] not in error:
            error += "\n" + result["local_error"]
        app.logger.info("启动更新结果：%s", error)
        for caption, command in (("退出", app.root.destroy), ("重试", self.retry)):
            ttk.Button(self.actions, text=caption, command=command).pack(side="right", padx=(6, 0))
        if result.get("local_target"):
            ttk.Button(self.actions, text="使用现有版本",
                       command=lambda: self.open_main(result["local_target"], result.get("channel"), offline=True),
                       style="Primary.TButton").pack(side="right")

    def retry(self):
        self.progress.pack(fill="x", before=self.details)
        self.start()

    def open_main(self, target=None, channel=None, *, offline=False, checked_at=None):
        app = self.app
        self.window.destroy()
        app.startup_window = None
        app.program_checked = True
        if target:
            app.target.set(target)
        view = app.program_view
        if channel is not None:
            app.update_channel.set(channel)
            if view.channel_picker is not None:
                view.channel_picker.current(channel)
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(checked_at)) if checked_at else None
        if timestamp:
            view.channel_check_times[view.program_channel()[1]] = timestamp
        view.version_banner.set_state("error" if offline else "current", timestamp)
        view.program_status.set("使用现有版本" if offline else "已是最新版本")
        app.configure_access()
        app.pages.select(app.config_page if target else app.program_page)
        app.root.deiconify()
        if target:
            app.connect()

    def close(self):
        if self.running:
            if self.cancellable and not self.app.quick_committing.is_set():
                self.app.cancel.set()
                self.cancel_button.configure(state="disabled")
                self.message.configure(text="正在取消…")
        else:
            self.app.root.destroy()
