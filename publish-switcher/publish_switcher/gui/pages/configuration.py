"""用户「配置切换」页。

列出可见且校验通过的配置版本，应用时整套替换三个根目录 JSON。
"""
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from publish_switcher.common.errors import SyncError
from publish_switcher.sync.diagnostics import format_diff
from publish_switcher.configuration.versions import format_comparison
from publish_switcher.gui.widgets.style import COLORS, style_dialog
from publish_switcher.gui.widgets.reference import InfoCard, ConfigTable


class ConfigurationPage:
    def __init__(self, application):
        self.application = application

    def build_config_page(self):
        page = self.application.config_page
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        actions = ttk.Frame(page)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.application.button(actions, "刷新", self.refresh_config_choices).pack(side="left")
        visibility = self.application.button(actions, "版本显示设置", self.edit_config_visibility)
        visibility.pack(side="right")
        self.application.engineer_widgets.append(visibility)
        ttk.Label(actions, textvariable=self.application.task_mode).pack(side="left", padx=12)
        versions = ttk.LabelFrame(page, text="配置版本", padding=6)
        versions.grid(row=2, column=0, sticky="nsew")
        self.config_tree = ttk.Treeview(versions, columns=("version", "status", "issues"), show="headings", height=5, selectmode="browse")
        for key, title, width in (("version", "版本名称", 200), ("status", "状态", 100), ("issues", "说明", 480)):
            self.config_tree.heading(key, text=title)
            self.config_tree.column(key, width=width, minwidth=80, stretch=key == "issues")
        self.application.scrollable_tree(versions, self.config_tree, horizontal=True)
        mapping = ttk.LabelFrame(page, text="文件映射", padding=6)
        mapping.grid(row=3, column=0, sticky="ew", pady=8)
        self.config_mapping = ttk.Treeview(mapping, columns=("source", "active", "action"), show="headings", height=3, selectmode="browse")
        self.config_mapping.tag_configure("same", foreground=COLORS["green"], background=COLORS["green_bg"])
        self.config_mapping.tag_configure("different", foreground=COLORS["red"], background=COLORS["red_bg"])
        for key, title, width in (("source", "源文件", 390), ("active", "生效文件", 290), ("action", "处理", 80)):
            self.config_mapping.heading(key, text=title)
            self.config_mapping.column(key, width=width, minwidth=70, stretch=key == "source")
        self.application.scrollable_tree(mapping, self.config_mapping, horizontal=True)
        self.application.engineer_widgets.append(mapping)
        bottom = ttk.Frame(page)
        bottom.grid(row=4, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.config_compare_button = self.application.button(bottom, "查看所选 JSON 差异", self.compare_config_selection)
        self.config_compare_button.grid(row=0, column=1, sticky="e", padx=(0, 8))
        self.application.engineer_widgets.append(self.config_compare_button)
        self.config_apply_button = self.application.button(bottom, "应用所选版本", self.apply_config)
        self.config_apply_button.configure(style="Primary.TButton")
        self.config_apply_button.grid(row=0, column=2, sticky="e")
        self.config_engineer_frames = (actions, versions, mapping, bottom)
        self.config_user_view = ttk.Frame(page)
        self.config_user_view.grid(row=1, column=0, rowspan=4, sticky="nsew")
        self.config_user_view.columnconfigure(0, weight=1)
        self.config_user_view.rowconfigure(1, weight=1)
        overview = ttk.Frame(self.config_user_view)
        overview.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        for col in range(3):
            overview.columnconfigure(col, weight=1, uniform="overview")
        self.config_count_card = InfoCard(overview, "配置数量", "—", self.application.font_family)
        self.config_current_card = InfoCard(overview, "当前配置", "未读取", self.application.font_family)
        self.config_read_card = InfoCard(overview, "读取状态", "未读取", self.application.font_family)
        for col, card in enumerate((self.config_count_card, self.config_current_card, self.config_read_card)):
            card.grid(row=0, column=col, sticky="ew", padx=(0, 12) if col < 2 else 0)
        self.config_table = ConfigTable(self.config_user_view, self.application.font_family, self.request_config_apply)
        self.config_table.grid(row=1, column=0, sticky="nsew")
        self.layout_config_role()


    def layout_config_role(self):
        for frame in self.config_engineer_frames:
            frame.grid() if self.application.engineer_mode else frame.grid_remove()
        self.config_user_view.grid_remove() if self.application.engineer_mode else self.config_user_view.grid()


    def clear_config_view(self, message="未读取"):
        self.config_table.clear(message)
        self.config_count_card.set("—")
        self.config_current_card.set("未读取")
        self.config_read_card.set(message, COLORS["muted"])


    def refresh_config_choices(self):
        if self.application.closing or self.application.busy or not self.application.engine or Path(self.application.target.get()).expanduser().resolve() != self.application.engine.target:
            return
        previous = self.config_tree.selection()
        selected = previous[0] if previous else None
        engine = self.application.engine
        user_only = not self.application.engineer_mode
        generation = self.config_generation
        self.layout_config_role()
        if user_only:
            self.clear_config_view("读取中")
            self.config_preview = None
            self.config_tree.delete(*self.config_tree.get_children())
            self.config_mapping.delete(*self.config_mapping.get_children())
            self.application.task_mode.set("配置版本：读取中")
        def done(result):
            if generation != self.config_generation or engine is not self.application.engine or user_only != (not self.application.engineer_mode) or str(engine.target) != str(Path(self.application.target.get()).expanduser().resolve()):
                self.application.root.after_idle(self.refresh_config_choices)
                return
            self.config_refreshing = True
            self.config_preview = None
            self.config_tree.delete(*self.config_tree.get_children())
            self.config_mapping.delete(*self.config_mapping.get_children())
            if "error" in result:
                self.clear_config_view("读取失败")
                self.config_read_card.set("读取失败", COLORS["red"])
                self.application.task_mode.set("配置版本：读取失败")
                self.application.status.set(result["error"])
                self.config_refreshing = False
                return
            versions, current = result["versions"], result["current_label"]
            self.config_count_card.set(str(result["count"]) + " 个")
            self.config_current_card.set(result["current_name"])
            self.config_read_card.set(result["read_label"], COLORS["green"] if result["read_state"] == "ready" else COLORS["amber"])
            if user_only:
                self.config_table.set_items(versions)
            for item in versions:
                label = item.get("display_name", item["version"]) if user_only else item["version"]
                self.config_tree.insert("", "end", iid=item["version"], values=(label, "可用" if item["valid"] else "不可用", "；".join(item["issues"])))
            if not user_only and selected and self.config_tree.exists(selected):
                self.config_tree.selection_set(selected)
            self.application.task_mode.set(current)
            self.application.status.set("请选择需要使用的配置版本。" if versions else "当前没有可用的用户配置，请联系实施人员。"
                            if user_only else "config 下没有版本文件夹。")
            def finished():
                self.config_refreshing = False
                if selected and not user_only:
                    self.preview_config_selection()
            self.application.root.after_idle(finished)
        def work():
            try:
                return engine.config_summary(user_only=user_only)
            except Exception as exc:
                self.application.logger.exception("配置概览读取失败")
                return {"error": str(exc)}
        self.application.run(work, done)


    def request_config_apply(self, name):
        if self.application.busy or not self.application.ensure_engine():
            return
        engine, generation = self.application.engine, self.config_generation
        def checked(preview):
            if generation != self.config_generation or engine is not self.application.engine or self.application.engineer_mode:
                return
            if not preview["valid"]:
                messagebox.showerror("版本不可用", "\n".join(preview["issues"]), parent=self.application.root)
                return
            if all(row.get("action") == "相同" for row in preview["mappings"]):
                self.refresh_config_choices()
                return
            title = preview.get("display_name", name)
            if not messagebox.askyesno("切换配置", "切换为“{}”？\n请先退出主程序。".format(title), parent=self.application.root):
                return
            if generation != self.config_generation or engine is not self.application.engine or self.application.engineer_mode:
                return
            def applied(result):
                self.config_preview = None
                self.application.files_view.invalidate_check()
                self.application.update_current()
            self.application.run(lambda: engine.activate_config_version(name, expected_snapshot=preview["snapshot"],
                     log=self.application.logger.info, user_only=True), applied, cancellable=False)
        self.application.run(lambda: engine.preview_config_version(name, user_only=True), checked)


    def edit_config_visibility(self):
        if self.application.busy or not self.application.engineer_mode or not self.application.ensure_engine():
            return
        from publish_switcher.gui.widgets.config_visibility import show_visibility_editor
        try:
            show_visibility_editor(self.application.root, self.application.engine, self.refresh_config_choices)
        except (SyncError, OSError) as exc:
            messagebox.showerror("无法打开版本显示设置", str(exc))


    def preview_config_selection(self):
        self.config_preview = None
        self.config_mapping.delete(*self.config_mapping.get_children())
        self.application.update_ready()
        if self.application.busy or self.config_refreshing:
            return
        selection = self.config_tree.selection()
        if not selection or not self.application.engine:
            return
        name = selection[0]
        user_only = not self.application.engineer_mode
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
            self.application.status.set("版本有效，确认后将一次替换三个生效 JSON。" if result["valid"] else "不可应用：" + "；".join(result["issues"]))
            self.application.update_ready()
        self.application.run(lambda: self.application.engine.preview_config_version(name, user_only=user_only), done)


    def compare_config_selection(self):
        if self.application.busy or not self.config_preview or not self.config_mapping.selection() or not self.application.ensure_engine():
            return
        preview = self.config_preview
        name = self.config_mapping.selection()[0]
        if name not in preview["sources"] or "snapshot" not in preview:
            return
        engine = self.application.engine
        self.application.run(lambda: engine.compare_config_file(preview["version"], name, preview["snapshot"], self.application.cancel), self.show_config_comparison)


    def show_config_comparison(self, report):
        summary = format_comparison(report, include_diff=False)
        self.application.logger.info("配置 JSON 对比\n%s", summary)
        self.application.append("\n" + summary)
        window = tk.Toplevel(self.application.root)
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
            formatted, window.json_diff_text = self.application.add_diff_page(pages, "JSON 内容差异（格式化）", report["json_diff"], report["json_note"])
        raw, window.raw_diff_text = self.application.add_diff_page(pages, "原始文本差异", report["raw_diff"])
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
        self.application.status.set("JSON 对比完成：{}；只读查看，未应用配置。".format(report["status"]))


    def apply_config(self):
        if not self.application.ensure_engine() or not self.config_preview:
            return
        preview = self.config_preview
        user_only = not self.application.engineer_mode
        if not preview["valid"]:
            messagebox.showerror("版本不可用", "\n".join(preview["issues"]))
            return
        mapping = "\n".join(row["source"] + " → " + row["active"] for row in preview["mappings"])
        label = preview.get("display_name", preview["version"]) if user_only else preview["version"]
        detail = "" if user_only else "\n" + mapping
        if not messagebox.askyesno("应用整套配置", "版本：" + label + detail + "\n\n将应用此配置。请先退出主程序，是否应用？"):
            return
        def done(result):
            self.application.files_view.invalidate_check()
            self.config_preview = None
            self.application.update_current()
            if user_only:
                self.application.status.set("配置已应用：" + label)
            else:
                self.application.log("整套配置已应用：" + result["version"] + "；备份：" + result["backup"])
        self.application.run(lambda: self.application.engine.activate_config_version(preview["version"], expected_snapshot=preview["snapshot"],
                 log=self.application.logger.info if user_only else self.application.log, user_only=user_only), done)
