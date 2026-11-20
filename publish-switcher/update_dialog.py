"""Compact progress window for the automatic update pipeline."""
import tkinter as tk
from tkinter import ttk

from switcher_style import style_dialog


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
        ttk.Label(box, text="更新 Switcher 与 publish", style="Title.TLabel").pack(anchor="w")
        self.message = tk.StringVar(value="正在检查更新…")
        ttk.Label(box, textvariable=self.message, wraplength=535).pack(fill="x", pady=(12, 6))
        self.progress = ttk.Progressbar(box, mode="indeterminate")
        self.progress.pack(fill="x", pady=6)
        self.summary = tk.StringVar(value="自动检查、下载和严格更新；无需手动刷新或比较。")
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
        self.retry = ttk.Button(self.actions, text="重试", command=app.start_quick_update)

    def exists(self):
        return bool(self.window.winfo_exists())

    def begin(self):
        self.running = True
        self.retry.pack_forget()
        self.action.configure(text="取消准备", state="normal", command=self.cancel)
        self.message.set("正在检查更新…")
        self.summary.set("自动检查、下载和严格更新；无需手动刷新或比较。")
        self.progress.configure(mode="indeterminate")
        self.progress.start(15)
        self.window.lift()

    def update(self, value):
        self.message.set(value["message"].replace("\n", " ")[:100])
        self.action.configure(state="normal" if value.get("cancellable", True) else "disabled")
        if "total" in value and value["total"]:
            self.progress.stop()
            self.progress.configure(mode="determinate", maximum=value["total"], value=value["received"])
            self.summary.set("程序下载 {:.1f} / {:.1f} MiB".format(value["received"] / 2**20, value["total"] / 2**20))
        elif str(self.progress["mode"]) != "indeterminate":
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
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
        self.message.set("更新完成" if result["success"] else "更新已取消" if result.get("cancelled") else "更新未完成")
        text = "publish：{}；Switcher：{}。".format(result["publish"], result["program"])
        if result.get("error"):
            text += "\n" + result["error"].split("\n")[0][:95] + "\n展开日志查看完整原因。"
        elif not result.get("restart"):
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
