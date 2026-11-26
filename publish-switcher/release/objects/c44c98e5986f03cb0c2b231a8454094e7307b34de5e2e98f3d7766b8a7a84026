"""桌面主窗口。

普通用户看程序更新与配置切换；Ctrl+Shift+F12 切换工程师面板。
网络与磁盘任务在后台线程执行，结果经事件队列回到 Tk 线程。
"""
import json
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from publish_switcher.common.paths import INSTALL_ROOT
from publish_switcher.common.compat import is_relative_to
from publish_switcher.common.errors import SyncError
from publish_switcher.sync.engine import Engine
from publish_switcher.repositories.source import Source
from publish_switcher.common.files import read_json
from publish_switcher.common.diagnostics import settings_path
from publish_switcher.common.settings import read_settings, save_settings
from publish_switcher.repositories.catalog import (
    DEFAULT_PROFILES,
    validate_presets,
    repository_from_settings,
    REPOSITORY_DEFAULT_VERSION,
)
from publish_switcher.repositories.discovery import (
    candidates as repository_candidates,
    discover as discover_repositories,
)
from publish_switcher.sync.diagnostics import format_report, comparison_self_test, visible_diff_line
from publish_switcher.sync.permissions import PRESETS, command_text, launch_preset
from publish_switcher.demo.runner import DemoPreflightError
from publish_switcher.gui.pages.demo import DemoPage
from publish_switcher.gui.widgets.style import (
    COLORS,
    NavButton,
    StatusBadge,
    apply_theme,
    style_dialog,
)
from publish_switcher.sync.formats import DEFAULT_EXTENSIONS, normalize_extensions
from publish_switcher.version import VERSION
from publish_switcher.updates import release as tool_update
from publish_switcher.updates import unified as unified_update
from publish_switcher.gui.pages.configuration import ConfigurationPage
from publish_switcher.gui.pages.program import ProgramPage
from publish_switcher.gui.pages.files import FilesPage
from publish_switcher.gui.pages.assets import AssetsPage
from publish_switcher.gui.pages.settings import SettingsPage


CONFIG = settings_path()


