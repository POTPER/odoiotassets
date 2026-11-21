"""一键更新进度小窗。

显示检查、下载与应用阶段；可展开日志、取消准备阶段或失败后重试。
"""
import tkinter as tk
from tkinter import ttk

from publish_switcher.gui.widgets.style import style_dialog
from publish_switcher.updates.channels import channel_name


class UpdateDialog:
    def __init__(self, app):
        self.app = app
        self.running = False
        self.window = tk.Toplevel(app.root)
        style_dialog(self.window)
        self.window.title("程序更新")
        self.window.geometry("590x280")
        self.window.minsize(510, 280)
        self.window.transient(app.root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        box = ttk.Frame(self.window, padding=18)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="程序更新", style="Title.TLabel").pack(anchor="w")
        self.message = tk.StringVar(value="正在检查更新…")
        ttk.Label(box, textvariable=self.message, wraplength=535).pack(fill="x", pady=(12, 6))
        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.pack(fill="x", pady=6)
        self.summary = tk.StringVar(value=channel_name(app.update_channel.get()))
        ttk.Label(box, textvariable=self.summary, wraplength=535).pack(fill="x", pady=6)
        self.log = tk.Text(box, height=9, wrap="word", state="disabled")
        self.log.configure(state="normal")
        files = [handler.baseFilename for handler in app.logger.handlers if hasattr(handler, "baseFilename")]
        self.log.insert("end", "完整日志：" + (files[0] if files else "~/.config/publish-switcher/logs/switcher.log") + "\n")
        self.log.configure(state="disabled")
        self.log_open = False
        self.actions = ttk.Frame(box)
        self.actions.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(self.actions, text="展开日志", command=self.toggle_log).pack(side="left")
        self.action = ttk.Button(self.actions, text="取消准备", command=self.cancel)
        self.action.pack(side="right")
        self.retry = ttk.Button(self.actions, text="重试", command=app.program_view.start_quick_update)

    def exists(self):
        return bool(self.window.winfo_exists())

    def begin(self):
        self.running = True
        self.retry.pack_forget()
        self.action.configure(text="取消准备", state="normal", command=self.cancel)
        self.message.set("正在检查更新…")
        self.summary.set(channel_name(self.app.update_channel.get()))
        self.progress.configure(mode="indeterminate")
        self.progress.start(15)
        self.window.lift()

    def update(self, value):
        phases = {"checking": "检查更新…", "preparing": "下载 swicher…", "publish": "更新 publish…",
                  "publish-commit": "正在应用，请稍候…", "prepared": "准备重启…"}
        self.message.set(phases.get(value.get("phase"), value["message"].replace("\n", " ")[:100]))
        self.action.configure(state="normal" if value.get("cancellable", True) else "disabled")
        if "total" in value and value["total"]:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=value["total"], value=value["received"])
            self.summary.set("程序下载 {:.1f} / {:.1f} MiB".format(value["received"] / 2**20, value["total"] / 2**20))
        elif str(self.progress["mode"]) != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
            self.summary.set(channel_name(self.app.update_channel.get()))
        if "received" not in value:
            self.log.configure(state="normal")
            self.log.insert("end", value["message"] + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 600:
                self.log.delete("1.0", "100.0")
            self.log.see("end")
            self.log.configure(state="disabled")

    def finish(self, result):
        self.running = False
        self.progress.stop()
        self.progress.configure(mode="determinate", maximum=1, value=1 if result["success"] else 0)
        if result["success"] and result.get("publish_skipped") and not result.get("restart"):
            self.message.set("已是最新版本")
        else:
            self.message.set("更新完成" if result["success"] else "更新已取消" if result.get("cancelled") else "更新未完成")
        text = "publish：{}；swicher：{}。".format(result["publish"], result["program"])
        if result.get("error"):
            text += "\n" + result["error"].split("\n")[0][:95]
        elif not result.get("restart") and not result.get("publish_skipped"):
            text += "\n请重新启动主程序。"
        self.summary.set(text)
        self.action.configure(text="关闭", state="normal", command=self.close)
        if not result["success"]:
            self.retry.pack(side="right", padx=8)

    def toggle_log(self):
        self.log_open = not self.log_open
        if self.log_open:
            self.log.pack(fill="both", expand=True, before=self.actions, pady=6)
            self.window.geometry("590x480")
        else:
            self.log.pack_forget()
            self.window.geometry("590x280")

    def cancel(self):
        if not self.app.quick_committing.is_set():
            self.app.cancel.set()
            self.action.configure(state="disabled")
            self.message.set("正在取消，请等待安全结束…")

    def close(self):
        if self.running:
            self.cancel()
            return
        self.window.grab_release()
        self.window.destroy()
