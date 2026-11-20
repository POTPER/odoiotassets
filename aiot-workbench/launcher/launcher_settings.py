"""Small modal settings window with live theme preview and explicit save."""
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import hmac

from launcher_style import palette
from core import SyncError


class SettingsPasswordDialog(simpledialog.Dialog):
    def __init__(self, parent, theme, family):
        self.colors, self.family = palette(theme), family
        self.auth_parent, self.center_job = parent, None
        super().__init__(parent, title="设置验证")

    def body(self, master):
        colors = self.colors
        self.configure(background=colors["bg"])
        self.bind("<Map>", self.on_map, add="+")
        master.configure(background=colors["bg"], padx=20, pady=16)
        tk.Label(master, text="请输入设置密码", background=colors["bg"], foreground=colors["text"],
                 font=(self.family, 12, "bold")).pack(anchor="w", pady=(0, 12))
        self.entry = tk.Entry(master, show="*", width=28, font=(self.family, 12), relief="flat", bd=7,
                              background=colors["sidebar"], foreground=colors["text"],
                              insertbackground=colors["text"])
        self.entry.pack(fill="x")
        self.error = tk.StringVar(master=self, value="")
        tk.Label(master, textvariable=self.error, background=colors["bg"], foreground="#d66a62",
                 font=(self.family, 10)).pack(anchor="w", pady=(8, 0))
        return self.entry

    def buttonbox(self):
        colors = self.colors
        row = tk.Frame(self, background=colors["bg"], padx=20, pady=12)
        row.pack(fill="x")
        tk.Button(row, text="确定", command=self.ok, relief="flat", padx=22, pady=6,
                  background=colors["primary"], foreground=colors["primary_text"],
                  activebackground=colors["primary"], activeforeground=colors["primary_text"]).pack(side="right")
        tk.Button(row, text="取消", command=self.cancel, relief="flat", padx=18, pady=6,
                  background=colors["selected"], foreground=colors["text"],
                  activebackground=colors["selected"], activeforeground=colors["text"]).pack(side="right", padx=(0, 8))
        self.bind("<Return>", self.ok)
        self.bind("<Escape>", self.cancel)

    def validate(self):
        entered = self.entry.get()
        self.entry.delete(0, "end")
        if not hmac.compare_digest(entered.encode("utf-8"), b"root"):
            self.error.set("密码不正确，请重试。")
            return False
        return True

    def apply(self):
        self.result = True

    def on_map(self, event):
        if event.widget is self:
            if self.center_job is not None:
                self.after_cancel(self.center_job)
            self.center_job = self.after_idle(self.center)

    def center(self):
        self.center_job = None
        if not self.winfo_exists():
            return
        self.update_idletasks()
        width = self.winfo_width() if self.winfo_width() > 1 else self.winfo_reqwidth()
        height = self.winfo_height() if self.winfo_height() > 1 else self.winfo_reqheight()
        border_x = self.winfo_rootx() - self.winfo_x()
        border_y = self.winfo_rooty() - self.winfo_y()
        parent = self.auth_parent
        if parent is not None and parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        else:
            x = (self.winfo_screenwidth() - width) // 2
            y = (self.winfo_screenheight() - height) // 2
        self.geometry("{:+d}{:+d}".format(x - border_x, y - border_y))
        self.lift()
        self.entry.focus_set()

    def cancel(self, event=None):
        if self.center_job is not None:
            self.after_cancel(self.center_job)
            self.center_job = None
        super().cancel(event)


def request_settings_access(parent, theme, family):
    return SettingsPasswordDialog(parent, theme, family).result is True


