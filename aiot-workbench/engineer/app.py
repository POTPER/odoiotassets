"""Chinese Tk desktop UI. All network and filesystem jobs run off the Tk thread."""
import json
import logging
import os
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from compat import is_relative_to

from core import (Cancelled, Engine, Source, SyncError, atomic_json, load_profile,
                  read_json, sync_blockers, validate_catalog)
from repository import (DEFAULT_PROFILES, DEFAULT_REPOSITORY, directory_manifest,
                        remote_profiles, validate_presets, repository_from_settings, REPOSITORY_DEFAULT_VERSION)
from file_compare import diagnose_file, format_report, comparison_self_test, visible_diff_line, format_diff
from config_versions import format_comparison
from assets_sync import AssetsEngine, format_preview as assets_report, format_details as assets_details
from permission_presets import PRESETS, command_text, launch_preset
from iot_runner import load_tasks, describe, task_name, run_selected, run_many, DemoError, DemoPreflightError, DemoQueueControl
from demo_cards import DemoGrid, PHASES, format_duration
from switcher_style import COLORS, NavButton, StatusBadge, apply_theme, rounded, style_dialog
from switcher_icon import WM_CLASS, load_icons
from file_formats import DEFAULT_EXTENSIONS, normalize_extensions, inventory, describe as describe_formats, label
from version import VERSION
import tool_update


CONFIG = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "publish-switcher" / "settings.json"
DEMO_RESULTS_EMPTY = "运行模块后，这里会显示状态、耗时和退出码。"


