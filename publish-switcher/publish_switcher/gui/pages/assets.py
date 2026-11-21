"""工程师「Assets 资源」页。

比较本地 Assets 与仓库差异，仅下载缺失资源，不覆盖已有同名文件。
"""
from tkinter import messagebox, ttk
from publish_switcher.sync.engine import Engine
from publish_switcher.sync.assets import (
    AssetsEngine,
    format_preview as assets_report,
    format_details as assets_details,
)
from publish_switcher.gui.widgets.style import COLORS


class AssetsPage:
    def __init__(self, application):
        self.application = application

    def build_assets_page(self):
        page = self.application.assets_page
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
        self.application.controls.append(self.assets_combo)
        self.application.button(choices, "刷新远端方案", self.application.refresh, row=0, column=2)
        self.application.button(choices, "导入本地方案", self.application.settings_view.import_local, row=0, column=3)
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
        self.application.scrollable_tree(table, self.assets_tree, horizontal=True)
        actions = ttk.Frame(page)
        actions.grid(row=3, column=0, sticky="ew", pady=8)
        self.assets_check_button = self.application.button(actions, "1. 检查资源差异", self.preview_assets)
        self.assets_check_button.pack(side="left")
        self.assets_details_button = self.application.button(actions, "查看资源校验信息", self.show_assets_details)
        self.assets_details_button.pack(side="left", padx=8)
        self.assets_apply_button = self.application.button(actions, "2. 下载缺失资源", self.download_assets)
        self.assets_apply_button.configure(style="Primary.TButton")
        self.assets_apply_button.pack(side="right")
        ttk.Label(page, textvariable=self.assets_summary, wraplength=820).grid(row=4, column=0, sticky="w")
        ttk.Label(page, text="大文件下载完成后校验；失败或取消不应用部分资源。此页只补缺失，不受文件格式勾选影响。",
                  wraplength=820).grid(row=5, column=0, sticky="w", pady=(5, 0))


    def invalidate_assets(self):
        self.assets_checked = None
        if hasattr(self, "assets_tree"):
            self.assets_tree.delete(*self.assets_tree.get_children())
        self.assets_summary.set("请检查资源差异；只补缺失文件，已有资源保留。")
        self.application.update_ready()


    def assets_choice(self):
        if not self.application.ensure_engine():
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
        if self.application.busy:
            return
        item = self.assets_choice()
        if item is None:
            return
        target = self.application.engine.target
        self.invalidate_assets()
        def work():
            manifest = self.application.files_view.get_manifest(item)
            engine = AssetsEngine(target)
            Engine(target).startup_recover()
            with engine.lock():
                engine.recover()
                engine.save_profile(manifest, item["source"])
                return manifest, engine.preview_assets(manifest, self.application.cancel, self.application.log)
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
            self.application.append(assets_report(manifest, preview))
            if preview["blocker"]:
                self.application.set_log_visible(True)
            self.application.status.set("Assets 比较完成，尚未修改 publish。")
        self.application.run(work, done)


    def show_assets_details(self):
        if self.application.busy or not self.assets_checked or not self.assets_tree.selection():
            return
        checked = self.assets_checked
        path = self.assets_tree.selection()[0]
        row = next(row for row in checked["preview"]["comparison"] if row["path"] == path)
        self.application.show_diagnostic(assets_details(AssetsEngine(checked["target"]), checked["manifest"], checked["item"]["source"], row))


    def download_assets(self):
        if self.application.busy or not self.assets_checked:
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
        self.application.files_view.invalidate_check()
        def done(result):
            self.application.config_view.config_preview = None
            self.invalidate_assets()
            self.application.demo_page.invalidate_demo_tasks()
            self.application.status.set("Assets 资源下载完成，已有资源保持原样。")
            self.assets_summary.set("Assets 下载完成；重新检查可确认缺失文件已补齐。")
            self.application.append("Assets 备份：" + str(self.application.engine.state / "backups" / result["backup"]) if result.get("backup") else "Assets 无需下载。")
        self.application.run(lambda: AssetsEngine(checked["target"]).download_missing(checked["manifest"], item["source"],
                      expected_actual=preview["actual"], cancel=self.application.cancel, log=self.application.log), done)
