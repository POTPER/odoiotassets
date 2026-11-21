"""工程师「更新文件」页。

刷新远端方案、预览差异、选择增量或严格更新，并管理同步格式勾选。
"""
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from publish_switcher.common.compat import is_relative_to
from publish_switcher.common.errors import SyncError
from publish_switcher.common.settings import save_settings
from publish_switcher.repositories.catalog import profile_manifest
from publish_switcher.sync.diagnostics import diagnose_file
from publish_switcher.gui.widgets.style import COLORS, style_dialog
from publish_switcher.sync.formats import (
    DEFAULT_EXTENSIONS,
    normalize_extensions,
    inventory,
    describe as describe_formats,
    label,
)


class FilesPage:
    def __init__(self, application):
        self.application = application

    def build_update_page(self):
        page = self.application.update_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(page)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.application.button(toolbar, "刷新远端方案", self.application.refresh).pack(side="left")
        self.application.button(toolbar, "导入本地方案", self.application.settings_view.import_local).pack(side="left", padx=6)
        maintenance = self.application.button(toolbar, "权限预设 / 恢复", lambda: self.application.pages.select(self.application.tools_page))
        maintenance.pack(side="right")
        self.formats_button = self.application.button(toolbar, "同步格式…", self.read_formats)
        self.formats_button.configure(textvariable=self.application.format_text)
        self.formats_button.pack(side="right", padx=8)
        self.application.engineer_widgets.extend((maintenance, self.formats_button))

        self.update_pane = ttk.Panedwindow(page, orient="vertical")
        self.update_pane.grid(row=1, column=0, sticky="nsew")
        schemes = ttk.LabelFrame(self.update_pane, text="1. 选择资源方案", padding=4)
        self.tree = ttk.Treeview(schemes, columns=("name", "version", "cached"), show="headings", height=2, selectmode="browse")
        for key, title, width in (("name", "方案名称", 160), ("version", "版本", 180), ("cached", "方案清单缓存", 360)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=100, stretch=True)
        self.application.scrollable_tree(schemes, self.tree)
        self.update_pane.add(schemes, weight=1)

        differences = ttk.LabelFrame(self.update_pane, text="2. 检查差异", padding=4)
        actions = ttk.Frame(differences)
        actions.pack(fill="x", pady=(0, 5))
        self.check_button = self.application.button(actions, "检查所选方案", self.preview)
        self.check_button.pack(side="left")
        self.diagnose_button = self.application.button(actions, "查看选中文件差异", self.diagnose_selected)
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
        self.application.scrollable_tree(holder, self.diff_tree, horizontal=True)
        self.update_pane.add(differences, weight=3)

        policy = ttk.LabelFrame(page, text="3. 选择方式并更新", padding=6)
        policy.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        policy.columnconfigure(0, weight=1)
        choices = ttk.Frame(policy)
        choices.grid(row=0, column=0, sticky="w")
        self.mode_buttons = []
        for value, text in (("incremental", "增量：只补缺失，保留已有和多余文件"),
                            ("strict", "严格：替换差异，删除所选格式的多余文件")):
            button = ttk.Radiobutton(choices, text=text, variable=self.application.update_mode, value=value, command=self.mode_changed)
            button.pack(side="left", padx=(0, 12))
            self.mode_buttons.append(button)
        self.permissions_button = ttk.Checkbutton(policy, text="严格更新同时同步仓库权限（默认保留本地权限）",
                                                 variable=self.application.sync_permissions, command=self.permissions_changed)
        self.permissions_button.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self.application.controls.append(self.permissions_button)
        self.application.engineer_widgets.extend((choices, self.permissions_button))
        policy_caption = ttk.Frame(policy)
        ttk.Label(policy_caption, text="3. 更新方式", style="Section.TLabel").pack(side="left")
        self.summary_label = ttk.Label(policy_caption, textvariable=self.application.update_summary, style="Muted.TLabel", wraplength=650)
        self.summary_label.pack(side="left", padx=(12, 0))
        policy.configure(labelwidget=policy_caption)
        self.apply_button = self.application.button(policy, "执行更新", self.apply)
        self.apply_button.configure(style="Primary.TButton")
        self.apply_button.grid(row=1, column=1, padx=(10, 0), sticky="e")


    def choice(self):
        if not self.application.ensure_engine():
            return None
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("选择方案", "请先选择一个方案。")
            return None
        item = self.application.profiles[int(selected[0])]
        if item.get("preset_only"):
            messagebox.showinfo("刷新方案", "这是初始预设，请先刷新远端方案。")
            return None
        return item


    def get_manifest(self, item):
        if "manifest" not in item:
            manifest = profile_manifest(item)
            with self.application.engine.lock():
                self.application.engine.save_profile(manifest, item["source"])
            item["manifest"] = manifest
        return item["manifest"]


    def record_formats(self, manifest):
        self.application.format_inventory = {"id": manifest["id"], "name": manifest.get("name", manifest["id"]),
                                 "version": manifest["version"], "repo": self.application.repo.get().strip(),
                                 "formats": inventory(manifest)}
        if self.application.settings_file.exists():
            self.save_formats()


    def save_formats(self):
        if self.application.target.get() and is_relative_to(self.application.settings_file.resolve(), Path(self.application.target.get()).expanduser().resolve()):
            raise SyncError("设置文件必须位于 publish 外。")
        save_settings(self.application.settings_file, {"file_extensions": list(self.application.file_extensions), "format_inventory": self.application.format_inventory})


    def read_formats(self):
        if self.application.busy:
            return
        item = self.choice()
        if item:
            self.application.run(lambda: self.get_manifest(item), self.show_formats)


    def show_formats(self, manifest):
        self.record_formats(manifest)
        dialog = tk.Toplevel(self.application.root)
        dialog.title("同步格式 · " + manifest.get("name", manifest["id"]))
        style_dialog(dialog)
        dialog.geometry("620x480")
        dialog.transient(self.application.root)
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
        for ext in sorted(set(rows) | set(self.application.file_extensions) | set(DEFAULT_EXTENSIONS)):
            row = rows.get(ext, {"count": 0, "bytes": 0, "unavailable": 0})
            variables[ext] = tk.BooleanVar(value=ext in self.application.file_extensions)
            text = "{}   {} 个文件 · {:.2f} MiB{}".format(label(ext), row["count"], row["bytes"] / 1024**2,
                    "（含仅元数据条目，发布方需补齐）" if row["unavailable"] else "")
            ttk.Checkbutton(content, text=text, variable=variables[ext]).pack(anchor="w", pady=5)
        def defaults():
            for ext, variable in variables.items():
                variable.set(ext in DEFAULT_EXTENSIONS)
        def save():
            try:
                selected = normalize_extensions([ext for ext, var in variables.items() if var.get()])
                old = self.application.file_extensions
                self.application.file_extensions = selected
                try:
                    self.save_formats()
                except Exception:
                    self.application.file_extensions = old
                    raise
                if self.application.engine:
                    self.application.engine.extensions = selected
                self.application.format_text.set("同步格式…（{} 种）".format(len(selected)))
                self.invalidate_check()
                self.application.status.set("格式选择已保存：" + describe_formats(selected) + "；请重新检查方案。")
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
        sync_permissions = self.application.sync_permissions.get()
        self.application.engine.extensions = self.application.file_extensions
        def work():
            m = self.get_manifest(item)
            with self.application.engine.lock():
                self.application.engine.recover()
                strict = self.application.engine.preview(m, self.application.cancel, mode="strict", sync_permissions=sync_permissions)
                incremental = self.application.engine.preview(m, self.application.cancel, mode="incremental", actual=strict["actual"], sync_permissions=sync_permissions)
            return m, {"strict": strict, "incremental": incremental}
        def done(result):
            m, plans = result
            self.record_formats(m)
            self.application.checked = {"item": item, "manifest": m, "plans": plans, "actual": plans["strict"]["actual"], "sync_permissions": sync_permissions}
            self.diff_tree.delete(*self.diff_tree.get_children())
            for row in plans["strict"]["comparison"]:
                tag = "same" if row["status"] in ("相同", "内容相同") else "permission" if row["status"] == "权限不同" else "different"
                self.diff_tree.insert("", "end", values=(row["status"], row["path"], row["incremental"], row["strict"], row.get("permissions", "—")), tags=(tag,))
            self.mode_changed()
            self.application.status.set("比较完成，请选择增量或严格更新，再点击执行更新。")
        self.application.run(work, done)


    def invalidate_check(self):
        self.application.checked = None
        self.application.assets_view.invalidate_assets()
        self.application.update_summary.set("尚未检查。请选择方案，再检查差异。")
        if hasattr(self, "diff_tree"):
            self.diff_tree.delete(*self.diff_tree.get_children())
        self.application.update_ready()


    def permissions_changed(self):
        self.invalidate_check()
        self.application.status.set("权限策略已改变，请重新检查差异；保存设置后下次沿用。")


    def diagnose_selected(self):
        if not self.application.checked or not self.diff_tree.selection() or self.application.busy:
            return
        checked = self.application.checked
        path = self.diff_tree.item(self.diff_tree.selection()[0], "values")[1]
        self.application.run(lambda: diagnose_file(self.application.engine, checked["manifest"], checked["item"]["source"], path, cancel=self.application.cancel,
                                      sync_permissions=checked["sync_permissions"]), self.application.show_diagnostic)


    def mode_changed(self):
        if self.application.checked:
            self.display_preview((self.application.checked["manifest"], self.application.checked["plans"][self.application.update_mode.get()]))
        self.application.update_ready()


    def display_preview(self, result):
        m, preview = result
        mode = "增量更新" if preview.get("mode") == "incremental" else "严格更新"
        self.application.update_summary.set("{} · 变更 {} 项 · 需下载 {:.2f} MiB{}".format(
            mode, len(preview["changes"]), preview["download_bytes"] / 1024**2,
            " · 当前方案无法应用，详见日志" if preview.get("blocker") else
            " · 其他资源提示 {} 项（见日志）".format(len(preview["notices"])) if preview.get("notices") else ""))
        if preview.get("blocker"):
            self.application.set_log_visible(True)
        self.application.append(f"\n方案：{m.get('name', m['id'])} / {m['version']}")
        if preview.get("blocker"):
            self.application.append("不能应用：" + preview["blocker"])
        self.application.append("更新方式：" + ("增量（只补齐缺失）" if preview.get("mode") == "incremental" else "严格（替换差异并删除本地多余文件）"))
        self.application.append("权限策略：" + ("严格更新同步仓库权限；增量跳过已有文件。" if preview["sync_permissions"] else "保留本地已有文件权限；新文件用仓库权限。"))
        self.application.append("同步格式：" + describe_formats(preview["extensions"]))
        self.application.append(f"变更 {len(preview['changes'])} 项；需下载 {preview['download_bytes'] / 1024**2:.2f} MiB")
        for action, path in preview["changes"]:
            self.application.append(f"{action}  {path}")
        self.application.append("其他文件不下载、不覆盖、不删除；只比较是否存在、类型和大小，不校验其内容。")
        for notice, path in preview.get("notices", []):
            self.application.append(f"{notice}  {path}")
        self.application.status.set("检查完成；尚未修改 publish。")


    def apply(self):
        item = self.choice()
        if not item:
            return
        if not self.application.checked or self.application.checked["item"] is not item:
            messagebox.showinfo("先检查差异", "请先检查当前方案，再选择更新方式。")
            return
        checked, mode = self.application.checked, self.application.update_mode.get()
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
        if not messagebox.askyesno("确认更新", f"目标：{self.application.engine.target}\n方案：{m.get('name', m['id'])}\n变更：{len(preview['changes'])} 项\n\n{detail}\n请先退出相关任务，是否执行？"):
            return
        self.application.run(lambda: self.application.engine.apply(m, item["source"], self.application.cancel, self.application.log, mode=mode, expected_actual=checked["actual"],
                                          sync_permissions=checked["sync_permissions"]), self.applied)


    def applied(self, result):
        self.application.logger.info("所选格式操作完成：%s", result)
        self.invalidate_check()
        self.application.update_current()
        if result.get("unchanged"):
            self.application.status.set("无需更新，未修改任何文件。")
            return
        self.application.status.set("同步完成。请重新启动主程序。")
        self.application.append("所选格式同步完成，其他文件保持原样。备份：" + str(self.application.engine.state / "backups" / result["backup"]))