class Application:
    """主应用：侧栏导航、用户/工程师模式切换、后台任务与更新小窗。"""

    def __init__(self, root, engineer=True, updates=False, *, auto_update=False, resume_update=False):
        self.root = root
        auto_update = auto_update and updates and not engineer
        self.startup_window = None
        if auto_update:
            root.withdraw()
        from publish_switcher.gui.widgets.icons import set_window_icon
        set_window_icon(root)
        self.config_view = ConfigurationPage(self)
        self.program_view = ProgramPage(self)
        self.files_view = FilesPage(self)
        self.assets_view = AssetsPage(self)
        self.settings_view = SettingsPage(self)
        self.engineer_mode = engineer
        self.updates_enabled = updates
        self.program_checked = not updates
        self.program_view.program_release = None
        self.program_checking = False
        self.program_view.program_auto_enter = True
        self.update_channel = tk.IntVar(value=0)
        self.program_view.channel_snapshot = None
        self.program_view.channel_buttons = []
        self.program_view.program_notes_open = False
        self.program_view.channel_check_times = {}
        self.config_view.config_generation = 0
        self.quick_dialog = None
        self.quick_committing = threading.Event()
        self.install_directory = INSTALL_ROOT
        self.logger = logging.getLogger("publish-switcher")
        if not self.logger.handlers:
            self.logger.addHandler(logging.NullHandler())
        root.title("swicher")
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
        self.config_view.config_preview = None
        self.config_view.config_refreshing = False
        self.assets_view.assets_checked = None
        self.assets_view.assets_profiles = []
        self.assets_view.assets_summary = tk.StringVar(value="未检查")
        try:
            config = read_settings(CONFIG)
        except (OSError, ValueError):
            config = {}
        self.sync_permissions = tk.BooleanVar(value=config.get("sync_permissions") is True)
        self.update_mode.set(config.get("update_mode") if config.get("update_mode") in ("incremental", "strict") else "incremental")
        self.program_source = tk.StringVar(value=config.get("program_update_url", tool_update.DEFAULT_UPDATE_URL))
        self.quick_profile = tk.StringVar(value=config.get("quick_update_profile", "rk"))
        self.program_view.program_status = tk.StringVar(value="检查中…")
        self.program_view.program_notes = tk.StringVar(value="")
        self.program_view.program_version_text = tk.StringVar(value="v" + VERSION)
        try:
            self.file_extensions = normalize_extensions(config.get("file_extensions"))
        except ValueError:
            self.file_extensions = DEFAULT_EXTENSIONS
        self.format_inventory = config.get("format_inventory", {})
        self.format_text = tk.StringVar(value="同步格式…（{} 种）".format(len(self.file_extensions)))
        default_target = next((path for path in unified_update.DEFAULT_TARGETS if Path(path).is_dir()), "")
        self.target = tk.StringVar(value=config.get("target", "") or default_target)
        self.repo = tk.StringVar(value=repository_from_settings(config))
        self.branch = tk.StringVar(value=config.get("branch", ""))
        try:
            self.repository_sources = repository_candidates(config)
        except SyncError as exc:
            self.logger.warning("多仓库设置无效，暂用首选仓库：%s", exc)
            self.repository_sources = repository_candidates(config, explicit=True)
        self.repo.set(self.repository_sources[0]["url"])
        self.branch.set(self.repository_sources[0]["branch"])
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
        self.files_view.tree.bind("<<TreeviewSelect>>", lambda event: self.files_view.invalidate_check())
        self.target.trace_add("write", lambda *args: self.publish_changed())
        self.repo.trace_add("write", lambda *args: self.files_view.invalidate_check())
        self.branch.trace_add("write", lambda *args: self.files_view.invalidate_check())
        self.update_ready()
        self.config_view.config_tree.bind("<<TreeviewSelect>>", lambda event: self.config_view.preview_config_selection())
        self.config_view.config_mapping.bind("<<TreeviewSelect>>", lambda event: self.update_ready())
        self.config_view.config_mapping.bind("<Double-1>", lambda event: self.config_view.compare_config_selection())
        self.files_view.diff_tree.bind("<<TreeviewSelect>>", lambda event: self.update_ready())
        self.assets_view.assets_tree.bind("<<TreeviewSelect>>", lambda event: self.update_ready())
        self.assets_view.assets_combo.bind("<<ComboboxSelected>>", lambda event: self.assets_view.invalidate_assets())
        self.pages.bind("<<NotebookTabChanged>>", self.page_changed)
        if auto_update:
            from publish_switcher.gui.startup import StartupWindow
            self.pages.select(self.program_page)
            self.startup_window = StartupWindow(self)

            def begin_startup():
                self.program_view.program_check_id = None
                self.startup_window.start(resume_update)

            self.startup_window.show(begin_startup)
        elif updates and not engineer:
            self.pages.select(self.program_page)
            self.program_view.program_check_id = root.after(150, self.program_view.check_program_update)
        elif self.target.get():
            self.connect()
        elif engineer:
            self.pages.select(self.settings_page)

    @property
    def settings_file(self):
        return CONFIG

    def build_layout(self):
        self.controls = []
        self.engineer_widgets = []
        self.update_summary = tk.StringVar(value="未检查")
        self.log_visible = False
        self.font_family = apply_theme(self.root)
        self.sidebar_compact = False
        self.sidebar = tk.Frame(self.root, background=COLORS["sidebar"], width=206)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        tk.Frame(self.root, background=COLORS["border"], width=1).pack(side="left", fill="y")
        self.brand = tk.Canvas(self.sidebar, height=78, background=COLORS["sidebar"], highlightthickness=0)
        self.brand.pack(fill="x")
        self.brand.bind("<Configure>", lambda event: self.draw_brand())
        self.nav_frame = tk.Frame(self.sidebar, background=COLORS["sidebar"])
        self.nav_frame.pack(fill="x", padx=10, pady=(5, 0))
        self.sidebar_footer = tk.Frame(self.sidebar, background=COLORS["sidebar"])
        self.sidebar_footer.pack(side="bottom", fill="x", padx=20, pady=20)
        tk.Label(self.sidebar_footer, text="v" + VERSION, background=COLORS["sidebar"], foreground=COLORS["sidebar_muted"],
                 font=(self.font_family, 9)).pack(anchor="w", pady=(0, 8))
        self.workspace = ttk.Frame(self.root)
        self.workspace.pack(side="left", fill="both", expand=True)
        header = ttk.Frame(self.workspace, padding=(20, 12, 20, 8))
        self.header = header
        header.pack(fill="x")
        header.columnconfigure(0, weight=1)
        self.page_title = tk.StringVar(value="更新文件")
        self.heading_label = ttk.Label(header, textvariable=self.page_title, style="PageTitle.TLabel")
        self.heading_label.grid(row=0, column=0, sticky="w")
        self.phase_badge = StatusBadge(header, self.font_family)
        self.quick_update_button = ttk.Button(header, text="更新", style="Primary.TButton", command=self.program_view.start_quick_update)
        if self.updates_enabled:
            self.quick_update_button.grid(row=0, column=3, padx=(12, 0))
        self.config_header_refresh = ttk.Button(header, text="刷新配置", command=self.config_view.refresh_config_choices)
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
        self.footer = footer
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
        self.demo_page = DemoPage(self.pages, self, log_directory=lambda: CONFIG.parent / "logs/iot-demo")
        self.tools_page = ttk.Frame(self.pages, padding=12)
        self.settings_page = ttk.Frame(self.pages, padding=12)
        for page, name in ((self.update_page, "更新文件"), (self.assets_page, "Assets 资源"), (self.config_page, "配置切换"),
                           (self.demo_page, "IoT Demo"), (self.tools_page, "辅助工具"), (self.settings_page, "设置")):
            self.pages.add(page, text=name)
        self.files_view.build_update_page()
        self.assets_view.build_assets_page()
        self.config_view.build_config_page()
        self.demo_page.build()
        self.build_tools_page()
        self.settings_view.build_settings_page()
        if self.updates_enabled:
            self.program_page = ttk.Frame(self.pages, padding=12)
            self.pages.add(self.program_page, text="程序更新")
            self.program_view.build_program_page()
        self.nav_buttons = {}
        self.page_info = {}
        navigation = (
            (self.update_page, "更新文件", "文件"),
            (self.assets_page, "Assets 资源", "资源"),
            (self.config_page, "配置切换", "配置"),
            (self.demo_page, "IoT Demo", "Demo"),
            (self.tools_page, "辅助工具", "工具"),
            (self.settings_page, "设置", "设置"),
        )
        if self.updates_enabled:
            navigation += ((self.program_page, "程序更新", "更新"),)
        for page, name, short in navigation:
            key = str(page)
            self.page_info[key] = name
            button = NavButton(self.nav_frame, name, short, lambda page=page: self.pages.select(page), self.font_family)
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
                if widget in (self.location_bar, self.footer):
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
            allowed.add(str(self.config_page))
        if self.engineer_mode:
            allowed.update(self.nav_buttons)
        for key, button in self.nav_buttons.items():
            if key in allowed:
                button.pack(fill="x", pady=2)
                self.pages.tab(key, state="normal")
            else:
                button.pack_forget()
                self.pages.hide(key)
        for widget in self.engineer_widgets + [self.location_bar, self.footer]:
            self.set_engineer_widget(widget, self.engineer_mode)
        if self.engineer_mode and self.program_view.program_notes_open:
            self.program_view.program_notes_label.grid()
        else:
            self.program_view.program_notes_label.grid_remove()
        self.log_button.grid() if self.engineer_mode else self.log_button.grid_remove()
        if not self.engineer_mode:
            self.set_log_visible(False)
            self.status_label.grid_remove()
        self.config_view.layout_config_role()
        self.files_view.diff_tree.configure(displaycolumns=("status", "path", "incremental", "strict", "permissions")
                                 if self.engineer_mode else ("status", "path"))
        self.config_view.config_tree.configure(displaycolumns=("version", "status", "issues") if self.engineer_mode else ("version",))
        if self.pages.select() not in allowed:
            self.pages.select(self.config_page if self.program_checked else self.program_page)
        self.sync_navigation()

    def toggle_engineer(self, event=None):
        """Ctrl+Shift+F12：在用户界面与工程师维护界面之间切换。"""
        if self.busy:
            return "break"
        self.engineer_mode = not self.engineer_mode
        self.config_view.config_generation += 1
        self.config_view.clear_config_view()
        self.config_view.config_preview = None
        self.config_view.config_tree.delete(*self.config_view.config_tree.get_children())
        self.config_view.config_mapping.delete(*self.config_view.config_mapping.get_children())
        self.task_mode.set("配置版本：读取中")
        self.configure_access()
        self.pages.select(self.settings_page if self.engineer_mode else
                          self.config_page if self.program_checked else self.program_page)
        self.status.set("已进入工程师面板。" if self.engineer_mode else "已返回用户界面。")
        return "break"

    def draw_brand(self):
        self.brand.delete("all")
        compact = self.sidebar_compact
        x = self.brand.winfo_width() / 2 if compact else 22
        self.brand.create_text(x, 38, text="swicher", anchor="center" if compact else "w",
                               fill=COLORS["sidebar_text"], font=(self.font_family, 10 if compact else 17, "bold"))

    def sync_navigation(self):
        key = self.pages.select()
        if key in self.page_info:
            self.page_title.set(self.page_info[key])
        for page, button in self.nav_buttons.items():
            button.set_selected(page == key)
        self.config_header_refresh.grid_remove()
        if key == str(self.config_page) and not self.engineer_mode:
            self.config_header_refresh.grid(row=0, column=2, padx=(6, 0))
        if self.updates_enabled:
            if key == str(self.program_page):
                self.quick_update_button.grid_remove()
            else:
                self.quick_update_button.grid(row=0, column=3, padx=(12, 0))

    def resize_shell(self, event):
        if event.widget is not self.root:
            return
        compact = event.width < 1100
        if compact != self.sidebar_compact:
            self.sidebar_compact = compact
            self.sidebar.configure(width=76 if compact else 206)
            if compact:
                self.sidebar_footer.pack_forget()
            else:
                self.sidebar_footer.pack(side="bottom", fill="x", padx=20, pady=20)
            for button in self.nav_buttons.values():
                button.set_compact(compact)
            self.header.configure(padding=(16, 4, 16, 2) if compact else (20, 12, 20, 8))
            self.heading_label.configure(style="CompactTitle.TLabel" if compact else "PageTitle.TLabel")
            self.location_bar.configure(padding=(16, 0, 16, 6) if compact else (20, 0, 20, 10))
            self.text.configure(height=2 if compact else 3)
            self.draw_brand()
            self.sync_navigation()
        self.config_view.config_table.compact(compact)
        if hasattr(self.program_view, "version_banner"):
            self.program_view.version_banner.compact(compact)

    def fit_content(self, event):
        if event.widget is not self.workspace:
            return
        width = max(300, event.width - 55)
        if getattr(self, "_last_content_width", None) == width:
            return
        self._last_content_width = width
        self.status_label.configure(wraplength=max(220, width - 205))
        self.files_view.summary_label.configure(wraplength=max(220, width - 210))
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
        visible = visible and (not self.updates_enabled or self.engineer_mode)
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
        self.files_view.tree.configure(selectmode="none")
        self.config_view.config_tree.configure(selectmode="none")
        self.assets_view.assets_tree.configure(selectmode="none")
        self.cancel_button.configure(state="normal" if cancellable else "disabled")
        self.cancel_button.configure(text="停止 Demo" if self.demo_page.running else "取消准备")
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
                    self.demo_page.append_demo(data)
                elif kind == "program_check":
                    self.program_view.program_check_finished(data)
                    continue
                elif kind == "startup_progress":
                    if self.startup_window:
                        self.startup_window.update(data)
                    continue
                elif kind == "quick_progress":
                    if self.quick_dialog and self.quick_dialog.exists():
                        self.quick_dialog.update(data)
                    if "received" not in data:
                        self.append(data["message"])
                        self.status.set(data["message"])
                    continue
                elif kind == "demo_progress":
                    self.demo_page.demo_progress_event(data)
                elif kind == "demo_state":
                    self.demo_page.handle_state(data)
                else:
                    self.busy = False
                    was_demo = self.demo_page.finish_run()
                    for control in self.controls:
                        control.configure(state="normal")
                    self.files_view.tree.configure(selectmode="browse")
                    self.config_view.config_tree.configure(selectmode="browse")
                    self.assets_view.assets_tree.configure(selectmode="browse")
                    self.cancel_button.configure(state="disabled")
                    self.cancel_button.configure(text="取消准备")
                    self.progress.stop()
                    if kind in ("error", "demo_preflight_error"):
                        if self.startup_window:
                            self.startup_window.finish(dict(success=False, error=data))
                            self.update_ready()
                            continue
                        was_quick = self.quick_dialog and self.quick_dialog.exists() and self.quick_dialog.running
                        self.last_error = True
                        self.checked = None
                        self.config_view.config_preview = None
                        self.assets_view.invalidate_assets()
                        self.update_summary.set("操作未完成，请重新检查后再更新。")
                        self.status.set(data)
                        self.append("操作未完成：" + data)
                        self.set_log_visible(True)
                        if was_quick:
                            self.quick_dialog.update(dict(message=data, cancellable=False))
                            self.quick_dialog.finish(dict(success=False, publish="请查看日志确认", program="未完成", error=data))
                        if was_demo:
                            self.demo_page.handle_failure(data, preflight=kind == "demo_preflight_error")
                        if not self.closing and not was_quick:
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
        if self.demo_page.running:
            self.demo_page.update_demo_clock()
        self.poll_id = self.root.after(100, self.poll)

    def on_destroy(self, event):
        if event.widget is self.root and getattr(self.program_view, "program_check_id", None):
            self.root.after_cancel(self.program_view.program_check_id)
            self.program_view.program_check_id = None
        if event.widget is self.root and self.demo_page.running:
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

    def connect(self, updated=False):
        target, repo, branch = self.target.get().strip(), self.repo.get().strip(), self.branch.get().strip()
        sync_permissions = self.sync_permissions.get()
        update_mode = self.update_mode.get()
        presets = json.loads(json.dumps(self.presets))
        quick_profile = self.quick_profile.get().strip()
        repositories = self.settings_view.repository_list()
        if not target:
            messagebox.showinfo("选择目录", "请先选择 publish 目录。")
            return
        def work():
            engine = Engine(target, extensions=self.file_extensions)
            if is_relative_to(CONFIG.resolve(), engine.target):
                raise SyncError("设置文件位置必须在 publish 外，请调整 XDG_CONFIG_HOME。")
            recovered = engine.startup_recover()
            save_settings(CONFIG, {"target": str(engine.target), "repo": repo, "branch": branch, "directory_profiles": presets,
                                 "repository_sources": repositories,
                                 "quick_update_profile": quick_profile,
                                 "update_mode": update_mode,
                                 "repository_default_version": REPOSITORY_DEFAULT_VERSION, "sync_permissions": sync_permissions,
                                 "file_extensions": list(self.file_extensions), "format_inventory": self.format_inventory})
            return engine, engine.profiles(), recovered
        def done(result):
            self.engine, profiles, recovered = result
            self.repository_sources = repositories
            self.program_view.refresh_update_channels()
            self.profiles = [{"manifest": p["manifest"], "source": Source(**p["source"])} for p in profiles]
            self.add_placeholders()
            self.show_profiles()
            if updated and self.updates_enabled and not self.engineer_mode:
                self.pages.select(self.config_page)
            self.update_current()
            self.status.set("已保存设置；" + ("已处理未完成事务。" if recovered else "可以刷新远端方案或导入本地 catalog。"))
        self.run(work, done)

    def add_placeholders(self):
        ids = {(p.get("manifest") or p["profile"])["id"] for p in self.profiles}
        for p in self.presets:
            if p["id"] not in ids:
                self.profiles.append({"preset_only": True, "profile": {"id": p["id"], "name": p["name"], "version": "待刷新"}})

    def show_profiles(self):
        self.files_view.invalidate_check()
        self.files_view.tree.delete(*self.files_view.tree.get_children())
        for i, item in enumerate(self.profiles):
            m = item.get("manifest") or item["profile"]
            self.files_view.tree.insert("", "end", iid=str(i), values=(m.get("name", m["id"]), m["version"],
                             "预设（请刷新）" if item.get("preset_only") else
                             "清单已缓存（资源需检查）" if "manifest" in item else "未缓存"))
        previous = self.assets_view.assets_combo.current()
        preferred = None
        if 0 <= previous < len(self.assets_view.assets_profiles):
            old = self.assets_view.assets_profiles[previous]
            preferred = (old.get("manifest") or old["profile"])["id"]
        self.assets_view.assets_profiles = self.profiles[:]
        values = []
        for index, item in enumerate(self.assets_view.assets_profiles, 1):
            profile = item.get("manifest") or item["profile"]
            values.append("{}. {} / {}{}".format(index, profile.get("name", profile["id"]), profile["version"], "（请先刷新）" if item.get("preset_only") else ""))
        self.assets_view.assets_combo.configure(values=values)
        if values:
            index = next((i for i, p in enumerate(self.assets_view.assets_profiles) if (p.get("manifest") or p["profile"])["id"] == preferred), 0)
            self.assets_view.assets_combo.current(index)
        else:
            self.assets_view.assets_combo.set("")

    def update_current(self):
        self.assets_view.invalidate_assets()
        self.demo_page.invalidate_demo_tasks()
        try:
            info = read_json(self.engine.current)
            text = f"当前方案：{info.get('name', info['id'])} / {info['version']}（上次成功应用记录）"
        except (OSError, ValueError, KeyError):
            text = "当前方案：未由本工具应用"
        self.current.set(text)
        self.task_mode.set("配置版本：读取中")
        if self.pages.select() == str(self.demo_page):
            self.demo_page.refresh_demo_tasks()
        else:
            self.config_view.refresh_config_choices()

    def publish_changed(self):
        self.config_view.config_generation += 1
        self.config_view.clear_config_view()
        self.files_view.invalidate_check()
        self.demo_page.invalidate_demo_tasks()
        self.config_view.config_preview = None
        self.config_view.config_tree.delete(*self.config_view.config_tree.get_children())
        self.config_view.config_mapping.delete(*self.config_view.config_mapping.get_children())
        self.task_mode.set("配置版本：未读取")
        self.update_ready()

    def page_changed(self, event):
        if self.updates_enabled:
            if not self.engineer_mode and (not self.program_checked or self.pages.select() in
                    (str(self.update_page), str(self.assets_page), str(self.demo_page), str(self.tools_page), str(self.settings_page))):
                self.configure_access()
                return
        self.sync_navigation()
        if self.pages.select() == str(self.config_page):
            self.config_view.refresh_config_choices()
        elif self.pages.select() == str(self.demo_page) and self.engine and Path(self.target.get()).expanduser().resolve() == self.engine.target:
            self.demo_page.refresh_demo_tasks()

    def refresh(self):
        if not self.ensure_engine():
            return
        repo, branch = self.repo.get().strip(), self.branch.get().strip()
        if not repo:
            messagebox.showinfo("仓库未填写", "可以先导入本地 catalog；创建仓库后再填写地址。")
            return
        repositories = self.settings_view.repository_list()
        def work():
            return discover_repositories(repositories, self.presets, self.log, self.cancel)
        def done(items):
            cached = [p for p in self.profiles if "manifest" in p]
            self.profiles = items + cached
            self.show_profiles()
            source = items[0]["source"]
            name = (source.owner + "/" + source.repo) if source.owner and source.repo else str(source.local)
            self.status.set("已选中可用仓库：{} / {}；尚未修改 publish。".format(name, (source.commit or "本地")[:12]))
        self.run(work, done)

    def update_ready(self):
        if hasattr(self.config_view, "config_table"):
            self.config_view.config_table.set_enabled(not self.busy)
            self.config_header_refresh.configure(state="disabled" if self.busy else "normal")
        if hasattr(self, "phase_badge"):
            self.phase_badge.set_phase("running" if self.demo_page.running else "busy" if self.busy else "error" if self.last_error else "idle")
        state = "normal" if self.checked is not None and not self.busy else "disabled"
        if hasattr(self.files_view, "apply_button"):
            self.files_view.apply_button.configure(state=state)
        if hasattr(self.files_view, "diagnose_button"):
            selected = hasattr(self.files_view, "diff_tree") and self.files_view.diff_tree.selection()
            self.files_view.diagnose_button.configure(state="normal" if self.checked and selected and not self.busy else "disabled")
        for button in getattr(self.files_view, "mode_buttons", []):
            button.configure(state=state)
        if hasattr(self.config_view, "config_apply_button"):
            valid = self.config_view.config_preview and self.config_view.config_preview.get("valid") and not self.busy
            self.config_view.config_apply_button.configure(state="normal" if valid else "disabled")
        if hasattr(self.config_view, "config_compare_button"):
            selection = self.config_view.config_mapping.selection()
            valid = self.config_view.config_preview and "snapshot" in self.config_view.config_preview and selection and selection[0] in self.config_view.config_preview["sources"]
            self.config_view.config_compare_button.configure(state="normal" if valid and not self.busy else "disabled")
        for button in getattr(self, "permission_preset_buttons", []):
            button.configure(state="normal" if sys.platform == "linux" and not self.busy else "disabled")
        self.demo_page.update_controls()
        if hasattr(self.assets_view, "assets_apply_button"):
            ready = self.assets_view.assets_checked and not self.busy
            valid = ready and self.assets_view.assets_checked["preview"]["changes"] and not self.assets_view.assets_checked["preview"]["blocker"]
            self.assets_view.assets_apply_button.configure(state="normal" if valid else "disabled")
            self.assets_view.assets_details_button.configure(state="normal" if ready and self.assets_view.assets_tree.selection() else "disabled")
            self.assets_view.assets_combo.configure(state="readonly" if not self.busy else "disabled")
        if self.updates_enabled:
            self.program_view.update_channel_controls()
            self.quick_update_button.configure(state="normal" if not self.program_checking and not self.busy else "disabled")
            self.program_view.program_check_button.configure(state="normal" if not self.program_checking and not self.busy else "disabled")
            self.program_view.program_apply_button.configure(state="normal" if self.program_view.program_release and not self.program_checking and not self.busy else "disabled")
            self.program_view.program_offline_button.configure(state="normal" if not self.program_checking and not self.busy else "disabled")
        show_status = self.engineer_mode and (self.last_error or (self.busy and not (self.quick_dialog and self.quick_dialog.running)))
        self.status_label.grid() if show_status else self.status_label.grid_remove()
        self.progress.grid() if self.busy and not (self.quick_dialog and self.quick_dialog.running) else self.progress.grid_remove()
        self.cancel_button.grid() if self.busy and getattr(self, "operation_cancellable", False) else self.cancel_button.grid_remove()

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
        self.files_view.invalidate_check()
        self.config_view.config_preview = None
        def done(result):
            self.config_view.config_tree.delete(*self.config_view.config_tree.get_children())
            self.config_view.config_mapping.delete(*self.config_view.config_mapping.get_children())
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
                             ("hunk", COLORS["accent"], "#eff6ff"), ("header", COLORS["muted"], COLORS["panel"]),
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

    def run_comparison_self_test(self):
        self.run(lambda: comparison_self_test(self.cancel), self.show_diagnostic)

    def restore(self):
        if not self.ensure_engine():
            return
        if messagebox.askyesno("恢复上次更新", "请先退出相关任务。\n按上次同步记录的格式范围恢复备份，其他格式保留。是否恢复？"):
            self.run(lambda: self.engine.restore(self.log), self.files_view.applied)

    def close(self):
        if self.quick_dialog and self.quick_dialog.exists() and self.quick_dialog.running:
            self.quick_dialog.close()
            return
        if self.busy:
            prompt = ("IoT Demo 正在运行。停止本次任务并在进程退出后关闭？" if self.demo_page.running else
                      "正在操作。取消准备并在操作安全结束后关闭？目录切换阶段将等待完成。"
                      if self.operation_cancellable else "权限预设正在处理，将等待授权或命令结束后关闭。是否等待并关闭？")
            if messagebox.askyesno("等待操作安全结束", prompt):
                self.closing = True
                self.cancel.set()
        else:
            self.root.destroy()

