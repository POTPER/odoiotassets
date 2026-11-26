"""工程师「设置」页。

publish 路径、仓库与分支、同步格式、权限策略、一键更新方案 ID、程序更新源等。
"""
import json
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from publish_switcher.common.paths import INSTALL_ROOT
from publish_switcher.common.compat import is_relative_to
from publish_switcher.common.errors import SyncError
from publish_switcher.repositories.source import Source
from publish_switcher.common.files import read_json
from publish_switcher.common.settings import save_settings
from publish_switcher.sync.manifests import validate_catalog
from publish_switcher.repositories.catalog import DEFAULT_PROFILES, validate_presets, REPOSITORY_DEFAULT_VERSION
from publish_switcher.repositories.discovery import candidates as repository_candidates
from publish_switcher.gui.widgets.style import style_dialog
from publish_switcher.version import VERSION


class SettingsPage:
    def __init__(self, application):
        self.application = application

    def build_settings_page(self):
        page = self.application.settings_page
        ttk.Label(page, text="设置完成后，用户点击“更新”即可自动更新；下方为工程师维护设置。",
                  wraplength=800).pack(anchor="w", pady=(0, 12))
        settings = ttk.LabelFrame(page, text="连接设置", padding=12)
        settings.pack(fill="x")
        settings.columnconfigure(1, weight=1)
        for row, (label, variable) in enumerate((("publish 目录", self.application.target), ("资源仓库", self.application.repo), ("分支", self.application.branch))):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky="w", pady=8)
            entry = ttk.Entry(settings, textvariable=variable)
            entry.grid(row=row, column=1, sticky="ew", padx=10)
            self.application.controls.append(entry)
        self.application.button(settings, "浏览目录", self.application.browse, row=0, column=2)
        self.application.button(settings, "多仓库顺序 / 检测…", self.edit_repositories).grid(row=1, column=2, padx=4)
        ttk.Label(settings, text="支持 Gitee / GitHub / GitLab / 极狐；按设置顺序查询，分支可分别指定。",
                  wraplength=700).grid(row=3, column=1, sticky="w", padx=10, pady=6)
        ttk.Label(settings, text="一键更新方案 ID").grid(row=4, column=0, sticky="w", pady=6)
        quick_profile = ttk.Entry(settings, textvariable=self.application.quick_profile, width=16)
        quick_profile.grid(row=4, column=1, sticky="w", padx=10)
        self.application.controls.append(quick_profile)
        ttk.Label(settings, text="默认 rk；一键更新固定严格模式，沿用已选格式与权限设置。",
                  wraplength=700).grid(row=5, column=1, sticky="w", padx=10)
        actions = ttk.Frame(page)
        actions.pack(fill="x", pady=12)
        self.application.button(actions, "保存设置 / 读取缓存", self.application.connect).pack(side="left")
        self.application.button(actions, "方案目录设置（Jetson / RK 等）", self.edit_presets).pack(side="left", padx=8)
        if self.application.updates_enabled:
            ttk.Button(actions, text="返回用户界面", command=self.application.toggle_engineer).pack(side="left")
        if self.application.updates_enabled:
            program = ttk.LabelFrame(page, text="swicher 程序更新源", padding=8)
            program.pack(fill="x")
            program.columnconfigure(0, weight=1)
            self.application.controls.append(ttk.Entry(program, textvariable=self.application.program_source))
            self.application.controls[-1].grid(row=0, column=0, sticky="ew")
            self.application.button(program, "保存更新源", self.application.program_view.save_program_source).grid(row=0, column=1, padx=(6, 0))
        ttk.Label(page, text="清单缓存保存方案的文件列表；实际资源文件经下载校验后单独缓存。\n是否支持离线更新，以所选方案需要的文件是否已完整缓存为准。",
                  wraplength=800).pack(anchor="w", pady=8)
        about = ttk.LabelFrame(page, text="关于工具", padding=12)
        about.pack(fill="x", pady=(6, 0))
        about.columnconfigure(1, weight=1)
        ttk.Label(about, text="版本").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(about, text=VERSION).grid(row=0, column=1, sticky="w")
        ttk.Label(about, text="运行目录").grid(row=1, column=0, sticky="w", pady=(6, 0))
        location = ttk.Entry(about)
        location.insert(0, str(INSTALL_ROOT))
        location.configure(state="readonly")
        location.grid(row=1, column=1, sticky="ew", pady=(6, 0))


    def edit_presets(self):
        dialog = tk.Toplevel(self.application.root)
        style_dialog(dialog)
        dialog.title("方案设置：名称、仓库目录及新增方案")
        dialog.geometry("740x540")
        dialog.transient(self.application.root)
        dialog.grab_set()
        ttk.Label(dialog, text="修改 JSON 数组即可添加或重命名方案。directory 是仓库内目录；刷新时也会发现新的 publish_* 目录。\nexecutables 设置实际同步文件的仓库权限；allow_empty 用于确实允许为空的文件。未勾选格式只提示。",
                  wraplength=710).pack(fill="x", padx=12, pady=10)
        editor = tk.Text(dialog, wrap="none")
        editor.pack(fill="both", expand=True, padx=12)
        editor.insert("1.0", json.dumps(self.application.presets, ensure_ascii=False, indent=2))
        actions = ttk.Frame(dialog)
        actions.pack(fill="x", padx=12, pady=10)
        def defaults():
            editor.delete("1.0", "end")
            editor.insert("1.0", json.dumps(DEFAULT_PROFILES, ensure_ascii=False, indent=2))
        def save():
            try:
                presets = validate_presets(json.loads(editor.get("1.0", "end")))
                target = self.application.target.get().strip()
                if target and is_relative_to(self.application.settings_file.resolve(), Path(target).expanduser().resolve()):
                    raise SyncError("设置文件位置必须在 publish 外。")
                save_settings(self.application.settings_file, {"target": target, "repo": self.application.repo.get().strip(), "branch": self.application.branch.get().strip(),
                                     "update_mode": self.application.update_mode.get(),
                                     "directory_profiles": presets, "repository_default_version": REPOSITORY_DEFAULT_VERSION,
                                     "sync_permissions": self.application.sync_permissions.get(), "file_extensions": list(self.application.file_extensions),
                                     "format_inventory": self.application.format_inventory})
            except (SyncError, ValueError, OSError) as exc:
                messagebox.showerror("设置未保存", str(exc), parent=dialog)
                return
            self.application.presets = presets
            self.application.profiles = [p for p in self.application.profiles if "manifest" in p]
            self.application.add_placeholders()
            self.application.show_profiles()
            self.application.status.set("方案设置已保存，请刷新远端方案；已有缓存方案仍可使用。")
            dialog.destroy()
        ttk.Button(actions, text="恢复默认方案", command=defaults).pack(side="left")
        ttk.Button(actions, text="保存", command=save).pack(side="right")
        ttk.Button(actions, text="取消", command=dialog.destroy).pack(side="right", padx=8)


    def repository_list(self):
        return repository_candidates({"repository_sources": self.application.repository_sources}, self.application.repo.get().strip(), self.application.branch.get().strip())


    def edit_repositories(self):
        if not self.application.busy:
            from publish_switcher.gui.widgets.repositories import show_editor
            show_editor(self.application, self.application.settings_file)


    def import_local(self):
        if not self.application.ensure_engine():
            return
        path = filedialog.askopenfilename(title="选择本地资源仓库的 catalog.json", filetypes=[("JSON", "*.json")])
        if not path:
            return
        self.application.run(lambda: (Source(local=Path(path).parent), validate_catalog(read_json(path))), self.receive_catalog)


    def receive_catalog(self, result):
        source, catalog = result
        # Keep older cached versions available for offline use.
        cached = [p for p in self.application.profiles if "manifest" in p]
        self.application.profiles = [{"source": source, "profile": p} for p in catalog["profiles"]] + cached
        self.application.show_profiles()
        self.application.status.set("方案列表已更新；尚未修改 publish。")