class Application:
    def __init__(self, root, engineer=True, updates=False):
        self.root = root
        self.engineer_mode = engineer
        self.updates_enabled = updates
        self.program_checked = not updates
        self.program_release = None
        self.program_checking = False
        self.install_directory = Path(__file__).resolve().parent
        self.logger = logging.getLogger("publish-switcher")
        if not self.logger.handlers:
            self.logger.addHandler(logging.NullHandler())
        root.title("Publish Switcher · 配置与资源管理")
        self.icons = load_icons(root)
        root.geometry("{}x{}".format(min(1240, max(900, root.winfo_screenwidth() - 80)),
                                          min(780, max(640, root.winfo_screenheight() - 100))))
        root.minsize(900, 640)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.last_error = False
        self.profiles = []
        self.engine = None
        self.selected = None
        self.source = None
        self.worker = None
        self.closing = False
        self.checked = None
        self.update_mode = tk.StringVar(value="incremental")
        self.config_preview = None
        self.config_refreshing = False
        self.demo_tasks = {}
        self.demo_running = False
        self.demo_active_ids = set()
        self.demo_control = None
        self.demo_current_id = None
        self.demo_order = []
        self.demo_timings = {}
        self.demo_started_at = None
        self.demo_finished_at = None
        self.demo_start_error = None
        self.demo_needs_refresh = False
        self.demo_log_entries = deque(maxlen=3000)
        self.demo_module_logs = {}
        self.demo_all_log = None
        self.demo_log_mode = tk.StringVar(value="全部日志")
        self.demo_log_title = tk.StringVar(value="开始运行后可在这里查看输出")
        self.demo_progress_text = tk.StringVar(value="尚未开始运行")
        self.demo_elapsed_text = tk.StringVar(value="总用时 00:00")
        self.assets_checked = None
        self.assets_profiles = []
        self.assets_summary = tk.StringVar(value="先选择资源方案，检查本地 Assets 与来源的差异。")
        self.demo_status = tk.StringVar(value="读取当前生效的 TrainTaskInfo.json，选择任务运行。")
        self.demo_log_path = tk.StringVar(value="运行后显示本次日志文件路径")
        try:
            config = read_json(CONFIG) if CONFIG.exists() else {}
        except (OSError, ValueError):
            config = {}
        self.sync_permissions = tk.BooleanVar(value=config.get("sync_permissions") is True)
        self.update_mode.set(config.get("update_mode") if config.get("update_mode") in ("incremental", "strict") else "incremental")
        self.program_source = tk.StringVar(value=config.get("program_update_url", tool_update.DEFAULT_UPDATE_URL))
        self.program_status = tk.StringVar(value="启动时将检查 Switcher 版本。")
        self.program_notes = tk.StringVar(value="")
        self.program_version_text = tk.StringVar(value="当前版本 " + VERSION)
        try:
            self.file_extensions = normalize_extensions(config.get("file_extensions"))
        except ValueError:
            self.file_extensions = DEFAULT_EXTENSIONS
        self.format_inventory = config.get("format_inventory", {})
        self.format_text = tk.StringVar(value="同步格式…（{} 种）".format(len(self.file_extensions)))
        self.target = tk.StringVar(value=config.get("target", ""))
        self.repo = tk.StringVar(value=repository_from_settings(config))
        self.branch = tk.StringVar(value=config.get("branch", ""))
        try:
            self.presets = validate_presets(config.get("directory_profiles", json.loads(json.dumps(DEFAULT_PROFILES))))
        except SyncError:
            self.presets = json.loads(json.dumps(DEFAULT_PROFILES))
        self.status = tk.StringVar(value="已预设 Jetson / RK 和资源仓库；选择 publish 目录后保存设置并刷新。")
        self.current = tk.StringVar(value="当前方案：未读取")
        self.task_mode = tk.StringVar(value="任务配置：未读取")
        self.build_layout()
        if updates:
            root.bind("<Control-Shift-F12>", self.toggle_engineer, add="+")
            self.configure_access()
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_id = root.after(100, self.poll)
        root.bind("<Destroy>", self.on_destroy, add="+")
        self.add_placeholders()
        self.show_profiles()
        self.tree.bind("<<TreeviewSelect>>", lambda event: self.invalidate_check())
        self.target.trace_add("write", lambda *args: self.publish_changed())
        self.repo.trace_add("write", lambda *args: self.invalidate_check())
        self.branch.trace_add("write", lambda *args: self.invalidate_check())
        self.update_ready()
        self.config_tree.bind("<<TreeviewSelect>>", lambda event: self.preview_config_selection())
        self.config_mapping.bind("<<TreeviewSelect>>", lambda event: self.update_ready())
        self.config_mapping.bind("<Double-1>", lambda event: self.compare_config_selection())
        self.diff_tree.bind("<<TreeviewSelect>>", lambda event: self.update_ready())
        self.demo_grid.bind("<<DemoSelect>>", self.demo_selection_changed)
        self.demo_grid.bind("<<DemoCheck>>", lambda event: self.update_ready())
        self.assets_tree.bind("<<TreeviewSelect>>", lambda event: self.update_ready())
        self.assets_combo.bind("<<ComboboxSelected>>", lambda event: self.invalidate_assets())
        self.pages.bind("<<NotebookTabChanged>>", self.page_changed)
        if updates and not engineer:
            self.pages.select(self.program_page)
            self.program_check_id = root.after(150, self.check_program_update)
        elif self.target.get():
            self.connect()
        elif engineer:
            self.pages.select(self.settings_page)

    def build_layout(self):
        self.controls = []
        self.engineer_widgets = []
        self.update_summary = tk.StringVar(value="尚未检查。请选择方案，再检查差异。")
        self.log_visible = False
        self.font_family = apply_theme(self.root)
        self.sidebar_compact = False
        self.sidebar = tk.Frame(self.root, background=COLORS["sidebar"], width=192)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self.root, background=COLORS["border"], width=1).pack(side="left", fill="y")
        self.brand = tk.Canvas(self.sidebar, height=94, background=COLORS["sidebar"], highlightthickness=0)
        self.brand.pack(fill="x")
        self.brand.bind("<Configure>", lambda event: self.draw_brand())
        self.nav_caption = tk.Label(self.sidebar, text="工作区", anchor="w", background=COLORS["sidebar"],
                                    foreground=COLORS["disabled"], font=(self.font_family, 8))
        self.nav_caption.pack(fill="x", padx=23, pady=(12, 8))
        self.nav_frame = tk.Frame(self.sidebar, background=COLORS["sidebar"])
        self.nav_frame.pack(fill="x", padx=8)
        self.sidebar_footer = tk.Frame(self.sidebar, background=COLORS["sidebar"])
        self.sidebar_footer.pack(side="bottom", fill="x", padx=20, pady=20)
        tk.Label(self.sidebar_footer, text="本地部署工具", background=COLORS["sidebar"], foreground=COLORS["text"],
                 font=(self.font_family, 9)).pack(anchor="w", pady=(0, 8))
        tk.Label(self.sidebar_footer, textvariable=self.current, background=COLORS["sidebar"], foreground=COLORS["muted"],
                 font=(self.font_family, 8), wraplength=150, justify="left").pack(anchor="w")
        self.workspace = ttk.Frame(self.root)
        self.workspace.pack(side="left", fill="both", expand=True)
        header = ttk.Frame(self.workspace, padding=(20, 12, 20, 8))
        self.header = header
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        self.page_title = tk.StringVar(value="更新文件")
        self.page_caption = tk.StringVar(value="勾选同步格式，比较差异，选择更新方式后应用。")
        self.heading_label = ttk.Label(header, textvariable=self.page_title, style="PageTitle.TLabel")
        self.heading_label.grid(row=0, column=0, sticky="w")
        self.phase_badge = StatusBadge(header, self.font_family)
        self.phase_badge.grid(row=0, column=1, sticky="e")
        self.caption_label = ttk.Label(header, textvariable=self.page_caption, style="Muted.TLabel")
        self.caption_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        location = ttk.Frame(self.workspace, padding=(20, 0, 20, 10))
        self.location_bar = location
        location.pack(fill="x")
        location.columnconfigure(0, weight=1)
        pathbar = ttk.Frame(location, style="Toolbar.TFrame", padding=(8, 3))
        pathbar.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        pathbar.columnconfigure(1, weight=1)
        ttk.Label(pathbar, text="PUBLISH", background=COLORS["panel"], foreground=COLORS["muted"],
                  font=(self.font_family, 8, "bold")).grid(row=0, column=0, padx=(4, 8))
        ttk.Entry(pathbar, textvariable=self.target, state="readonly", style="Path.TEntry").grid(row=0, column=1, sticky="ew")
        self.button(location, "目录设置", lambda: self.pages.select(self.settings_page)).grid(row=0, column=1)

        # Fixed actions stay available when lists or logs grow.
        footer = ttk.Frame(self.workspace, padding=(20, 4, 20, 8))
        footer.pack(side="bottom", fill="x")
        footer.columnconfigure(0, weight=1)
        self.progress = ttk.Progressbar(footer, mode="indeterminate")
        self.progress.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 5))
        self.status_label = ttk.Label(footer, textvariable=self.status, style="Muted.TLabel", wraplength=660)
        self.status_label.grid(row=1, column=0, sticky="w")
        self.log_button = ttk.Button(footer, text="展开日志", style="Quiet.TButton", command=self.toggle_log)
        self.log_button.grid(row=1, column=1, padx=8)
        self.cancel_button = ttk.Button(footer, text="取消准备", style="Quiet.TButton", command=self.cancel.set, state="disabled")
        self.cancel_button.grid(row=1, column=2)
        self.log_output = ttk.LabelFrame(self.workspace, text="操作日志", padding=6)
        self.text = tk.Text(self.log_output, wrap="word", state="disabled", height=3, padx=8, pady=4)
        self.text.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(self.log_output, command=self.text.yview)
        scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scroll.set)

        self.pages = ttk.Notebook(self.workspace, style="Workspace.TNotebook", takefocus=False)
        self.pages.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self.update_page = ttk.Frame(self.pages, padding=8)
        self.assets_page = ttk.Frame(self.pages, padding=8)
        self.config_page = ttk.Frame(self.pages, padding=8)
        self.demo_page = ttk.Frame(self.pages, padding=8)
        self.tools_page = ttk.Frame(self.pages, padding=12)
        self.settings_page = ttk.Frame(self.pages, padding=12)
        for page, name in ((self.update_page, "更新文件"), (self.assets_page, "Assets 资源"), (self.config_page, "配置切换"),
                           (self.demo_page, "IoT Demo"), (self.tools_page, "辅助工具"), (self.settings_page, "设置")):
            self.pages.add(page, text=name)
        self.build_update_page()
        self.build_assets_page()
        self.build_config_page()
        self.build_demo_page()
        self.build_tools_page()
        self.build_settings_page()
        if self.updates_enabled:
            self.program_page = ttk.Frame(self.pages, padding=12)
            self.pages.add(self.program_page, text="程序更新")
            self.build_program_page()
        self.nav_buttons = {}
        self.page_info = {}
        navigation = (
            (self.update_page, "更新文件", "文件", "update", "勾选同步格式，比较差异，选择更新方式后应用。"),
            (self.assets_page, "Assets 资源", "资源", "assets", "比较图片、视频等资源的内容，只补齐缺失文件。"),
            (self.config_page, "配置切换", "配置", "config", "查看 JSON 差异，一次应用所选版本的三个配置文件。"),
            (self.demo_page, "IoT Demo", "Demo", "demo", "按当前任务配置运行模块，在右侧查看日志和结果。"),
            (self.tools_page, "辅助工具", "工具", "tools", "维护文件权限、恢复备份与运行比较自测。"),
            (self.settings_page, "设置", "设置", "settings", "连接 publish 目录与资源仓库，管理平台方案。"),
        )
        if self.updates_enabled:
            navigation += ((self.program_page, "程序更新", "升级", "update", "检查 Switcher 版本，完成更新后使用。"),)
        for page, name, short, symbol, description in navigation:
            key = str(page)
            self.page_info[key] = (name, description)
            button = NavButton(self.nav_frame, name, short, symbol, lambda page=page: self.pages.select(page), self.font_family)
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button
        self.root.bind("<Configure>", self.resize_shell, add="+")
        self.workspace.bind("<Configure>", self.fit_content, add="+")
        self.pages.enable_traversal()
        self.sync_navigation()

    def set_engineer_widget(self, widget, visible):
        manager = widget.winfo_manager()
        if manager and not hasattr(widget, "_engineer_layout"):
            widget._engineer_layout = (manager, widget.pack_info() if manager == "pack" else widget.grid_info())
        if visible and hasattr(widget, "_engineer_layout"):
            manager, options = widget._engineer_layout
            if manager == "pack":
                if widget is self.location_bar:
                    options = dict(options, before=self.pages)
                widget.pack(**options)
            else:
                widget.grid(**options)
        elif not visible:
            if manager == "pack":
                widget.pack_forget()
            elif manager == "grid":
                widget.grid_remove()

    def configure_access(self):
        if not self.updates_enabled:
            return
        allowed = {str(self.program_page)}
        if self.engineer_mode or self.program_checked:
            allowed.update(str(page) for page in (self.update_page, self.config_page, self.demo_page))
        if self.engineer_mode:
            allowed.update(self.nav_buttons)
        for key, button in self.nav_buttons.items():
            if key in allowed:
                button.pack(fill="x", pady=2)
                self.pages.tab(key, state="normal")
            else:
                button.pack_forget()
                self.pages.hide(key)
        for widget in self.engineer_widgets + [self.location_bar]:
            self.set_engineer_widget(widget, self.engineer_mode)
        self.log_button.grid() if self.engineer_mode else self.log_button.grid_remove()
        if not self.engineer_mode:
            self.set_log_visible(False)
        self.diff_tree.configure(displaycolumns=("status", "path", "incremental", "strict", "permissions")
                                 if self.engineer_mode else ("status", "path"))
        self.config_tree.configure(displaycolumns=("version", "status", "issues") if self.engineer_mode else ("version", "status"))
        if self.pages.select() not in allowed:
            self.pages.select(self.config_page if self.program_checked else self.program_page)
        self.sync_navigation()

    def toggle_engineer(self, event=None):
        if self.busy:
            return "break"
        self.engineer_mode = not self.engineer_mode
        self.config_preview = None
        self.config_tree.delete(*self.config_tree.get_children())
        self.config_mapping.delete(*self.config_mapping.get_children())
        self.task_mode.set("配置版本：读取中")
        self.configure_access()
        self.pages.select(self.settings_page if self.engineer_mode else
                          self.config_page if self.program_checked else self.program_page)
        self.status.set("已进入工程师面板。" if self.engineer_mode else "已返回用户界面。")
        return "break"

    def build_update_page(self):
        page = self.update_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(page)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.button(toolbar, "刷新远端方案", self.refresh).pack(side="left")
        self.button(toolbar, "导入本地方案", self.import_local).pack(side="left", padx=6)
        maintenance = self.button(toolbar, "权限预设 / 恢复", lambda: self.pages.select(self.tools_page))
        maintenance.pack(side="right")
        self.formats_button = self.button(toolbar, "同步格式…", self.read_formats)
        self.formats_button.configure(textvariable=self.format_text)
        self.formats_button.pack(side="right", padx=8)
        self.engineer_widgets.extend((maintenance, self.formats_button))

        self.update_pane = ttk.Panedwindow(page, orient="vertical")
        self.update_pane.grid(row=1, column=0, sticky="nsew")
        schemes = ttk.LabelFrame(self.update_pane, text="1. 选择资源方案", padding=4)
        self.tree = ttk.Treeview(schemes, columns=("name", "version", "cached"), show="headings", height=2, selectmode="browse")
        for key, title, width in (("name", "方案名称", 160), ("version", "版本", 180), ("cached", "方案清单缓存", 360)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=100, stretch=True)
        self.scrollable_tree(schemes, self.tree)
        self.update_pane.add(schemes, weight=1)

        differences = ttk.LabelFrame(self.update_pane, text="2. 检查差异", padding=4)
        actions = ttk.Frame(differences)
        actions.pack(fill="x", pady=(0, 5))
        self.check_button = self.button(actions, "检查所选方案", self.preview)
        self.check_button.pack(side="left")
        self.diagnose_button = self.button(actions, "查看选中文件差异", self.diagnose_selected)
        self.diagnose_button.pack(side="left", padx=6)
        ttk.Label(actions, text="绿色：无需更新", foreground=COLORS["green"]).pack(side="right")
        holder = ttk.Frame(differences)
        holder.pack(fill="both", expand=True)
        self.diff_tree = ttk.Treeview(holder, columns=("status", "path", "incremental", "strict", "permissions"), show="headings", height=6)
        self.diff_tree.tag_configure("same", foreground=COLORS["green"], background=COLORS["green_bg"])
        self.diff_tree.tag_configure("permission", foreground=COLORS["amber"], background=COLORS["amber_bg"])
        self.diff_tree.tag_configure("different", foreground=COLORS["red"], background=COLORS["red_bg"])
        for key, title, width in (("status", "比较结果", 100), ("path", "相对路径", 260), ("incremental", "增量处理", 80),
                                  ("strict", "严格处理", 80), ("permissions", "权限：本地 / 仓库", 220)):
            self.diff_tree.heading(key, text=title)
            self.diff_tree.column(key, width=width, minwidth=70, stretch=key == "path")
        self.scrollable_tree(holder, self.diff_tree, horizontal=True)
        self.update_pane.add(differences, weight=3)

        policy = ttk.LabelFrame(page, text="3. 选择方式并更新", padding=6)
        policy.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        policy.columnconfigure(0, weight=1)
        choices = ttk.Frame(policy)
        choices.grid(row=0, column=0, sticky="w")
        self.mode_buttons = []
        for value, text in (("incremental", "增量：只补缺失，保留已有和多余文件"),
                            ("strict", "严格：替换差异，删除所选格式的多余文件")):
            button = ttk.Radiobutton(choices, text=text, variable=self.update_mode, value=value, command=self.mode_changed)
            button.pack(side="left", padx=(0, 12))
            self.mode_buttons.append(button)
        self.permissions_button = ttk.Checkbutton(policy, text="严格更新同时同步仓库权限（默认保留本地权限）",
                                                 variable=self.sync_permissions, command=self.permissions_changed)
        self.permissions_button.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.controls.append(self.permissions_button)
        self.engineer_widgets.extend((choices, self.permissions_button))
        policy_caption = ttk.Frame(policy)
        ttk.Label(policy_caption, text="3. 更新方式", style="Section.TLabel").pack(side="left")
        self.summary_label = ttk.Label(policy_caption, textvariable=self.update_summary, style="Muted.TLabel", wraplength=650)
        self.summary_label.pack(side="left", padx=(12, 0))
        policy.configure(labelwidget=policy_caption)
        self.apply_button = self.button(policy, "执行更新", self.apply)
        self.apply_button.configure(style="Primary.TButton")
        self.apply_button.grid(row=1, column=1, padx=(10, 0), sticky="e")

    def draw_brand(self):
        self.brand.delete("all")
        compact = self.sidebar_compact
        x = 19 if compact else 21
        if 32 in self.icons:
            self.brand.create_image(x, 27, image=self.icons[32], anchor="nw", tags="app-icon")
        else:
            rounded(self.brand, x, 27, x + 32, 59, radius=7, fill=COLORS["primary"], outline="")
            self.brand.create_text(x + 16, 43, text="AW", fill=COLORS["bg"], font=(self.font_family, 10, "bold"))
        if not compact:
            self.brand.create_text(66, 36, text="工作台", anchor="w", fill=COLORS["text"], font=(self.font_family, 16, "bold"))
            self.brand.create_text(67, 57, text="AIoT WORKSPACE", anchor="w", fill=COLORS["muted"], font=(self.font_family, 7))

    def sync_navigation(self):
        key = self.pages.select()
        if key in self.page_info:
            title, description = self.page_info[key]
            self.page_title.set(title)
            self.page_caption.set(description)
        for page, button in self.nav_buttons.items():
            button.set_selected(page == key)

    def resize_shell(self, event):
        if event.widget is not self.root:
            return
        compact = event.width < 1120
        if compact != self.sidebar_compact:
            self.sidebar_compact = compact
            self.sidebar.configure(width=70 if compact else 192)
            self.nav_caption.configure(text="功能" if compact else "工作区")
            self.nav_caption.pack_configure(padx=19 if compact else 23)
            if compact:
                self.sidebar_footer.pack_forget()
            else:
                self.sidebar_footer.pack(side="bottom", fill="x", padx=20, pady=20)
            for button in self.nav_buttons.values():
                button.set_compact(compact)
            self.header.configure(padding=(16, 4, 16, 2) if compact else (20, 12, 20, 8))
            self.heading_label.configure(style="CompactTitle.TLabel" if compact else "PageTitle.TLabel")
            if compact:
                self.caption_label.grid_remove()
            else:
                self.caption_label.grid()
            self.location_bar.configure(padding=(16, 0, 16, 6) if compact else (20, 0, 20, 10))
            self.text.configure(height=2 if compact else 3)
            self.draw_brand()

    def fit_content(self, event):
        if event.widget is not self.workspace:
            return
        width = max(300, event.width - 55)
        if getattr(self, "_last_content_width", None) == width:
            return
        self._last_content_width = width
        self.status_label.configure(wraplength=max(220, width - 205))
        self.summary_label.configure(wraplength=max(220, width - 210))
        # Long paths and descriptions wrap inside the content area rather than moving actions off-screen.
        def fit(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label) and child.cget("wraplength"):
                    current = str(child.cget("wraplength"))
                    if not hasattr(child, "_preferred_wrap"):
                        child._preferred_wrap = int(float(current))
                    child.configure(wraplength=min(child._preferred_wrap, width))
                fit(child)
        for page in (self.assets_page, self.config_page, self.demo_page, self.tools_page, self.settings_page):
            fit(page)

    def build_assets_page(self):
        page = self.assets_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text="只下载 Assets 内缺失的普通文件；已有文件（含空文件和内容不同）跳过，多余资源保留。",
                  wraplength=820).grid(row=0, column=0, sticky="w", pady=(0, 8))
        choices = ttk.Frame(page)
        choices.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        choices.columnconfigure(1, weight=1)
        ttk.Label(choices, text="资源方案").grid(row=0, column=0, padx=(0, 8))
        self.assets_combo = ttk.Combobox(choices, state="readonly", width=34)
        self.assets_combo.grid(row=0, column=1, sticky="ew")
        self.controls.append(self.assets_combo)
        self.button(choices, "刷新远端方案", self.refresh, row=0, column=2)
        self.button(choices, "导入本地方案", self.import_local, row=0, column=3)
        table = ttk.LabelFrame(page, text="大小与内容哈希比较 · 相同文件绿色，增量仅补缺失", padding=6)
        table.grid(row=2, column=0, sticky="nsew")
        self.assets_tree = ttk.Treeview(table, columns=("status", "path", "local", "remote", "action", "cached"), show="headings", height=9, selectmode="browse")
        for key, title, width in (("status", "比较结果", 100), ("path", "资源相对路径", 300), ("local", "本地字节", 95),
                                  ("remote", "来源字节", 95), ("action", "增量处理", 80), ("cached", "完整缓存", 80)):
            self.assets_tree.heading(key, text=title)
            self.assets_tree.column(key, width=width, minwidth=65, stretch=key == "path")
        self.assets_tree.tag_configure("same", foreground=COLORS["green"], background=COLORS["green_bg"])
        self.assets_tree.tag_configure("different", foreground=COLORS["red"], background=COLORS["red_bg"])
        self.assets_tree.tag_configure("local", foreground=COLORS["muted"])
        self.scrollable_tree(table, self.assets_tree, horizontal=True)
        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky="ew", pady=8)
        self.assets_check_button = self.button(actions, "1. 检查资源差异", self.preview_assets)
        self.assets_check_button.pack(side="left")
        self.assets_details_button = self.button(actions, "查看资源校验信息", self.show_assets_details)
        self.assets_details_button.pack(side="left", padx=8)
        self.assets_apply_button = self.button(actions, "2. 下载缺失资源", self.download_assets)
        self.assets_apply_button.configure(style="Primary.TButton")
        self.assets_apply_button.pack(side="right")
        ttk.Label(page, textvariable=self.assets_summary, wraplength=820).grid(row=4, column=0, sticky="w")
        ttk.Label(page, text="大文件下载完成后校验；失败或取消不应用部分资源。此页只补缺失，不受文件格式勾选影响。",
                  wraplength=820).grid(row=5, column=0, sticky="w", pady=(5, 0))

    def build_config_page(self):
        page = self.config_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        ttk.Label(page, text="选择本机 config 中的版本，将整套三个 JSON 复制到 publish 根目录。",
                  style="Section.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        actions = ttk.Frame(page)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.button(actions, "刷新版本列表", self.refresh_config_choices).pack(side="left")
        visibility = self.button(actions, "版本显示设置", self.edit_config_visibility)
        visibility.pack(side="right")
        self.engineer_widgets.append(visibility)
        ttk.Label(actions, textvariable=self.task_mode).pack(side="left", padx=12)
        versions = ttk.LabelFrame(page, text="1. 选择版本 · 名称来自 publish/config 的子文件夹", padding=6)
        versions.grid(row=2, column=0, sticky="nsew")
        self.config_tree = ttk.Treeview(versions, columns=("version", "status", "issues"), show="headings", height=5, selectmode="browse")
        for key, title, width in (("version", "版本名称", 200), ("status", "状态", 100), ("issues", "说明", 480)):
            self.config_tree.heading(key, text=title)
            self.config_tree.column(key, width=width, minwidth=80, stretch=key == "issues")
        self.scrollable_tree(versions, self.config_tree, horizontal=True)
        mapping = ttk.LabelFrame(page, text="2. 确认三个文件的替换关系", padding=6)
        mapping.grid(row=3, column=0, sticky="ew", pady=8)
        self.config_mapping = ttk.Treeview(mapping, columns=("source", "active", "action"), show="headings", height=3, selectmode="browse")
        self.config_mapping.tag_configure("same", foreground=COLORS["green"], background=COLORS["green_bg"])
        self.config_mapping.tag_configure("different", foreground=COLORS["red"], background=COLORS["red_bg"])
        for key, title, width in (("source", "版本文件夹内的源 JSON", 390), ("active", "publish 根目录生效文件", 290), ("action", "处理", 80)):
            self.config_mapping.heading(key, text=title)
            self.config_mapping.column(key, width=width, minwidth=70, stretch=key == "source")
        self.scrollable_tree(mapping, self.config_mapping, horizontal=True)
        self.engineer_widgets.append(mapping)
        bottom = ttk.Frame(page)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, text="缺失、重名或无效 JSON 时禁止应用。请先退出主程序；旧配置会备份，源模板保留。",
                  wraplength=440).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.config_compare_button = self.button(bottom, "查看所选 JSON 差异", self.compare_config_selection)
        self.config_compare_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.engineer_widgets.append(self.config_compare_button)
        self.config_apply_button = self.button(bottom, "应用所选版本", self.apply_config)
        self.config_apply_button.configure(style="Primary.TButton")
        self.config_apply_button.grid(row=0, column=2, sticky="e")

    def build_demo_page(self):
        page = self.demo_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        actions = ttk.Frame(page)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.demo_run_button = self.button(actions, "运行当前", self.start_demo)
        self.demo_run_button.pack(side="left", padx=(0, 6))
        self.demo_checked_button = self.button(actions, "运行勾选", self.start_checked_demos)
        self.demo_checked_button.configure(style="Primary.TButton")
        self.demo_checked_button.pack(side="left", padx=(0, 6))
        self.demo_all_button = self.button(actions, "全部运行", self.start_all_demos)
        self.demo_all_button.pack(side="left")
        self.demo_stop_button = ttk.Button(actions, text="停止全部", command=self.stop_demo, state="disabled")
        self.demo_stop_button.pack(side="right")
        self.demo_skip_button = ttk.Button(actions, text="跳过当前", command=self.skip_demo, state="disabled")
        self.demo_skip_button.pack(side="right", padx=6)
        queue_status = ttk.Frame(page, style="Toolbar.TFrame", padding=(10, 7))
        queue_status.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        queue_status.columnconfigure(0, weight=1)
        ttk.Label(queue_status, textvariable=self.demo_progress_text, style="Panel.TLabel", wraplength=650).grid(row=0, column=0, sticky="w")
        ttk.Label(queue_status, textvariable=self.demo_elapsed_text, style="PanelMuted.TLabel").grid(row=0, column=1, padx=(10, 0))
        self.demo_queue_bar = ttk.Progressbar(queue_status, mode="determinate", maximum=1)
        self.demo_queue_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.demo_pane = ttk.Panedwindow(page, orient="horizontal")
        self.demo_pane_sized = False
        self.demo_pane.grid(row=2, column=0, sticky="nsew")
        self.demo_pane.bind("<Configure>", lambda event: self.demo_pane.after_idle(self.fit_demo_panes))
        self.demo_pane.bind("<ButtonRelease-1>", lambda event: self.demo_pane.after_idle(self.fit_demo_panes))
        tasks = ttk.LabelFrame(self.demo_pane, text="模块", padding=6)
        task_tools = ttk.Frame(tasks)
        task_tools.pack(fill="x", pady=(0, 4))
        refresh = self.button(task_tools, "刷新", self.refresh_demo_tasks)
        refresh.configure(style="Compact.TButton", width=5)
        refresh.pack(side="left")
        self.demo_select_all_button = ttk.Button(task_tools, text="全选", style="Compact.TButton", width=5,
                                                 command=lambda: self.demo_grid.check_all(True))
        self.demo_select_all_button.pack(side="left", padx=(6, 3))
        self.demo_clear_button = ttk.Button(task_tools, text="清空", style="Compact.TButton", width=5,
                                            command=lambda: self.demo_grid.check_all(False))
        self.demo_clear_button.pack(side="left")
        self.demo_count = ttk.Label(tasks, text="尚未读取模块", style="Muted.TLabel")
        self.demo_count.pack(anchor="w", padx=3, pady=(0, 3))
        self.demo_grid = DemoGrid(tasks, self.font_family, self.start_demo)
        self.demo_grid.pack(fill="both", expand=True)
        self.demo_pane.add(tasks, weight=5)
        self.demo_output = ttk.Notebook(self.demo_pane)
        self.demo_pane.add(self.demo_output, weight=6)
        self.demo_log_page = ttk.Frame(self.demo_output, padding=6)
        self.demo_result_page = ttk.Frame(self.demo_output, padding=6)
        self.demo_output.add(self.demo_log_page, text="实时日志")
        self.demo_output.add(self.demo_result_page, text="本次结果")
        self.build_demo_log(self.demo_log_page)
        self.build_demo_results(self.demo_result_page)
        ttk.Label(page, textvariable=self.demo_status, style="Muted.TLabel",
                  wraplength=820).grid(row=3, column=0, sticky="w", pady=(6, 0))

    def fit_demo_panes(self):
        width = self.demo_pane.winfo_width()
        if width < 500:
            return
        current = self.demo_pane.sashpos(0)
        desired = current if self.demo_pane_sized else round(width * 0.44)
        self.demo_pane_sized = True
        desired = max(205, min(desired, width - 270))
        if current != desired:
            self.demo_pane.sashpos(0, desired)

    def build_demo_log(self, output):
        output.columnconfigure(0, weight=1)
        output.rowconfigure(2, weight=1)
        filters = ttk.Frame(output)
        filters.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.demo_log_filter = ttk.Combobox(filters, textvariable=self.demo_log_mode, values=("全部日志", "当前模块日志"),
                                          state="readonly", width=10)
        self.demo_log_filter.pack(side="left")
        self.demo_log_filter.bind("<<ComboboxSelected>>", lambda event: self.render_demo_logs())
        ttk.Button(filters, text="复制", style="Compact.TButton", width=5,
                   command=self.copy_demo_logs).pack(side="left", padx=4)
        ttk.Button(filters, text="导出…", style="Compact.TButton", width=6,
                   command=self.export_demo_logs).pack(side="left")
        log_info = ttk.Frame(output)
        log_info.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self.demo_latest_button = ttk.Button(log_info, text="回到最新", style="Compact.TButton", width=8,
                                             command=self.show_latest_demo_log)
        self.demo_latest_button.pack(side="right")
        log_title = ttk.Label(log_info, textvariable=self.demo_log_title, style="Muted.TLabel", wraplength=180)
        log_title.pack(side="left", fill="x", expand=True)
        log_info.bind("<Configure>", lambda event: log_title.configure(
            wraplength=max(70, event.width - self.demo_latest_button.winfo_reqwidth() - 8)))
        self.demo_text = tk.Text(output, wrap="none", state="disabled", height=7, width=29, font="TkFixedFont")
        self.demo_text.grid(row=2, column=0, sticky="nsew")
        self.demo_text.tag_configure("error", foreground=COLORS["red"])
        self.demo_text.tag_configure("warning", foreground=COLORS["amber"])
        vertical = ttk.Scrollbar(output, command=self.demo_text.yview)
        vertical.grid(row=2, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(output, orient="horizontal", command=self.demo_text.xview)
        horizontal.grid(row=3, column=0, sticky="ew")
        self.demo_text.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        ttk.Entry(output, textvariable=self.demo_log_path, state="readonly", width=12).grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(5, 0))

    def build_demo_results(self, results):
        results.columnconfigure(0, weight=1)
        results.rowconfigure(1, weight=1)
        self.demo_result_hint = tk.StringVar(value=DEMO_RESULTS_EMPTY)
        summary = ttk.Label(results, textvariable=self.demo_result_hint, style="Muted.TLabel", wraplength=260)
        summary.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        results.bind("<Configure>", lambda event: summary.configure(wraplength=max(150, event.width - 12)))
        actions = ttk.Frame(results)
        actions.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        self.demo_result_log_button = ttk.Button(actions, text="查看日志", style="Compact.TButton", width=9,
                                                 command=self.show_demo_result_log, state="disabled")
        self.demo_result_log_button.pack(side="left")
        self.demo_retry_button = ttk.Button(actions, text="重跑失败及未启动", style="Compact.TButton", width=16,
                                            command=self.retry_demos, state="disabled")
        self.demo_retry_button.pack(side="left", padx=(6, 0))
        table = ttk.Frame(results)
        table.grid(row=1, column=0, sticky="nsew")
        self.demo_results = ttk.Treeview(table, columns=("module", "result", "elapsed", "exit"),
                                        show="headings", selectmode="browse", height=6)
        for key, name, width in (("module", "模块", 113), ("result", "结果", 66),
                                 ("elapsed", "耗时", 52), ("exit", "退出码", 58)):
            self.demo_results.heading(key, text=name)
            self.demo_results.column(key, width=width, minwidth=48, stretch=key == "module",
                                     anchor="w" if key == "module" else "center")
        for phase, color in (("completed", "green"), ("failed", "red"), ("stopped", "amber"), ("skipped", "amber")):
            self.demo_results.tag_configure(phase, foreground=COLORS[color])
        self.scrollable_tree(table, self.demo_results, horizontal=True)
        self.demo_results.bind("<<TreeviewSelect>>", lambda event: self.demo_result_selected())
        self.demo_results.bind("<Double-1>", self.show_demo_result_log)
        self.demo_results.bind("<Return>", self.show_demo_result_log)
        self.demo_detail_frame = ttk.Frame(results)
        self.demo_detail_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.demo_detail_frame.columnconfigure(0, weight=1)
        self.demo_result_detail = tk.Text(self.demo_detail_frame, wrap="word", height=4, width=16,
                                          padx=7, pady=4, state="disabled")
        self.demo_result_detail.grid(row=0, column=0, sticky="ew")
        self.demo_result_detail.tag_configure("module", font=(self.font_family, 9, "bold"))
        detail_scroll = ttk.Scrollbar(self.demo_detail_frame, command=self.demo_result_detail.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.demo_result_detail.configure(yscrollcommand=detail_scroll.set)
        self.demo_detail_frame.grid_remove()

    def build_tools_page(self):
        presets = ttk.LabelFrame(self.tools_page, text="手动权限预设 · 整个当前 publish 目录", padding=12)
        presets.pack(fill="x", pady=(0, 12))
        ttk.Label(presets, text="Ubuntu 管理员授权后执行，包含主程序、脚本和模型等全部内容。\n777 允许所有用户读写执行；此操作不生成备份，失败可能已修改部分权限。",
                  wraplength=800).pack(anchor="w", pady=(0, 10))
        actions = ttk.Frame(presets)
        actions.pack(fill="x")
        self.permission_preset_buttons = []
        for key in ("root", "777", "root-and-777"):
            button = self.button(actions, PRESETS[key], lambda key=key: self.apply_permission_preset(key))
            button.pack(side="left", padx=(0, 8))
            self.permission_preset_buttons.append(button)
        recovery = ttk.LabelFrame(self.tools_page, text="备份恢复", padding=12)
        recovery.pack(fill="x", pady=(0, 12))
        ttk.Label(recovery, text="按上次记录的格式范围恢复文件；执行前请退出主程序。", wraplength=800).pack(anchor="w")
        self.button(recovery, "恢复上次更新", self.restore).pack(anchor="w", pady=(8, 0))
        diagnostics = ttk.LabelFrame(self.tools_page, text="比较自测", padding=12)
        diagnostics.pack(fill="x")
        ttk.Label(diagnostics, text="使用随工具附带的样例验证比较功能，结果在独立窗口查看。", wraplength=800).pack(anchor="w")
        self.button(diagnostics, "运行比较自测", self.run_comparison_self_test).pack(anchor="w", pady=(8, 0))
        ttk.Label(self.tools_page, text="实际文件的红绿逐行对比：更新文件 → 检查差异 → 选中文件 → 查看选中文件差异。",
                  wraplength=800).pack(anchor="w", pady=12)

    def build_program_page(self):
        page = self.program_page
        page.columnconfigure(0, weight=1)
        ttk.Label(page, text="Switcher 程序更新", style="Title.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 10))
        ttk.Label(page, textvariable=self.program_version_text).grid(row=1, column=0, sticky="w", pady=4)
        ttk.Label(page, textvariable=self.program_status, wraplength=650).grid(row=2, column=0, sticky="w", pady=8)
        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky="w", pady=8)
        self.program_check_button = ttk.Button(actions, text="检查更新 / 重试", command=self.check_program_update)
        self.program_check_button.pack(side="left")
        self.program_apply_button = ttk.Button(actions, text="更新并重启", style="Primary.TButton",
                                                command=self.apply_program_update, state="disabled")
        self.program_apply_button.pack(side="left", padx=8)
        self.program_offline_button = ttk.Button(actions, text="导入离线更新", command=self.import_program_update)
        self.program_offline_button.pack(side="left")
        ttk.Label(page, textvariable=self.program_notes, wraplength=650, style="Muted.TLabel",
                  justify="left").grid(row=4, column=0, sticky="nw", pady=12)

    def save_program_source(self):
        if self.busy:
            return
        try:
            address = tool_update.https_url(self.program_source.get())
            data = read_json(CONFIG) if CONFIG.exists() else {}
            data["program_update_url"] = address
            atomic_json(CONFIG, data)
        except (ValueError, OSError, tool_update.UpdateError) as exc:
            messagebox.showerror("更新源未保存", str(exc))
            return
        self.program_source.set(address)
        self.program_checked = False
        self.program_release = None
        self.program_status.set("更新源已保存，请检查程序版本。")
        self.configure_access()
        self.update_ready()

    def check_program_update(self):
        if getattr(self, "program_check_id", None):
            self.root.after_cancel(self.program_check_id)
            self.program_check_id = None
        if self.program_checking or self.busy:
            return
        self.program_checking = True
        self.program_status.set("正在检查 Switcher 版本…")
        address = self.program_source.get().strip()
        def worker():
            try:
                value = tool_update.check_release(address, self.install_directory, VERSION)
                self.events.put(("program_check", (address, value, None)))
            except Exception as exc:
                self.logger.exception("Switcher 程序版本检查失败")
                self.events.put(("program_check", (address, None, str(exc))))
        threading.Thread(target=worker, daemon=True).start()
        self.update_ready()

    def program_check_finished(self, data):
        address, value, error = data
        self.program_checking = False
        if address != self.program_source.get().strip():
            self.check_program_update()
            return
        if error:
            self.program_status.set("版本检查未完成，请重试或导入离线更新。")
            self.program_notes.set(error)
            self.program_checked = False
        else:
            release, newer = value
            self.program_checked = not newer
            self.program_release = release if newer else None
            self.program_notes.set(release["notes"])
            if newer:
                self.program_version_text.set("当前 {}    最新 {}".format(VERSION, release["version"]))
                self.program_status.set("发现新版本。请更新并重启后使用。")
            else:
                self.program_status.set("已确认当前版本，可以使用。")
        self.configure_access()
        self.update_ready()
        if self.program_checked:
            self.program_ready()

    def program_ready(self):
        self.configure_access()
        if self.target.get():
            if not self.engine:
                self.connect()
            if not self.engineer_mode:
                self.pages.select(self.config_page)
        elif not self.engineer_mode:
            self.program_status.set("程序版本已确认。设备尚未配置，请联系实施人员。")

    def apply_program_update(self):
        if not self.program_release or self.busy:
            return
        release = dict(self.program_release)
        self.program_status.set("正在下载、校验并准备新版程序…")
        count = [0]
        def progress(size):
            count[0] += size
            self.events.put(("log", "程序下载 {:.1f} / {:.1f} MiB".format(count[0] / 2**20, release["size"] / 2**20)))
        self.run(lambda: tool_update.prepare_online(self.install_directory, release, VERSION, self.cancel, progress),
                 self.program_prepared, system_update=True)

    def import_program_update(self):
        if self.busy:
            return
        selected = filedialog.askopenfilename(parent=self.root, title="选择与安装包放在一起的 switcher-update.json",
                                              filetypes=[("程序发布信息", "*.json")])
        if not selected:
            return
        def work():
            release = tool_update.validate_release(tool_update.read_json(selected))
            record = tool_update.prepare_offline(self.install_directory, selected, VERSION)
            return release, record
        def done(result):
            release, record = result
            if tool_update.version_number(release["version"]) == tool_update.version_number(VERSION):
                tool_update.recover_update(self.install_directory)
                self.program_release = None
                self.program_checked = True
                self.program_status.set("已通过离线安装包验证当前版本，可以使用。")
                self.program_ready()
            else:
                self.program_prepared(record)
        self.run(work, done, system_update=True)

    def program_prepared(self, record):
        try:
            tool_update.launch_update_helper(self.install_directory, self.engineer_mode)
        except Exception as exc:
            tool_update.recover_update(self.install_directory)
            messagebox.showerror("更新助手未启动", str(exc))
            return
        self.root.destroy()

    def build_settings_page(self):
        page = self.settings_page
        ttk.Label(page, text="先填写设备上的 publish 目录，保存后到“更新文件”刷新方案。",
                  wraplength=800).pack(anchor="w", pady=(0, 12))
        settings = ttk.LabelFrame(page, text="连接设置", padding=12)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate((("publish 目录", self.target), ("资源仓库", self.repo), ("分支", self.branch))):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", pady=8)
            entry = ttk.Entry(settings, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=10)
            self.controls.append(entry)
        self.button(settings, "浏览目录", self.browse, row=0, column=2)
        ttk.Label(settings, text="支持 Gitee / GitHub；分支留空使用仓库默认分支。",
                  wraplength=700).grid(row=3, column=1, sticky="w", padx=10, pady=6)
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=12)
        self.button(actions, "保存设置 / 读取缓存", self.connect).pack(side="left")
        self.button(actions, "方案目录设置（Jetson / RK 等）", self.edit_presets).pack(side="left", padx=8)
        if self.updates_enabled:
            ttk.Button(actions, text="返回用户界面", command=self.toggle_engineer).pack(side="left")
        if self.updates_enabled:
            program = ttk.LabelFrame(page, text="Switcher 程序更新源", padding=8)
            program.pack(fill="x")
            program.columnconfigure(0, weight=1)
            self.controls.append(ttk.Entry(program, textvariable=self.program_source))
            self.controls[-1].grid(row=0, column=0, sticky="ew")
            self.button(program, "保存更新源", self.save_program_source).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(page, text="清单缓存保存方案的文件列表；实际资源文件经下载校验后单独缓存。\n是否支持离线更新，以所选方案需要的文件是否已完整缓存为准。",
                  wraplength=800).pack(anchor="w", pady=8)
        about = ttk.LabelFrame(page, text="关于工具", padding=12)
        about.pack(fill="x", pady=(6, 0))
        about.columnconfigure(1, weight=1)
        ttk.Label(about, text="版本").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(about, text=VERSION).grid(row=0, column=1, sticky="w")
        ttk.Label(about, text="运行目录").grid(row=1, column=0, sticky="w", pady=(6, 0))
        location = ttk.Entry(about)
        location.insert(0, str(Path(__file__).resolve().parent))
        location.configure(state="readonly")
        location.grid(row=1, column=1, sticky="ew", pady=(6, 0))

    @staticmethod
    def scrollable_tree(parent, tree, horizontal=False):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(parent, command=tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=vertical.set)
        if horizontal:
            bar = ttk.Scrollbar(parent, orient="horizontal", command=tree.xview)
            bar.grid(row=1, column=0, sticky="ew")
            tree.configure(xscrollcommand=bar.set)

    def toggle_log(self):
        self.set_log_visible(not self.log_visible)

    def set_log_visible(self, visible):
        self.log_visible = visible
        if visible:
            self.log_output.pack(side="bottom", fill="x", padx=12, pady=(0, 4), before=self.pages)
        else:
            self.log_output.pack_forget()
        self.log_button.configure(text="收起日志" if visible else "展开日志")

    def button(self, parent, text, command, **grid):
        button = ttk.Button(parent, text=text, command=command)
        self.controls.append(button)
        if grid:
            button.grid(**grid, padx=3)
        return button

    def browse(self):
        path = filedialog.askdirectory(title="选择要同步的 publish 目录")
        if path:
            self.target.set(path)

    def append(self, text):
        self.text.configure(state="normal")
        self.text.insert("end", text + "\n")
        self.text.see("end")
        self.text.configure(state="disabled")

    def run(self, function, done, cancellable=True, system_update=False):
        if self.busy:
            return
        if self.updates_enabled and not self.engineer_mode and not self.program_checked and not system_update:
            self.pages.select(self.program_page)
            return
        self.busy = True
        self.operation_cancellable = cancellable
        self.last_error = False
        self.update_ready()
        self.cancel.clear()
        for control in self.controls:
            control.configure(state="disabled")
        self.tree.configure(selectmode="none")
        self.config_tree.configure(selectmode="none")
        self.assets_tree.configure(selectmode="none")
        self.cancel_button.configure(state="normal" if cancellable else "disabled")
        self.cancel_button.configure(text="停止 Demo" if self.demo_running else "取消准备")
        self.progress.start(15)
        self.status.set("正在处理…")
        def worker():
            try:
                value = function()
                self.events.put(("done", (done, value)))
            except Exception as exc:
                self.logger.exception("桌面操作失败")
                kind = "demo_preflight_error" if isinstance(exc, DemoPreflightError) else "error"
                self.events.put((kind, str(exc)))
        self.worker = threading.Thread(target=worker, daemon=False)
        self.worker.start()

    def poll(self):
        try:
            for _ in range(200):
                kind, data = self.events.get_nowait()
                if kind == "log":
                    self.append(data)
                    self.status.set(data)
                elif kind == "demo_log":
                    self.append_demo(data)
                elif kind == "program_check":
                    self.program_check_finished(data)
                    continue
                elif kind == "demo_progress":
                    self.demo_progress_event(data)
                elif kind == "demo_state":
                    self.demo_grid.update_state(data)
                    if data["phase"] == "running" and data["task_id"] != getattr(self, "demo_follow_id", None):
                        self.demo_follow_id = data["task_id"]
                        if self.demo_log_mode.get() == "全部日志" or self.demo_log_at_end():
                            self.demo_grid.reveal(data["task_id"])
                    self.demo_live_summary()
                    self.update_demo_controls()
                else:
                    self.busy = False
                    was_demo = self.demo_running
                    self.demo_running = False
                    for control in self.controls:
                        control.configure(state="normal")
                    self.tree.configure(selectmode="browse")
                    self.config_tree.configure(selectmode="browse")
                    self.assets_tree.configure(selectmode="browse")
                    self.cancel_button.configure(state="disabled")
                    self.cancel_button.configure(text="取消准备")
                    self.progress.stop()
                    if kind in ("error", "demo_preflight_error"):
                        self.last_error = True
                        self.checked = None
                        self.config_preview = None
                        self.invalidate_assets()
                        self.update_summary.set("操作未完成，请重新检查后再更新。")
                        self.status.set(data)
                        self.append("操作未完成：" + data)
                        self.set_log_visible(True)
                        if was_demo:
                            self.demo_needs_refresh = kind == "demo_preflight_error"
                            self.finish_demo_cards("failed", error=data)
                            self.demo_status.set("Demo 未能完成：" + data)
                            self.append_demo("Demo 未能完成：" + data)
                        if not self.closing:
                            messagebox.showerror("操作未完成", data)
                    else:
                        callback, value = data
                        callback(value)
                    self.update_ready()
                    if self.closing:
                        self.root.destroy()
                        return
        except queue.Empty:
            pass
        if self.demo_running:
            self.update_demo_clock()
        self.poll_id = self.root.after(100, self.poll)

    def on_destroy(self, event):
        if event.widget is self.root and getattr(self, "program_check_id", None):
            self.root.after_cancel(self.program_check_id)
            self.program_check_id = None
        if event.widget is self.root and self.demo_running:
            self.cancel.set()
        if event.widget is self.root and getattr(self, "poll_id", None):
            try:
                self.root.after_cancel(self.poll_id)
            except tk.TclError:
                pass
            self.poll_id = None

    def log(self, text):
        self.logger.info(text)
        self.events.put(("log", text))

    def ensure_engine(self):
        if self.engine is None or Path(self.target.get()).expanduser().resolve() != self.engine.target:
            messagebox.showinfo("先保存设置", "选择目标目录后，请先保存设置并读取缓存。")
            return False
        return True

    def connect(self):
        target, repo, branch = self.target.get().strip(), self.repo.get().strip(), self.branch.get().strip()
        sync_permissions = self.sync_permissions.get()
        update_mode = self.update_mode.get()
        presets = json.loads(json.dumps(self.presets))
        if not target:
            messagebox.showinfo("选择目录", "请先选择 publish 目录。")
            return
        def work():
            engine = Engine(target, extensions=self.file_extensions)
            if is_relative_to(CONFIG.resolve(), engine.target):
                raise SyncError("设置文件位置必须在 publish 外，请调整 XDG_CONFIG_HOME。")
            recovered = engine.startup_recover()
            data = read_json(CONFIG) if CONFIG.exists() else {}
            data.update({"target": str(engine.target), "publish_dir": str(engine.target), "repo": repo, "branch": branch, "directory_profiles": presets,
                                 "update_mode": update_mode,
                                 "repository_default_version": REPOSITORY_DEFAULT_VERSION, "sync_permissions": sync_permissions,
                                 "file_extensions": list(self.file_extensions), "format_inventory": self.format_inventory})
            atomic_json(CONFIG, data)
            return engine, engine.profiles(), recovered
        def done(result):
            self.engine, profiles, recovered = result
            self.profiles = [{"manifest": p["manifest"], "source": Source(**p["source"])} for p in profiles]
            self.add_placeholders()
            self.show_profiles()
            self.update_current()
            self.status.set("已保存设置；" + ("已处理未完成事务。" if recovered else "可以刷新远端方案或导入本地 catalog。"))
        self.run(work, done)

    def add_placeholders(self):
        ids = {(p.get("manifest") or p["profile"])["id"] for p in self.profiles}
        for p in self.presets:
            if p["id"] not in ids:
                self.profiles.append({"preset_only": True, "profile": {"id": p["id"], "name": p["name"], "version": "待刷新"}})

    def edit_presets(self):
        dialog = tk.Toplevel(self.root)
        style_dialog(dialog)
        dialog.title("方案设置：名称、仓库目录及新增方案")
        dialog.geometry("740x540")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="修改 JSON 数组即可添加或重命名方案。directory 是仓库内目录；刷新时也会发现新的 publish_* 目录。\nexecutables 设置实际同步文件的仓库权限；allow_empty 用于确实允许为空的文件。未勾选格式只提示。",
                  wraplength=710).pack(fill="x", padx=12, pady=10)
        editor = tk.Text(dialog, wrap="none")
        editor.pack(fill="both", expand=True, padx=12)
        editor.insert("1.0", json.dumps(self.presets, ensure_ascii=False, indent=2))
        actions = ttk.Frame(dialog)
        actions.pack(fill="x", padx=12, pady=10)
        def defaults():
            editor.delete("1.0", "end")
            editor.insert("1.0", json.dumps(DEFAULT_PROFILES, ensure_ascii=False, indent=2))
        def save():
            try:
                presets = validate_presets(json.loads(editor.get("1.0", "end")))
                target = self.target.get().strip()
                if target and is_relative_to(CONFIG.resolve(), Path(target).expanduser().resolve()):
                    raise SyncError("设置文件位置必须在 publish 外。")
                data = read_json(CONFIG) if CONFIG.exists() else {}
                data.update({"target": target, "repo": self.repo.get().strip(), "branch": self.branch.get().strip(),
                                     "update_mode": self.update_mode.get(),
                                     "directory_profiles": presets, "repository_default_version": REPOSITORY_DEFAULT_VERSION,
                                     "sync_permissions": self.sync_permissions.get(), "file_extensions": list(self.file_extensions),
                                     "format_inventory": self.format_inventory})
                atomic_json(CONFIG, data)
            except (SyncError, ValueError, OSError) as exc:
                messagebox.showerror("设置未保存", str(exc), parent=dialog)
                return
            self.presets = presets
            self.profiles = [p for p in self.profiles if "manifest" in p]
            self.add_placeholders()
            self.show_profiles()
            self.status.set("方案设置已保存，请刷新远端方案；已有缓存方案仍可使用。")
            dialog.destroy()
        ttk.Button(actions, text="恢复默认方案", command=defaults).pack(side="left")
        ttk.Button(actions, text="保存", command=save).pack(side="right")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="right", padx=8)

    def show_profiles(self):
        self.invalidate_check()
        self.tree.delete(*self.tree.get_children())
        for i, item in enumerate(self.profiles):
            m = item.get("manifest") or item["profile"]
            self.tree.insert("", "end", iid=str(i), values=(m.get("name", m["id"]), m["version"],
                             "预设（请刷新）" if item.get("preset_only") else
                             "清单已缓存（资源需检查）" if "manifest" in item else "未缓存"))
        previous = self.assets_combo.current()
        preferred = None
        if 0 <= previous < len(self.assets_profiles):
            old = self.assets_profiles[previous]
            preferred = (old.get("manifest") or old["profile"])["id"]
        self.assets_profiles = self.profiles[:]
        values = []
        for index, item in enumerate(self.assets_profiles, 1):
            profile = item.get("manifest") or item["profile"]
            values.append("{}. {} / {}{}".format(index, profile.get("name", profile["id"]), profile["version"], "（请先刷新）" if item.get("preset_only") else ""))
        self.assets_combo.configure(values=values)
        if values:
            index = next((i for i, p in enumerate(self.assets_profiles) if (p.get("manifest") or p["profile"])["id"] == preferred), 0)
            self.assets_combo.current(index)
        else:
            self.assets_combo.set("")

    def update_current(self):
        self.invalidate_assets()
        self.invalidate_demo_tasks()
        try:
            info = read_json(self.engine.current)
            text = f"当前方案：{info.get('name', info['id'])} / {info['version']}（上次成功应用记录）"
        except (OSError, ValueError, KeyError):
            text = "当前方案：未由本工具应用"
        self.current.set(text)
        self.task_mode.set(self.engine.task_config_status(user_only=not self.engineer_mode))
        if self.pages.select() == str(self.demo_page):
            self.refresh_demo_tasks()
        else:
            self.refresh_config_choices()

    def publish_changed(self):
        self.invalidate_check()
        self.invalidate_demo_tasks()
        self.config_preview = None
        self.config_tree.delete(*self.config_tree.get_children())
        self.config_mapping.delete(*self.config_mapping.get_children())
        self.task_mode.set("配置版本：未读取")
        self.update_ready()

    def page_changed(self, event):
        if self.updates_enabled:
            if not self.engineer_mode and (not self.program_checked or self.pages.select() in
                    (str(self.assets_page), str(self.tools_page), str(self.settings_page))):
                self.configure_access()
                return
        self.sync_navigation()
        if self.pages.select() == str(self.config_page):
            self.refresh_config_choices()
        elif self.pages.select() == str(self.demo_page) and self.engine and Path(self.target.get()).expanduser().resolve() == self.engine.target:
            self.refresh_demo_tasks()

    def invalidate_demo_tasks(self):
        self.demo_tasks = {}
        self.demo_grid.clear()
        self.demo_grid.empty.configure(text="选择 publish 目录后，点击“刷新”读取模块。")
        self.reset_demo_run()
        self.demo_count.configure(text="尚未读取模块")
        self.demo_status.set("目录或配置已变化，请刷新任务列表；运行前会重新读取当前配置。")
        self.update_ready()

    def refresh_demo_tasks(self):
        if self.busy or self.closing or not self.ensure_engine():
            return
        engine = self.engine
        def work():
            try:
                tasks = load_tasks(engine.target, allow_empty=True)
            except DemoError as exc:
                return [], str(exc)
            rows = []
            for task in tasks:
                scripts, _, error = describe(engine.target, task)
                rows.append((task, scripts, error))
            return rows, None
        def done(data):
            rows, read_error = data
            tasks = {}
            cards = []
            for task, scripts, error in rows:
                key = str(task["TrainTaskId"])
                paths = [script.relative_to(engine.target).as_posix() for script in scripts]
                tasks[key] = {"task": task, "valid": not error, "scripts": paths, "error": error}
                cards.append((key, task_name(task), paths, error))
            same = list(self.demo_tasks.items()) == list(tasks.items())
            if same and tasks:
                if self.demo_needs_refresh:
                    self.demo_needs_refresh = False
                    self.demo_result_selected()
                    self.demo_status.set("已重新检查模块。可以从结果页重跑。")
                else:
                    self.status.set("模块列表已刷新。")
                return
            self.demo_tasks = tasks
            self.demo_grid.set_tasks(cards)
            self.reset_demo_run()
            if not rows:
                self.demo_count.configure(text="读取失败" if read_error else "没有 IoT 模块")
                self.demo_grid.empty.configure(text=read_error or "当前任务配置没有 IoT 模块。请在“配置切换”选择包含 IoT 模块的版本，或检查 TrainTaskInfo.json。")
                self.demo_status.set("检查任务配置后点击“刷新”。")
                self.status.set("模块读取失败。" if read_error else "已读取任务配置。")
                return
            valid = sum(item["valid"] for item in self.demo_tasks.values())
            self.demo_count.configure(text="{} / {} 可运行".format(valid, len(rows)))
            self.demo_status.set("点击卡片查看脚本。勾选模块后，可按顺序运行勾选项。" if valid else
                                 "当前模块均不可运行。请查看卡片上的原因，处理后点击“刷新”。")
            self.status.set("模块列表已刷新。")
        self.run(work, done)

    def demo_selection_changed(self, event=None):
        self.update_ready()
        if self.demo_log_mode.get() == "当前模块日志":
            self.render_demo_logs()

    def demo_log_matches(self, entry):
        return self.demo_log_mode.get() == "全部日志" or (self.demo_grid.selected is not None and entry.get("task_id") == self.demo_grid.selected)

    def update_demo_log_path(self):
        key = self.demo_grid.selected
        if self.demo_log_mode.get() == "当前模块日志":
            item = self.demo_tasks.get(key)
            self.demo_log_title.set("#{} {}".format(key, task_name(item["task"])) if item else "请在左侧选择模块")
            path = self.demo_module_logs.get(key)
            self.demo_log_path.set(str(path) if path else "当前模块尚无本次运行日志")
        else:
            self.demo_log_title.set("全部模块的输出" if self.demo_all_log or self.demo_log_entries else
                                    "开始运行后可在这里查看输出")
            self.demo_log_path.set(str(self.demo_all_log) if self.demo_all_log else "运行后显示本次日志文件路径")

    def insert_demo_log(self, entry):
        level = entry.get("level")
        self.demo_text.insert("end", entry["line"] + "\n", level if level in ("error", "warning") else ())

    def demo_log_at_end(self):
        return self.demo_text.yview()[1] >= 0.9999

    def show_latest_demo_log(self):
        if self.demo_running and self.demo_log_mode.get() == "当前模块日志" and self.demo_current_id:
            if self.demo_grid.selected != self.demo_current_id:
                self.demo_grid.reveal(self.demo_current_id)
        self.demo_text.see("end")

    def render_demo_logs(self):
        self.demo_text.configure(state="normal")
        self.demo_text.delete("1.0", "end")
        entries = [entry for entry in self.demo_log_entries if self.demo_log_matches(entry)]
        for entry in entries:
            self.insert_demo_log(entry)
        # A later, noisy module can push all of an earlier module out of the live cache.
        if not entries and self.demo_log_mode.get() == "当前模块日志":
            path = self.demo_module_logs.get(self.demo_grid.selected)
            if path:
                try:
                    with path.open("rb") as stream:
                        size = stream.seek(0, os.SEEK_END)
                        offset = max(0, size - 256 * 1024)
                        stream.seek(offset)
                        data = stream.read(256 * 1024)
                    if offset and b"\n" in data:
                        data = data.split(b"\n", 1)[1]
                    lines = data.decode("utf-8", errors="replace").splitlines()[-3000:]
                    if lines:
                        self.demo_text.insert("end", "\n".join(lines) + "\n")
                except OSError as exc:
                    self.insert_demo_log({"line": "无法读取模块日志：" + str(exc), "level": "error"})
        self.demo_text.see("end")
        self.demo_text.configure(state="disabled")
        self.update_demo_log_path()

    def append_demo(self, entry):
        # Routing metadata comes from the runner, never from parsing script output.
        if isinstance(entry, str):
            entry = {"line": entry, "task_id": self.demo_current_id, "level": "info"}
        self.demo_log_entries.append(entry)
        if entry.get("log_path"):
            self.demo_all_log = Path(entry["log_path"])
            if entry.get("task_id") is not None:
                self.demo_module_logs[entry["task_id"]] = self.demo_all_log
        if entry.get("module_log_path"):
            self.demo_module_logs[entry["task_id"]] = Path(entry["module_log_path"])
        if entry.get("log_path") or entry.get("module_log_path") or len(self.demo_log_entries) == 1:
            self.update_demo_log_path()
        if not self.demo_log_matches(entry):
            return
        follow = self.demo_log_at_end()
        self.demo_text.configure(state="normal")
        self.insert_demo_log(entry)
        if int(self.demo_text.index("end-1c").split(".")[0]) > 3000:
            self.demo_text.delete("1.0", "501.0")
        if follow:
            self.demo_text.see("end")
        self.demo_text.configure(state="disabled")

    def copy_demo_logs(self):
        output = self.demo_text.get("1.0", "end-1c")
        if not output:
            self.status.set("当前没有可复制的日志。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(output)
        self.status.set("已复制当前显示的日志；完整日志可通过“导出”保存。")

    def export_demo_logs(self):
        path = self.demo_module_logs.get(self.demo_grid.selected) if self.demo_log_mode.get() == "当前模块日志" else self.demo_all_log
        if path is None or not path.is_file():
            messagebox.showinfo("暂无日志", "当前范围尚无本次运行日志文件。")
            return
        destination = filedialog.asksaveasfilename(parent=self.root, title="导出完整日志", initialfile=path.name,
                                                 defaultextension=".log", filetypes=[("日志文件", "*.log"), ("所有文件", "*")])
        if not destination:
            return
        try:
            if Path(destination).resolve() == path.resolve():
                messagebox.showinfo("日志已在此处", "选择的路径就是原始日志，无需重复导出。")
                return
            shutil.copyfile(str(path), destination)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        self.status.set("已导出完整日志" + ("（截至当前时刻）" if self.demo_running else "") + "：" + destination)

    def start_demo(self):
        if self.busy or self.demo_needs_refresh or not self.ensure_engine() or not self.demo_grid.selected:
            return
        key = self.demo_grid.selected
        item = self.demo_tasks.get(key)
        if not item or not item["valid"]:
            return
        engine = self.engine
        if not messagebox.askyesno("运行 IoT Demo", "任务：{} / {}\n脚本：{}\n\n将执行当前配置中的原脚本，并可能操作硬件、写入结果文件。\n请先退出主程序和其他硬件任务，是否运行？".format(
                key, task_name(item["task"]), item["task"]["PythonScriptPath"])):
            return
        self.begin_demo([key])
        def done(code):
            self.complete_demo(code)
        self.run(lambda: run_selected(engine.target, key, CONFIG.parent / "logs/iot-demo", cancel=self.cancel,
                                      output=lambda line: None,
                                      log_event=lambda event: self.events.put(("demo_log", event)),
                                      progress=lambda event: self.events.put(("demo_progress", event)),
                                      state=lambda event: self.events.put(("demo_state", event))), done)

    def start_all_demos(self):
        keys = [key for key, item in self.demo_tasks.items() if item["valid"]]
        skipped = [key + " " + task_name(item["task"]) for key, item in self.demo_tasks.items() if not item["valid"]]
        self.start_demo_queue(keys, "全部运行", skipped)

    def start_checked_demos(self):
        self.start_demo_queue(self.demo_grid.checked_keys(), "运行勾选")

    def demo_retry_keys(self):
        if self.demo_needs_refresh:
            return []
        return [key for key in self.demo_order if self.demo_tasks.get(key, {}).get("valid")
                and self.demo_timings.get(key, {}).get("phase") in ("failed", "not_started")]

    def retry_demos(self):
        self.start_demo_queue(self.demo_retry_keys(), "重跑失败及未启动")

    def start_demo_queue(self, keys, title, skipped=()):
        if self.busy or self.demo_needs_refresh or not self.ensure_engine():
            return
        if not keys:
            messagebox.showinfo("没有可运行模块", "请先刷新模块，检查脚本与解释器。")
            return
        names = ["#{} {}".format(key, task_name(self.demo_tasks[key]["task"])) for key in keys]
        text = ("将按列表顺序运行 {} 个模块。当前模块清理完成后才会开始下一项。"
                "\n脚本异常或停止全部会结束队列。请先退出主程序及其他硬件任务。"
                "\n\n{}").format(len(keys), "\n".join(names[:10]))
        if len(names) > 10:
            text += "\n另有 {} 项".format(len(names) - 10)
        if skipped:
            text += "\n\n跳过 {} 个不可运行模块：\n{}".format(len(skipped), "\n".join(skipped[:8]))
        if not messagebox.askyesno(title + " IoT Demo", text + "\n\n是否运行？"):
            return
        engine = self.engine
        snapshot = [item["task"] for item in self.demo_tasks.values()]
        self.begin_demo(keys)
        self.demo_control = DemoQueueControl()
        self.run(lambda: run_many(engine.target, keys, CONFIG.parent / "logs/iot-demo", cancel=self.cancel,
                                 output=lambda line: None, control=self.demo_control,
                                 log_event=lambda event: self.events.put(("demo_log", event)),
                                 progress=lambda event: self.events.put(("demo_progress", event)),
                                 state=lambda event: self.events.put(("demo_state", event)), expected_tasks=snapshot), self.complete_demo)

    def reset_demo_run(self):
        self.demo_log_entries.clear()
        self.demo_module_logs.clear()
        self.demo_all_log = None
        self.demo_order = []
        self.demo_timings = {}
        self.demo_started_at = self.demo_finished_at = None
        self.demo_start_error = None
        self.demo_needs_refresh = False
        self.demo_current_id = None
        self.demo_control = None
        self.demo_results.delete(*self.demo_results.get_children())
        self.demo_result_hint.set(DEMO_RESULTS_EMPTY)
        self.demo_queue_bar.configure(maximum=1, value=0)
        self.demo_progress_text.set("尚未开始运行")
        self.demo_elapsed_text.set("总用时 00:00")
        self.render_demo_logs()
        self.demo_result_selected()

    def begin_demo(self, keys):
        self.invalidate_check()
        self.reset_demo_run()
        self.demo_output.select(self.demo_log_page)
        self.demo_order = list(keys)
        self.demo_started_at = time.monotonic()
        self.demo_queue_bar.configure(maximum=len(keys), value=0)
        self.demo_progress_text.set("准备 {} 个模块…".format(len(keys)))
        self.demo_active_ids = set(keys)
        self.demo_follow_id = None
        self.demo_result_hint.set("本次运行正在进行。实时输出在“实时日志”。")
        for key in keys:
            card = self.demo_grid.cards[key]
            # Clear previous exit states and use structured startup events.
            card.scripts.clear()
            card.set_elapsed(None)
            for script in self.demo_tasks[key]["scripts"]:
                self.demo_grid.update_state({"task_id": key, "script": script, "phase": "queued"})
        self.demo_status.set("准备启动 {} 个模块。".format(len(keys)))
        self.demo_running = True

    def demo_progress_event(self, event):
        key = event["task_id"]
        self.demo_timings[key] = dict(event)
        if event["phase"] == "running":
            self.demo_current_id = key
        card = self.demo_grid.cards.get(key)
        if card and event.get("started") is not None:
            card.set_elapsed(event["elapsed"])
        self.update_demo_clock()
        self.update_demo_controls()

    def update_demo_clock(self):
        if self.demo_started_at is None:
            return
        now = self.demo_finished_at if self.demo_finished_at is not None else time.monotonic()
        self.demo_elapsed_text.set("总用时 " + format_duration(now - self.demo_started_at))
        completed = sum(t["phase"] not in ("running", "not_started") for t in self.demo_timings.values())
        self.demo_queue_bar.configure(value=completed)
        timing = self.demo_timings.get(self.demo_current_id)
        if timing and timing["phase"] == "running":
            elapsed = now - timing["started"]
            card = self.demo_grid.cards.get(self.demo_current_id)
            if card:
                card.set_elapsed(elapsed)
            item = self.demo_tasks.get(self.demo_current_id)
            name = task_name(item["task"]) if item else self.demo_current_id
            self.demo_progress_text.set("正在运行第 {} / {} 个 · {} · 当前用时 {}".format(
                timing["index"], timing["total"], name, format_duration(elapsed)))
        elif self.demo_timings or not self.demo_running:
            self.demo_progress_text.set("{} · 已处理 {} / {} 个模块".format("正在准备下一个" if self.demo_running else "队列已结束", completed, len(self.demo_order)))

    def update_demo_controls(self):
        can_skip = (self.demo_running and not self.cancel.is_set() and self.demo_control is not None and
                    self.demo_control.can_skip(self.demo_current_id))
        self.demo_skip_button.configure(state="normal" if can_skip else "disabled")

    def skip_demo(self):
        if (self.demo_running and not self.cancel.is_set() and self.demo_control is not None and
                self.demo_control.request_skip(self.demo_current_id)):
            self.demo_status.set("正在跳过当前模块，等待进程清理后继续下一个…")
        self.update_demo_controls()

    def finish_demo_cards(self, phase, error=None):
        self.demo_finished_at = time.monotonic()
        if error and not self.demo_timings:
            self.demo_start_error = error
        for timing in self.demo_timings.values():
            if timing["phase"] == "running":
                timing["phase"] = phase
                timing["elapsed"] = self.demo_finished_at - timing["started"]
                card = self.demo_grid.cards.get(timing["task_id"])
                if card:
                    card.set_elapsed(timing["elapsed"])
        for key in self.demo_active_ids:
            card = self.demo_grid.cards.get(key)
            if card:
                for script, current in list(card.scripts.items()):
                    if current.get("phase") in ("queued", "running"):
                        script_phase = "not_started" if current.get("phase") == "queued" else phase
                        card.update_state(dict(current, script=script, phase=script_phase, error=error))
        for key in self.demo_order:
            self.demo_timings.setdefault(key, {"phase": "not_started", "started": None, "elapsed": 0})
        self.demo_live_summary()
        self.update_demo_clock()
        self.demo_active_ids.clear()
        self.show_demo_results()

    def show_demo_results(self):
        self.demo_results.delete(*self.demo_results.get_children())
        counts = {}
        for key in self.demo_order:
            timing = self.demo_timings[key]
            phase = timing["phase"]
            counts[phase] = counts.get(phase, 0) + 1
            card = self.demo_grid.cards.get(key)
            codes = [str(item["exit_code"]) for item in card.scripts.values()
                     if item.get("exit_code") is not None] if card else []
            name = task_name(self.demo_tasks[key]["task"])
            elapsed = format_duration(timing["elapsed"]) if timing.get("started") is not None else "—"
            self.demo_results.insert("", "end", iid=key, tags=(phase,),
                                     values=("#{} {}".format(key, name), PHASES[phase], elapsed, ", ".join(codes) or "—"))
        summary = " · ".join("{} {}".format(PHASES[phase], counts[phase])
                             for phase in ("completed", "failed", "stopped", "skipped", "not_started") if phase in counts)
        self.demo_result_hint.set("启动检查失败 · " + summary if self.demo_start_error else summary or DEMO_RESULTS_EMPTY)
        first = next((key for key in self.demo_order if self.demo_timings[key]["phase"] == "failed"),
                     self.demo_order[0] if self.demo_order else None)
        if first is not None:
            self.demo_results.selection_set(first)
            self.demo_results.see(first)
        self.demo_result_selected()
        if self.demo_start_error or (len(self.demo_order) > 1 and self.demo_log_at_end()):
            self.demo_output.select(self.demo_result_page)

    def demo_result_selected(self):
        self.update_demo_result_controls()
        selected = self.demo_results.selection()
        key = selected[0] if selected else None
        if key not in self.demo_timings or key not in self.demo_tasks:
            self.demo_detail_frame.grid_remove()
            return
        phase = self.demo_timings[key]["phase"]
        card = self.demo_grid.cards.get(key)
        scripts = card.scripts if card else {}
        errors = list(dict.fromkeys(event["error"] for event in scripts.values() if event.get("error")))
        if self.demo_start_error and self.demo_start_error not in errors:
            errors.insert(0, self.demo_start_error)
        next_step = {
            "failed": "处理异常后可重跑该模块。",
            "not_started": "可以从本页重跑未启动的模块。",
            "skipped": "如需补测，从左侧选中模块后点“运行当前”。",
            "stopped": "如需补测，从左侧选中模块后点“运行当前”。",
        }.get(phase)
        if self.demo_needs_refresh:
            next_step = "处理上述问题后，先点击左侧“刷新”。"
        elif self.demo_start_error:
            next_step = "处理上述问题后，可重跑未启动的模块。"
        elif phase == "failed" and key in self.demo_module_logs:
            next_step = "点“查看日志”定位异常，处理后可重跑。"
        lines = []
        for script, event in scripts.items():
            code = event.get("exit_code")
            status = PHASES.get(event.get("phase"), "待运行")
            if code is not None:
                status += " · 退出码 {}".format(code)
            lines.append("{} · {}".format(script, status))
        detail = self.demo_result_detail
        detail.configure(state="normal")
        detail.delete("1.0", "end")
        detail.insert("end", self.demo_results.set(key, "module") + "\n", "module")
        detail.insert("end", "\n".join(errors + ([next_step] if next_step else []) + lines))
        detail.configure(state="disabled")
        self.demo_detail_frame.grid()

    def update_demo_result_controls(self):
        selected = self.demo_results.selection()
        self.demo_result_log_button.configure(
            state="normal" if not self.busy and selected and selected[0] in self.demo_module_logs else "disabled")
        self.demo_retry_button.configure(
            state="normal" if not self.busy and self.demo_finished_at is not None and self.demo_retry_keys() else "disabled")

    def show_demo_result_log(self, event=None):
        if self.busy:
            return
        selected = self.demo_results.selection()
        if event is not None and event.type == tk.EventType.ButtonPress:
            key = self.demo_results.identify_row(event.y)
        else:
            key = selected[0] if selected else None
        if key in self.demo_module_logs:
            self.demo_log_mode.set("当前模块日志")
            self.demo_output.select(self.demo_log_page)
            self.demo_grid.reveal(key)

    def demo_live_summary(self):
        if not self.demo_active_ids:
            return
        counts = {"running": 0, "completed": 0, "failed": 0, "stopped": 0, "not_started": 0, "waiting": 0, "skipped": 0}
        for key in self.demo_active_ids:
            card = self.demo_grid.cards.get(key)
            phases = [s.get("phase") for s in card.scripts.values()] if card else []
            status = ("running" if "running" in phases else "failed" if "failed" in phases else
                      "completed" if phases and all(p == "completed" for p in phases) else
                      "skipped" if "skipped" in phases else
                      "stopped" if "stopped" in phases else "not_started" if "not_started" in phases else "waiting")
            counts[status] += 1
        self.demo_count.configure(text="运行 {} · 完成 {}".format(counts["running"], counts["completed"]))
        self.demo_status.set("本批次 {} 个模块：运行 {}，完成 {}，异常 {}，已跳过 {}，已停止 {}，等待 {}，未启动 {}。".format(
            len(self.demo_active_ids), counts["running"], counts["completed"], counts["failed"], counts["skipped"], counts["stopped"], counts["waiting"], counts["not_started"]))

    def complete_demo(self, code):
        phases = {timing["phase"] for timing in self.demo_timings.values()}
        stopped = "stopped" in phases or (code == 130 and self.cancel.is_set() and "failed" not in phases)
        self.finish_demo_cards("stopped" if stopped else "failed" if code else "completed")
        skipped = sum(t["phase"] == "skipped" for t in self.demo_timings.values())
        if stopped:
            text = "Demo 已停止。"
        elif code:
            text = "Demo 异常退出（{}），请查看右侧日志。".format(code)
        else:
            text = "Demo 队列结束，已跳过 {} 个模块。".format(skipped) if skipped else "Demo 正常结束。"
        self.demo_status.set(text)
        self.status.set(text)
        self.invalidate_check()

    def stop_demo(self):
        if self.demo_running:
            self.cancel.set()
            self.update_demo_controls()
            self.demo_status.set("正在停止本次启动的 Demo，请等待进程退出…")

    def refresh_config_choices(self):
        if self.closing or self.busy or not self.engine or Path(self.target.get()).expanduser().resolve() != self.engine.target:
            return
        previous = self.config_tree.selection()
        selected = previous[0] if previous else None
        engine = self.engine
        user_only = not self.engineer_mode
        if user_only:
            self.config_preview = None
            self.config_tree.delete(*self.config_tree.get_children())
            self.config_mapping.delete(*self.config_mapping.get_children())
            self.task_mode.set("配置版本：读取中")
        def done(result):
            versions, current = result
            self.config_refreshing = True
            self.config_preview = None
            self.config_tree.delete(*self.config_tree.get_children())
            self.config_mapping.delete(*self.config_mapping.get_children())
            for item in versions:
                label = item.get("display_name", item["version"]) if user_only else item["version"]
                self.config_tree.insert("", "end", iid=item["version"], values=(label, "可用" if item["valid"] else "不可用", "；".join(item["issues"])))
            if selected and self.config_tree.exists(selected):
                self.config_tree.selection_set(selected)
            self.task_mode.set(current)
            self.status.set("请选择需要使用的配置版本。" if versions else "当前没有可用的用户配置，请联系实施人员。"
                            if user_only else "config 下没有版本文件夹。")
            def finished():
                self.config_refreshing = False
                if selected:
                    self.preview_config_selection()
            self.root.after_idle(finished)
        self.run(lambda: (engine.list_config_versions(user_only=user_only), engine.task_config_status(user_only=user_only)), done)

    def edit_config_visibility(self):
        if self.busy or not self.engineer_mode or not self.ensure_engine():
            return
        from config_visibility_ui import show_visibility_editor
        try:
            show_visibility_editor(self.root, self.engine, self.refresh_config_choices)
        except (SyncError, OSError) as exc:
            messagebox.showerror("无法打开版本显示设置", str(exc))

    def preview_config_selection(self):
        self.config_preview = None
        self.config_mapping.delete(*self.config_mapping.get_children())
        self.update_ready()
        if self.busy or self.config_refreshing:
            return
        selection = self.config_tree.selection()
        if not selection or not self.engine:
            return
        name = selection[0]
        user_only = not self.engineer_mode
        def done(result):
            if self.config_tree.selection() != (name,):
                return
            self.config_preview = result
            for row in result["mappings"]:
                action = row.get("action", row["status"])
                self.config_mapping.insert("", "end", iid=row["active"], values=(row["source"], row["active"], action),
                                           tags=("same" if action == "相同" else "different",))
            comparable = [row["active"] for row in result["mappings"] if row["status"] == "有效"]
            if comparable:
                self.config_mapping.selection_set(comparable[0])
            self.status.set("版本有效，确认后将一次替换三个生效 JSON。" if result["valid"] else "不可应用：" + "；".join(result["issues"]))
            self.update_ready()
        self.run(lambda: self.engine.preview_config_version(name, user_only=user_only), done)

    def compare_config_selection(self):
        if self.busy or not self.config_preview or not self.config_mapping.selection() or not self.ensure_engine():
            return
        preview = self.config_preview
        name = self.config_mapping.selection()[0]
        if name not in preview["sources"] or "snapshot" not in preview:
            return
        engine = self.engine
        self.run(lambda: engine.compare_config_file(preview["version"], name, preview["snapshot"], self.cancel), self.show_config_comparison)

    def show_config_comparison(self, report):
        summary = format_comparison(report, include_diff=False)
        self.logger.info("配置 JSON 对比\n%s", summary)
        self.append("\n" + summary)
        window = tk.Toplevel(self.root)
        style_dialog(window)
        self.config_diff_window = window
        window.title("配置 JSON 对比 · " + report["name"] + " · " + report["version"])
        window.geometry("1080x720")
        window.minsize(800, 500)
        pages = ttk.Notebook(window)
        window.pages = pages
        pages.pack(fill="both", expand=True, padx=8, pady=8)
        overview = ttk.Frame(pages)
        pages.add(overview, text="对比摘要")
        text = tk.Text(overview, wrap="word", padx=10, pady=10)
        scroll = ttk.Scrollbar(overview, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", summary)
        text.configure(state="disabled")
        window.summary_text = text
        formatted = None
        if report["json_diff"] is not None:
            formatted, window.json_diff_text = self.add_diff_page(pages, "JSON 内容差异（格式化）", report["json_diff"], report["json_note"])
        raw, window.raw_diff_text = self.add_diff_page(pages, "原始文本差异", report["raw_diff"])
        pages.select(formatted if formatted is not None else raw)
        footer = ttk.Frame(window, padding=8)
        footer.pack(fill="x")
        def copy_report():
            content = format_comparison(report)
            if report["json_diff"] is not None:
                content += "\n\n原始文本差异：\n" + format_diff(report["raw_diff"])
            window.clipboard_clear()
            window.clipboard_append(content)
        ttk.Button(footer, text="复制完整对比", command=copy_report).pack(side="left")
        ttk.Button(footer, text="关闭", command=window.destroy).pack(side="right")
        self.status.set("JSON 对比完成：{}；只读查看，未应用配置。".format(report["status"]))

    def apply_config(self):
        if not self.ensure_engine() or not self.config_preview:
            return
        preview = self.config_preview
        user_only = not self.engineer_mode
        if not preview["valid"]:
            messagebox.showerror("版本不可用", "\n".join(preview["issues"]))
            return
        mapping = "\n".join(row["source"] + " → " + row["active"] for row in preview["mappings"])
        label = preview.get("display_name", preview["version"]) if user_only else preview["version"]
        detail = "" if user_only else "\n" + mapping
        if not messagebox.askyesno("应用整套配置", "版本：" + label + detail + "\n\n将应用此配置。请先退出主程序，是否应用？"):
            return
        def done(result):
            self.invalidate_check()
            self.config_preview = None
            self.update_current()
            if user_only:
                self.status.set("配置已应用：" + label)
            else:
                self.log("整套配置已应用：" + result["version"] + "；备份：" + result["backup"])
        self.run(lambda: self.engine.activate_config_version(preview["version"], expected_snapshot=preview["snapshot"],
                 log=self.logger.info if user_only else self.log, user_only=user_only), done)

    def refresh(self):
        if not self.ensure_engine():
            return
        repo, branch = self.repo.get().strip(), self.branch.get().strip()
        if not repo:
            messagebox.showinfo("仓库未填写", "可以先导入本地 catalog；创建仓库后再填写地址。")
            return
        def work():
            source = Source.remote(repo, branch)
            return remote_profiles(source, self.presets)
        def done(items):
            cached = [p for p in self.profiles if "manifest" in p]
            self.profiles = items + cached
            self.show_profiles()
            self.status.set("远端方案已更新，新增 publish_* 目录会自动出现；尚未修改 publish。")
        self.run(work, done)

    def import_local(self):
        if not self.ensure_engine():
            return
        path = filedialog.askopenfilename(title="选择本地资源仓库的 catalog.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.run(lambda: (Source(local=Path(path).parent), validate_catalog(read_json(path))), self.receive_catalog)

    def receive_catalog(self, result):
        source, catalog = result
        # Keep older cached versions available for offline use.
        cached = [p for p in self.profiles if "manifest" in p]
        self.profiles = [{"source": source, "profile": p} for p in catalog["profiles"]] + cached
        self.show_profiles()
        self.status.set("方案列表已更新；尚未修改 publish。")

    def choice(self):
        if not self.ensure_engine():
            return None
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("选择方案", "请先选择一个方案。")
            return None
        item = self.profiles[int(selected[0])]
        if item.get("preset_only"):
            messagebox.showinfo("刷新方案", "这是初始预设，请先刷新远端方案。")
            return None
        return item

    def get_manifest(self, item):
        if "manifest" not in item:
            manifest = (directory_manifest(item["source"], item["directory_preset"], item["git_tree"])
                        if "directory_preset" in item else load_profile(item["source"], item["profile"]))
            with self.engine.lock():
                self.engine.save_profile(manifest, item["source"])
            item["manifest"] = manifest
        return item["manifest"]

    def record_formats(self, manifest):
        self.format_inventory = {"id": manifest["id"], "name": manifest.get("name", manifest["id"]),
                                 "version": manifest["version"], "repo": self.repo.get().strip(),
                                 "formats": inventory(manifest)}
        if CONFIG.exists():
            self.save_formats()

    def save_formats(self):
        if self.target.get() and is_relative_to(CONFIG.resolve(), Path(self.target.get()).expanduser().resolve()):
            raise SyncError("设置文件必须位于 publish 外。")
        data = read_json(CONFIG) if CONFIG.exists() else {}
        data.update(file_extensions=list(self.file_extensions), format_inventory=self.format_inventory)
        atomic_json(CONFIG, data)

    def read_formats(self):
        if self.busy:
            return
        item = self.choice()
        if item:
            self.run(lambda: self.get_manifest(item), self.show_formats)

    def show_formats(self, manifest):
        self.record_formats(manifest)
        dialog = tk.Toplevel(self.root)
        dialog.title("同步格式 · " + manifest.get("name", manifest["id"]))
        style_dialog(dialog)
        dialog.geometry("620x480")
        dialog.transient(self.root)
        dialog.grab_set()
        ttk.Label(dialog, text="按远端方案的普通文件识别格式；只读取清单，不下载资源正文。", wraplength=570).pack(anchor="w", padx=16, pady=(14, 6))
        ttk.Label(dialog, text="严格更新会替换／删除勾选格式的文件；未勾选格式保留。\n新发现的格式默认不勾选。字体按资源文件部署，不安装到系统字体目录。",
                  style="Muted.TLabel", wraplength=570).pack(anchor="w", padx=16, pady=(0, 8))
        actions = ttk.Frame(dialog, padding=(16, 8))
        actions.pack(side="bottom", fill="x")
        body = ttk.Frame(dialog, padding=(16, 0))
        body.pack(fill="both", expand=True)
        canvas = tk.Canvas(body, highlightthickness=0, background=COLORS["bg"])
        scroll = ttk.Scrollbar(body, command=canvas.yview)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        content = ttk.Frame(canvas)
        child = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(child, width=event.width))
        content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        rows = {row["extension"]: row for row in inventory(manifest)}
        variables = {}
        for ext in sorted(set(rows) | set(self.file_extensions) | set(DEFAULT_EXTENSIONS)):
            row = rows.get(ext, {"count": 0, "bytes": 0, "unavailable": 0})
            variables[ext] = tk.BooleanVar(value=ext in self.file_extensions)
            text = "{}   {} 个文件 · {:.2f} MiB{}".format(label(ext), row["count"], row["bytes"] / 1024**2,
                    "（含仅元数据条目，发布方需补齐）" if row["unavailable"] else "")
            ttk.Checkbutton(content, text=text, variable=variables[ext]).pack(anchor="w", pady=5)
        def defaults():
            for ext, variable in variables.items():
                variable.set(ext in DEFAULT_EXTENSIONS)
        def save():
            try:
                selected = normalize_extensions([ext for ext, var in variables.items() if var.get()])
                old = self.file_extensions
                self.file_extensions = selected
                try:
                    self.save_formats()
                except Exception:
                    self.file_extensions = old
                    raise
                if self.engine:
                    self.engine.extensions = selected
                self.format_text.set("同步格式…（{} 种）".format(len(selected)))
                self.invalidate_check()
                self.status.set("格式选择已保存：" + describe_formats(selected) + "；请重新检查方案。")
                dialog.destroy()
            except (OSError, ValueError, SyncError) as exc:
                messagebox.showerror("格式设置未保存", str(exc), parent=dialog)
        ttk.Button(actions, text="恢复默认", command=defaults).pack(side="left")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="保存格式选择", style="Primary.TButton", command=save).pack(side="right", padx=8)
        dialog.format_variables = variables
        dialog.save_selection = save
        return dialog

    def preview(self):
        item = self.choice()
        if not item:
            return
        sync_permissions = self.sync_permissions.get()
        self.engine.extensions = self.file_extensions
        def work():
            m = self.get_manifest(item)
            with self.engine.lock():
                self.engine.recover()
                strict = self.engine.preview(m, self.cancel, mode="strict", sync_permissions=sync_permissions)
                incremental = self.engine.preview(m, self.cancel, mode="incremental", actual=strict["actual"], sync_permissions=sync_permissions)
            return m, {"strict": strict, "incremental": incremental}
        def done(result):
            m, plans = result
            self.record_formats(m)
            self.checked = {"item": item, "manifest": m, "plans": plans, "actual": plans["strict"]["actual"], "sync_permissions": sync_permissions}
            self.diff_tree.delete(*self.diff_tree.get_children())
            for row in plans["strict"]["comparison"]:
                tag = "same" if row["status"] in ("相同", "内容相同") else "permission" if row["status"] == "权限不同" else "different"
                self.diff_tree.insert("", "end", values=(row["status"], row["path"], row["incremental"], row["strict"], row.get("permissions", "—")), tags=(tag,))
            self.mode_changed()
            self.status.set("比较完成，请选择增量或严格更新，再点击执行更新。")
        self.run(work, done)

    def invalidate_check(self):
        self.checked = None
        self.invalidate_assets()
        self.update_summary.set("尚未检查。请选择方案，再检查差异。")
        if hasattr(self, "diff_tree"):
            self.diff_tree.delete(*self.diff_tree.get_children())
        self.update_ready()

    def invalidate_assets(self):
        self.assets_checked = None
        if hasattr(self, "assets_tree"):
            self.assets_tree.delete(*self.assets_tree.get_children())
        self.assets_summary.set("请检查资源差异；只补缺失文件，已有资源保留。")
        self.update_ready()

    def assets_choice(self):
        if not self.ensure_engine():
            return None
        index = self.assets_combo.current()
        if index < 0 or index >= len(self.assets_profiles):
            messagebox.showinfo("选择方案", "请先选择 Assets 资源方案。")
            return None
        item = self.assets_profiles[index]
        if item.get("preset_only"):
            messagebox.showinfo("刷新方案", "这是预设方案，请先刷新远端方案或导入本地清单。")
            return None
        return item

    def preview_assets(self):
        if self.busy:
            return
        item = self.assets_choice()
        if item is None:
            return
        target = self.engine.target
        self.invalidate_assets()
        def work():
            manifest = self.get_manifest(item)
            engine = AssetsEngine(target)
            Engine(target).startup_recover()
            with engine.lock():
                engine.recover()
                engine.save_profile(manifest, item["source"])
                return manifest, engine.preview_assets(manifest, self.cancel, self.log)
        def done(result):
            manifest, preview = result
            self.assets_checked = {"item": item, "manifest": manifest, "preview": preview, "target": target}
            self.assets_tree.delete(*self.assets_tree.get_children())
            for row in preview["comparison"]:
                local, remote = row["local"], row["remote"]
                self.assets_tree.insert("", "end", iid=row["path"], values=(row["status"], row["path"],
                    "{:,}".format(local["size"]) if local and "size" in local else "—", "{:,}".format(remote["size"]) if remote else "—",
                    row["action"], "已校验" if row["cached"] else "—"), tags=("same" if row["status"] == "相同" else "local" if row["status"] == "仅本地" else "different",))
            self.assets_summary.set("缺失 {} 项 · 新增资源 {:.2f} MiB · 需下载 {:.2f} MiB{}".format(
                len(preview["changes"]), preview["resource_bytes"] / 1024**2, preview["download_bytes"] / 1024**2,
                " · 无法下载，详见日志" if preview["blocker"] else " · 已有文件不覆盖"))
            self.append(assets_report(manifest, preview))
            if preview["blocker"]:
                self.set_log_visible(True)
            self.status.set("Assets 比较完成，尚未修改 publish。")
        self.run(work, done)

    def show_assets_details(self):
        if self.busy or not self.assets_checked or not self.assets_tree.selection():
            return
        checked = self.assets_checked
        path = self.assets_tree.selection()[0]
        row = next(row for row in checked["preview"]["comparison"] if row["path"] == path)
        self.show_diagnostic(assets_details(AssetsEngine(checked["target"]), checked["manifest"], checked["item"]["source"], row))

    def download_assets(self):
        if self.busy or not self.assets_checked:
            return
        item = self.assets_choice()
        checked = self.assets_checked
        if not item or item is not checked["item"]:
            self.invalidate_assets()
            return
        preview = checked["preview"]
        if preview["blocker"] or not preview["changes"]:
            return
        if not messagebox.askyesno("下载缺失的 Assets 资源", "目标：{}\n方案：{}\n缺失 {} 项，需下载 {:.2f} MiB。\n\n只新增缺失资源，已有文件不覆盖，本地多余资源不删除。\n请先退出主程序及相关任务，是否下载？".format(
                checked["target"], checked["manifest"].get("name", checked["manifest"]["id"]), len(preview["changes"]), preview["download_bytes"] / 1024**2)):
            return
        self.invalidate_check()
        def done(result):
            self.config_preview = None
            self.invalidate_assets()
            self.invalidate_demo_tasks()
            self.status.set("Assets 资源下载完成，已有资源保持原样。")
            self.assets_summary.set("Assets 下载完成；重新检查可确认缺失文件已补齐。")
            self.append("Assets 备份：" + str(self.engine.state / "backups" / result["backup"]) if result.get("backup") else "Assets 无需下载。")
        self.run(lambda: AssetsEngine(checked["target"]).download_missing(checked["manifest"], item["source"],
                      expected_actual=preview["actual"], cancel=self.cancel, log=self.log), done)

    def permissions_changed(self):
        self.invalidate_check()
        self.status.set("权限策略已改变，请重新检查差异；保存设置后下次沿用。")

    def update_ready(self):
        if hasattr(self, "phase_badge"):
            self.phase_badge.set_phase("running" if self.demo_running else "busy" if self.busy else "error" if self.last_error else "idle")
        state = "normal" if self.checked is not None and not self.busy else "disabled"
        if hasattr(self, "apply_button"):
            self.apply_button.configure(state=state)
        if hasattr(self, "diagnose_button"):
            selected = hasattr(self, "diff_tree") and self.diff_tree.selection()
            self.diagnose_button.configure(state="normal" if self.checked and selected and not self.busy else "disabled")
        for button in getattr(self, "mode_buttons", []):
            button.configure(state=state)
        if hasattr(self, "config_apply_button"):
            valid = self.config_preview and self.config_preview.get("valid") and not self.busy
            self.config_apply_button.configure(state="normal" if valid else "disabled")
        if hasattr(self, "config_compare_button"):
            selection = self.config_mapping.selection()
            valid = self.config_preview and "snapshot" in self.config_preview and selection and selection[0] in self.config_preview["sources"]
            self.config_compare_button.configure(state="normal" if valid and not self.busy else "disabled")
        for button in getattr(self, "permission_preset_buttons", []):
            button.configure(state="normal" if sys.platform == "linux" and not self.busy else "disabled")
        if hasattr(self, "demo_run_button"):
            selection = self.demo_grid.selected
            valid = selection and self.demo_tasks.get(selection, {}).get("valid")
            has_valid = any(item["valid"] for item in self.demo_tasks.values())
            checked = len(self.demo_grid.checked_keys())
            can_run = not self.busy and not self.demo_needs_refresh
            self.demo_run_button.configure(state="normal" if valid and can_run else "disabled")
            self.demo_all_button.configure(state="normal" if can_run and has_valid else "disabled")
            self.demo_checked_button.configure(text="运行勾选 ({})".format(checked) if checked else "运行勾选",
                                               state="normal" if checked and can_run else "disabled")
            self.demo_select_all_button.configure(state="normal" if has_valid and not self.busy else "disabled")
            self.demo_clear_button.configure(state="normal" if checked and not self.busy else "disabled")
            self.demo_grid.enabled = not self.busy or self.demo_running
            self.demo_grid.enable_checking(not self.busy)
            self.demo_stop_button.configure(state="normal" if self.demo_running else "disabled")
            self.update_demo_controls()
            self.update_demo_result_controls()
        if hasattr(self, "assets_apply_button"):
            ready = self.assets_checked and not self.busy
            valid = ready and self.assets_checked["preview"]["changes"] and not self.assets_checked["preview"]["blocker"]
            self.assets_apply_button.configure(state="normal" if valid else "disabled")
            self.assets_details_button.configure(state="normal" if ready and self.assets_tree.selection() else "disabled")
            self.assets_combo.configure(state="readonly" if not self.busy else "disabled")
        if self.updates_enabled:
            self.program_check_button.configure(state="normal" if not self.program_checking and not self.busy else "disabled")
            self.program_apply_button.configure(state="normal" if self.program_release and not self.program_checking and not self.busy else "disabled")
            self.program_offline_button.configure(state="normal" if not self.program_checking and not self.busy else "disabled")

    def apply_permission_preset(self, preset):
        if self.busy or not self.ensure_engine():
            return
        if sys.platform != "linux":
            messagebox.showinfo("仅支持 Linux", "权限预设请在 Ubuntu 设备上使用。")
            return
        engine = self.engine
        detail = "目标：{}\n\n{}\n\n递归修改这个目录及全部文件，包括主程序、模型和日志。".format(engine.target, command_text(engine.target, preset))
        if preset in ("777", "root-and-777"):
            detail += "\n777 将允许所有用户读取、修改和执行其中的文件。"
        detail += "\n这项操作不生成备份，失败可能部分完成。请先退出主程序和相关任务。\n是否继续并请求管理员授权？"
        if not messagebox.askyesno("确认权限预设：" + PRESETS[preset], detail):
            return
        self.invalidate_check()
        self.config_preview = None
        def done(result):
            self.config_tree.delete(*self.config_tree.get_children())
            self.config_mapping.delete(*self.config_mapping.get_children())
            self.task_mode.set("配置版本：权限已变化，请刷新版本列表")
            self.status.set("权限预设完成，请重新检查文件差异。")
            self.append("权限预设完成：" + PRESETS[result["preset"]] + "；目标：" + result["target"])
        self.run(lambda: launch_preset(engine, preset, self.log), done, cancellable=False)

    def add_diff_page(self, pages, title, diff, extra_note=""):
        frame = ttk.Frame(pages)
        pages.add(frame, text=title)
        ttk.Label(frame, text=(extra_note + "\n" if extra_note else "") + diff["note"], wraplength=1020).pack(anchor="w", padx=8, pady=6)
        ttk.Label(frame, text="{}新增 {} 行，删除 {} 行；左侧两列为旧版行号 / 新版行号。".format(
            "已显示：" if diff["truncated"] else "", diff["added"], diff["deleted"])).pack(anchor="w", padx=8)
        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, padx=6, pady=6)
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        changes = tk.Text(holder, wrap="none", font="TkFixedFont", background=COLORS["field"], foreground=COLORS["text"], padx=8, pady=8)
        vertical = ttk.Scrollbar(holder, command=changes.yview)
        horizontal = ttk.Scrollbar(holder, orient="horizontal", command=changes.xview)
        changes.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        changes.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        for kind, fg, bg in (("add", COLORS["green"], COLORS["green_bg"]), ("delete", COLORS["red"], COLORS["red_bg"]),
                             ("hunk", COLORS["accent"], "#1d2b3c"), ("header", COLORS["muted"], COLORS["panel"]),
                             ("note", COLORS["muted"], COLORS["field"])):
            changes.tag_configure(kind, foreground=fg, background=bg)
        for row in diff["rows"]:
            numbers = "{:>5} {:>5}  ".format(row.get("old_line") or "", row.get("new_line") or "")
            changes.insert("end", numbers + visible_diff_line(row["text"]) + "\n", row["kind"])
        changes.configure(state="disabled")
        return frame, changes

    def show_diagnostic(self, report):
        summary = format_report(report, include_diff=False) if isinstance(report, dict) else report
        diff = report.get("diff") if isinstance(report, dict) else None
        self.append("\n" + summary)
        self.logger.info("比较诊断\n%s", summary)
        window = tk.Toplevel(self.root)
        style_dialog(window)
        self.diagnostic_window = window
        window.title("只读比较诊断")
        window.geometry("1080x720")
        window.minsize(800, 500)
        pages = ttk.Notebook(window)
        pages.pack(fill="both", expand=True, padx=8, pady=8)
        overview = ttk.Frame(pages)
        pages.add(overview, text="诊断摘要")
        text = tk.Text(overview, wrap="word", padx=10, pady=10)
        window.summary_text = text
        scroll = ttk.Scrollbar(overview, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.pack(fill="both", expand=True)
        text.configure(yscrollcommand=scroll.set)
        text.insert("1.0", summary)
        text.configure(state="disabled")
        if diff:
            frame, window.diff_text = self.add_diff_page(pages, "文本差异（本地 → 远端）", diff)
            if diff["rows"] or diff["kind"] != "same":
                pages.select(frame)
        footer = ttk.Frame(window)
        footer.pack(fill="x", padx=8, pady=(0, 8))
        def copy_report():
            window.clipboard_clear()
            window.clipboard_append(format_report(report) if isinstance(report, dict) else report)
        ttk.Button(footer, text="复制完整报告", command=copy_report).pack(side="left")
        ttk.Button(footer, text="关闭", command=window.destroy).pack(side="right")
        self.status.set("诊断完成，publish 未修改；摘要已写入日志，完整差异可复制。")

    def diagnose_selected(self):
        if not self.checked or not self.diff_tree.selection() or self.busy:
            return
        checked = self.checked
        path = self.diff_tree.item(self.diff_tree.selection()[0], "values")[1]
        self.run(lambda: diagnose_file(self.engine, checked["manifest"], checked["item"]["source"], path, cancel=self.cancel,
                                      sync_permissions=checked["sync_permissions"]), self.show_diagnostic)

    def run_comparison_self_test(self):
        self.run(lambda: comparison_self_test(self.cancel), self.show_diagnostic)

    def mode_changed(self):
        if self.checked:
            self.display_preview((self.checked["manifest"], self.checked["plans"][self.update_mode.get()]))
        self.update_ready()

    def display_preview(self, result):
        m, preview = result
        mode = "增量更新" if preview.get("mode") == "incremental" else "严格更新"
        self.update_summary.set("{} · 变更 {} 项 · 需下载 {:.2f} MiB{}".format(
            mode, len(preview["changes"]), preview["download_bytes"] / 1024**2,
            " · 当前方案无法应用，详见日志" if preview.get("blocker") else
            " · 其他资源提示 {} 项（见日志）".format(len(preview["notices"])) if preview.get("notices") else ""))
        if preview.get("blocker"):
            self.set_log_visible(True)
        self.append(f"\n方案：{m.get('name', m['id'])} / {m['version']}")
        if preview.get("blocker"):
            self.append("不能应用：" + preview["blocker"])
        self.append("更新方式：" + ("增量（只补齐缺失）" if preview.get("mode") == "incremental" else "严格（替换差异并删除本地多余文件）"))
        self.append("权限策略：" + ("严格更新同步仓库权限；增量跳过已有文件。" if preview["sync_permissions"] else "保留本地已有文件权限；新文件用仓库权限。"))
        self.append("同步格式：" + describe_formats(preview["extensions"]))
        self.append(f"变更 {len(preview['changes'])} 项；需下载 {preview['download_bytes'] / 1024**2:.2f} MiB")
        for action, path in preview["changes"]:
            self.append(f"{action}  {path}")
        self.append("其他文件不下载、不覆盖、不删除；只比较是否存在、类型和大小，不校验其内容。")
        for notice, path in preview.get("notices", []):
            self.append(f"{notice}  {path}")
        self.status.set("检查完成；尚未修改 publish。")

    def apply(self):
        item = self.choice()
        if not item:
            return
        if not self.checked or self.checked["item"] is not item:
            messagebox.showinfo("先检查差异", "请先检查当前方案，再选择更新方式。")
            return
        checked, mode = self.checked, self.update_mode.get()
        m, preview = checked["manifest"], checked["plans"][mode]
        if preview["blocker"]:
            messagebox.showerror("资源不完整", preview["blocker"])
            return
        if not preview["changes"]:
            messagebox.showinfo("无需更新", "当前更新方式没有需要修改的文件。已有文件将保持原样。")
            return
        detail = "只新增缺失文件；已有文件跳过，本地多余文件保留。" if mode == "incremental" else "替换差异并删除所选格式的多余文件；勾选 JSON 时包括当前生效配置。"
        detail += "\n同步格式：" + describe_formats(preview["extensions"])
        detail += "\n权限：" + ("严格更新按仓库同步，增量跳过已有文件。" if checked["sync_permissions"] else "保留本地已有文件权限，新文件使用仓库权限。")
        if not messagebox.askyesno("确认更新", f"目标：{self.engine.target}\n方案：{m.get('name', m['id'])}\n变更：{len(preview['changes'])} 项\n\n{detail}\n请先退出相关任务，是否执行？"):
            return
        self.run(lambda: self.engine.apply(m, item["source"], self.cancel, self.log, mode=mode, expected_actual=checked["actual"],
                                          sync_permissions=checked["sync_permissions"]), self.applied)

    def applied(self, result):
        self.logger.info("所选格式操作完成：%s", result)
        self.invalidate_check()
        self.update_current()
        if result.get("unchanged"):
            self.status.set("无需更新，未修改任何文件。")
            return
        self.status.set("同步完成。请重新启动主程序。")
        self.append("所选格式同步完成，其他文件保持原样。备份：" + str(self.engine.state / "backups" / result["backup"]))

    def restore(self):
        if not self.ensure_engine():
            return
        if messagebox.askyesno("恢复上次更新", "请先退出相关任务。\n按上次同步记录的格式范围恢复备份，其他格式保留。是否恢复？"):
            self.run(lambda: self.engine.restore(self.log), self.applied)

    def close(self):
        if self.busy:
            prompt = ("IoT Demo 正在运行。停止本次任务并在进程退出后关闭？" if self.demo_running else
                      "正在操作。取消准备并在操作安全结束后关闭？目录切换阶段将等待完成。"
                      if self.operation_cancellable else "权限预设正在处理，将等待授权或命令结束后关闭。是否等待并关闭？")
            if messagebox.askyesno("等待操作安全结束", prompt):
                self.closing = True
                self.cancel.set()
        else:
            self.root.destroy()


if __name__ == "__main__":
    from switcher import main
    raise SystemExit(main(["gui"]))