class SettingsDialog:
    def __init__(self, parent, directory, theme, family, on_save, on_preview, settings=None,
                 on_config_refresh=None, on_config_replace=None, running=False, on_config_clear=None):
        self.on_save, self.on_preview = on_save, on_preview
        self.original_theme = theme
        self.family = family
        self.window = tk.Toplevel(parent)
        self.window.title("设置")
        self.window.transient(parent)
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self.cancel)
        self.directory = tk.StringVar(master=self.window, value=str(directory))
        self.theme = tk.StringVar(master=self.window, value=theme)
        settings = settings or {}
        self.submission_enabled = tk.BooleanVar(master=self.window, value=settings.get("submission_enabled", False) is True)
        self.submission_dir = tk.StringVar(master=self.window, value=settings.get("submission_dir", ""))
        self.notebook = ttk.Notebook(self.window, style="Settings.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.body = tk.Frame(self.notebook, padx=24, pady=12)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(8, weight=1)
        self.notebook.add(self.body, text="常规")
        from config_panel import ConfigPanel
        self.config_panel = ConfigPanel(self.notebook, family, on_config_refresh, on_config_replace, on_config_clear)
        self.notebook.add(self.config_panel, text="切换赛题")
        self.config_panel.set_running(running)
        self.notebook.bind("<<NotebookTabChanged>>", self.tab_changed)
        self.title = tk.Label(self.body, text="常规", font=(family, 15, "bold"))
        self.title.grid(row=0, column=0, sticky="w")
        self.folder_label = tk.Label(self.body, text="成果文件夹", font=(family, 10))
        self.folder_label.grid(row=1, column=0, sticky="w", pady=(14, 6))
        self.folder_row = tk.Frame(self.body)
        self.folder_row.grid(row=2, column=0, sticky="ew")
        self.entry = tk.Entry(self.folder_row, textvariable=self.directory, width=1, font=(family, 10), relief="flat", bd=6)
        self.entry.pack(side="left", fill="x", expand=True)
        self.browse = tk.Button(self.folder_row, text="浏览…", command=self.choose_folder, relief="flat", padx=12,
                                font=(family, 10))
        self.browse.pack(side="right", padx=(8, 0))
        self.theme_label = tk.Label(self.body, text="界面主题", font=(family, 10))
        self.theme_label.grid(row=3, column=0, sticky="w", pady=(18, 6))
        self.theme_row = tk.Frame(self.body)
        self.theme_row.grid(row=4, column=0, sticky="w")
        self.theme_buttons = []
        for label, value in (("深色 Dark", "dark"), ("浅色 Light", "light")):
            button = tk.Radiobutton(self.theme_row, text=label, value=value, variable=self.theme,
                                    command=self.preview, indicatoron=False, font=(family, 10),
                                    relief="flat", padx=18, pady=7, bd=0)
            button.pack(side="left", padx=(0, 8))
            self.theme_buttons.append(button)
        self.submission_toggle = tk.Checkbutton(self.body, text="启用成果提交", variable=self.submission_enabled,
                                                command=self.update_submission_state, font=(family, 10), bd=0)
        self.submission_toggle.grid(row=5, column=0, sticky="w", pady=(18, 6))
        self.submission_label = tk.Label(self.body, text="提交目标文件夹", font=(family, 10))
        self.submission_label.grid(row=6, column=0, sticky="w", pady=(0, 6))
        self.submission_row = tk.Frame(self.body)
        self.submission_row.grid(row=7, column=0, sticky="ew")
        self.submission_entry = tk.Entry(self.submission_row, textvariable=self.submission_dir,
                                        width=1, font=(family, 10), relief="flat", bd=6)
        self.submission_entry.pack(side="left", fill="x", expand=True)
        self.submission_browse = tk.Button(self.submission_row, text="浏览…", command=self.choose_submission_folder,
                                           relief="flat", padx=12, font=(family, 10))
        self.submission_browse.pack(side="right", padx=(8, 0))
        self.actions = tk.Frame(self.body)
        self.actions.grid(row=9, column=0, sticky="ew", pady=(16, 0))
        self.save_button = tk.Button(self.actions, text="保存", command=self.save, relief="flat", padx=24, pady=7,
                                     font=(family, 10))
        self.save_button.pack(side="right")
        self.cancel_button = tk.Button(self.actions, text="取消", command=self.cancel, relief="flat", padx=20, pady=7,
                                       font=(family, 10))
        self.cancel_button.pack(side="right", padx=(0, 8))
        self.apply_theme(theme)
        self.update_submission_state()
        # Reserve space for both pages once; changing tabs must never resize the window.
        # Use real font metrics so Linux DPI settings cannot push the footer off-screen.
        self.window.update_idletasks()
        width = max(660, self.notebook.winfo_reqwidth())
        height = max(500, self.notebook.winfo_reqheight())
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        self.window.geometry("{}x{}{:+d}{:+d}".format(width, height, max(0, x), max(0, y)))
        self.window.bind("<Escape>", lambda _: self.cancel())
        self.window.grab_set()

    def apply_theme(self, theme):
        colors = palette(theme)
        style = ttk.Style(self.window)
        style.configure("Settings.TNotebook", background=colors["bg"], borderwidth=0)
        style.configure("Settings.TNotebook.Tab", background=colors["sidebar"], foreground=colors["text"], padding=(20, 9),
                         font=(self.family, 10))
        # Clam maps selected-tab padding independently of configure(), changing
        # its dimensions. Override the inherited state map as well as the base.
        style.map("Settings.TNotebook.Tab", background=[("selected", colors["selected"])],
                   foreground=[("selected", colors["text"])],
                   padding=[("selected", (20, 9)), ("!selected", (20, 9))],
                   expand=[("selected", (0, 0, 0, 0)), ("!selected", (0, 0, 0, 0))])
        self.config_panel.apply_theme(theme)
        for frame in (self.window, self.body, self.folder_row, self.theme_row, self.submission_row, self.actions):
            frame.configure(background=colors["bg"])
        for label in (self.title, self.folder_label, self.theme_label, self.submission_label):
            label.configure(background=colors["bg"], foreground=colors["text"])
        for entry in (self.entry, self.submission_entry):
            entry.configure(background=colors["sidebar"], foreground=colors["text"], insertbackground=colors["text"],
                            disabledbackground=colors["selected"], disabledforeground=colors["muted"])
        self.submission_toggle.configure(background=colors["bg"], foreground=colors["text"],
                                         activebackground=colors["bg"], activeforeground=colors["text"],
                                         selectcolor=colors["sidebar"])
        for button in (self.browse, self.cancel_button, self.submission_browse):
            button.configure(background=colors["selected"], foreground=colors["text"],
                             activebackground=colors["border"], activeforeground=colors["text"],
                             disabledforeground=colors["muted"])
        for button in self.theme_buttons:
            button.configure(background=colors["sidebar"], foreground=colors["text"],
                             selectcolor=colors["selected"], activebackground=colors["selected"],
                             activeforeground=colors["text"])
        self.save_button.configure(background=colors["primary"], foreground=colors["primary_text"],
                                   activebackground=colors["primary"], activeforeground=colors["primary_text"])

    def choose_folder(self):
        from pathlib import Path
        initial = Path(self.directory.get()).expanduser()
        while not initial.is_dir() and initial != initial.parent:
            initial = initial.parent
        selected = filedialog.askdirectory(parent=self.window, title="选择成果文件夹", initialdir=str(initial))
        if selected:
            self.directory.set(selected)

    def preview(self):
        self.on_preview(self.theme.get())
        self.apply_theme(self.theme.get())

    def update_submission_state(self):
        state = "normal" if self.submission_enabled.get() else "disabled"
        self.submission_entry.configure(state=state)
        self.submission_browse.configure(state=state)

    def choose_submission_folder(self):
        from pathlib import Path
        initial = Path(self.submission_dir.get()).expanduser()
        while not initial.is_dir() and initial != initial.parent:
            initial = initial.parent
        selected = filedialog.askdirectory(parent=self.window, title="选择提交目标文件夹", initialdir=str(initial))
        if selected:
            self.submission_dir.set(selected)

    def save(self):
        if self.config_panel.busy:
            return
        try:
            self.on_save(self.directory.get(), self.theme.get(), self.submission_enabled.get(), self.submission_dir.get())
        except (OSError, ValueError, SyncError) as exc:
            messagebox.showerror("设置未保存", str(exc), parent=self.window)
            return
        self.window.destroy()

    def cancel(self):
        if self.config_panel.busy:
            return
        self.on_preview(self.original_theme)
        self.window.destroy()

    def tab_changed(self, event=None):
        if self.notebook.select() == str(self.config_panel) and not self.config_panel.loaded:
            self.config_panel.refresh()

    def set_config_busy(self, busy, action=None):
        self.config_panel.set_busy(busy, action)
        for button in (self.save_button, self.cancel_button):
            button.configure(state="disabled" if busy else "normal")
