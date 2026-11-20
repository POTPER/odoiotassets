"""Settings tab for choosing a local question bundle; no filesystem operations."""
import tkinter as tk
from tkinter import ttk

from launcher_style import palette


class ConfigPanel(tk.Frame):
    def __init__(self, parent, family, on_refresh, on_replace, on_clear=None):
        super().__init__(parent, padx=24, pady=20)
        self.on_refresh, self.on_replace = on_refresh, on_replace
        self.on_clear = on_clear
        self.busy, self.running, self.loaded = False, False, False
        self.rows = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.current = tk.StringVar(master=self, value="当前赛题：未读取")
        self.message = tk.StringVar(master=self, value="选择赛题后点击替换。")
        self.heading = tk.Label(self, textvariable=self.current, font=(family, 11, "bold"), anchor="w")
        self.heading.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self.heading.configure(wraplength=560, justify="left")
        self.table_frame = tk.Frame(self)
        self.table_frame.grid(row=1, column=0, sticky="nsew")
        self.table = ttk.Treeview(self.table_frame, columns=("version", "status"), show="headings",
                                  selectmode="browse", height=5, style="Question.Treeview")
        self.table.heading("version", text="赛题名称")
        self.table.heading("status", text="状态")
        self.table.column("version", width=360, minwidth=180)
        self.table.column("status", width=110, stretch=False)
        self.scrollbar = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="right", fill="y")
        self.table.pack(fill="both", expand=True)
        self.table.bind("<<TreeviewSelect>>", self.selection_changed)
        self.note = tk.Label(self, textvariable=self.message, font=(family, 10), anchor="w",
                              justify="left", wraplength=540, height=3)
        self.note.grid(row=2, column=0, sticky="ew", pady=(10, 8))
        self.actions = tk.Frame(self)
        self.actions.grid(row=3, column=0, sticky="ew")
        self.refresh_button = tk.Button(self.actions, text="刷新", command=self.refresh, relief="flat", padx=20, pady=7,
                                        font=(family, 10))
        self.refresh_button.pack(side="left")
        self.replace_button = tk.Button(self.actions, text="确认替换", command=self.replace, relief="flat", padx=24, pady=7,
                                        font=(family, 10))
        self.replace_button.pack(side="right")
        self.clear_button = tk.Button(self.actions, text="清除", command=self.clear, relief="flat", padx=20, pady=7,
                                      font=(family, 10))
        self.clear_button.pack(side="right", padx=(0, 8))
        self.family = family
        self.apply_theme("dark")
        self.update_controls()

    def selected(self):
        selection = self.table.selection()
        return self.rows.get(selection[0]) if selection else None

    def selection_changed(self, event=None):
        if self.busy or self.running:
            return
        item = self.selected()
        self.message.set("；".join(item["issues"]) if item and not item["valid"] else "")
        self.update_controls()

    def update_controls(self):
        available = not self.busy and not self.running
        self.refresh_button.configure(state="normal" if available and self.on_refresh else "disabled")
        self.clear_button.configure(state="normal" if available and self.on_clear else "disabled")
        item = self.selected()
        self.replace_button.configure(state="normal" if available and item and item["valid"] and self.on_replace else "disabled")
        self.table.state(("!disabled",) if available else ("disabled",))

    def set_running(self, running):
        changed = running != self.running
        self.running = running
        if changed and not self.busy:
            self.message.set("请先停止 AIoT，再切换赛题。" if running else "点击刷新读取赛题。")
        self.update_controls()

    def set_busy(self, busy, action=None):
        self.busy = busy
        if busy:
            self.message.set("正在替换…" if action == "replace" else "正在清除…" if action == "clear" else "正在读取…")
        self.update_controls()

    def refresh(self):
        if not self.busy and not self.running and self.on_refresh:
            self.on_refresh()

    def replace(self):
        item = self.selected()
        if not self.busy and not self.running and item and item["valid"] and self.on_replace:
            self.on_replace(item["version"])

    def clear(self):
        if not self.busy and not self.running and self.on_clear:
            self.on_clear()

    def receive(self, action, data):
        self.set_busy(False)
        if data.get("error"):
            self.message.set(data["error"])
            return
        self.current.set(data.get("current", "配置版本：自定义／未识别").replace("配置版本：", "当前赛题：", 1))
        if action == "list":
            previous = self.selected()
            previous = previous["version"] if previous else None
            self.table.delete(*self.table.get_children())
            self.rows = {}
            for index, item in enumerate(data["versions"]):
                key = str(index)
                self.rows[key] = item
                self.table.insert("", "end", iid=key, values=(item.get("display_name", item["version"]), "可用" if item["valid"] else "不可用"),
                                   tags=() if item["valid"] else ("invalid",))
                if item["version"] == previous:
                    self.table.selection_set(key)
            self.loaded = True
            self.message.set("" if self.rows else "publish/config 中没有赛题文件夹。")
        elif action == "clear":
            counts = data["cleanup"]
            self.message.set("已清除：target.py {} 个，student_data {} 个。".format(
                counts["target_files"], counts["student_data_dirs"]))
        else:
            self.message.set("已切换：" + data["version"])
        self.update_controls()

    def apply_theme(self, theme):
        colors = palette(theme)
        for frame in (self, self.table_frame, self.actions):
            frame.configure(background=colors["bg"])
        for label in (self.heading, self.note):
            label.configure(background=colors["bg"], foreground=colors["text"])
        self.refresh_button.configure(background=colors["selected"], foreground=colors["text"],
                                      activebackground=colors["border"], activeforeground=colors["text"],
                                      disabledforeground=colors["muted"])
        self.clear_button.configure(background=colors["selected"], foreground=colors["text"],
                                    activebackground=colors["border"], activeforeground=colors["text"],
                                    disabledforeground=colors["muted"])
        self.replace_button.configure(background=colors["primary"], foreground=colors["primary_text"],
                                      activebackground=colors["primary"], activeforeground=colors["primary_text"],
                                      disabledforeground=colors["muted"])
        style = ttk.Style(self)
        style.configure("Question.Treeview", background=colors["sidebar"], fieldbackground=colors["sidebar"],
                         foreground=colors["text"], rowheight=32, font=(self.family, 10), borderwidth=0)
        style.configure("Question.Treeview.Heading", background=colors["selected"], foreground=colors["text"],
                         font=(self.family, 10))
        style.map("Question.Treeview", background=[("selected", colors["selected"])],
                   foreground=[("selected", colors["text"])])
        self.table.tag_configure("invalid", foreground=colors["muted"])
