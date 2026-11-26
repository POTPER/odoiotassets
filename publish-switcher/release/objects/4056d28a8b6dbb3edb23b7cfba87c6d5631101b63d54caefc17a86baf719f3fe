"""工程师「IoT Demo」页。

按当前配置列出任务卡片，单选或顺序运行，实时显示状态、耗时与日志。
"""
import os
import shutil
import time
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from publish_switcher.gui.widgets.demo_cards import DemoGrid, PHASES, format_duration
from publish_switcher.demo.runner import DemoError, DemoQueueControl, describe, load_tasks, run_many, run_selected, task_name
from publish_switcher.gui.widgets.style import COLORS


DEMO_RESULTS_EMPTY = "暂无运行记录"


class DemoPage(ttk.Frame):
    def __init__(self, parent, application, log_directory):
        super().__init__(parent, padding=8)
        self.application = application
        self.log_directory = log_directory
        self.demo_tasks = {}
        self.running = False
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
        self.demo_log_title = tk.StringVar(value="运行日志")
        self.demo_progress_text = tk.StringVar(value="未运行")
        self.demo_elapsed_text = tk.StringVar(value="总用时 00:00")
        self.demo_status = tk.StringVar(value="选择模块运行")
        self.demo_log_path = tk.StringVar(value="尚无日志")

    def build(self):
        page = self
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)
        actions = ttk.Frame(page)
        actions.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.demo_run_button = self.application.button(actions, "运行当前", self.start_demo)
        self.demo_run_button.pack(side="left", padx=(0, 6))
        self.demo_checked_button = self.application.button(actions, "运行勾选", self.start_checked_demos)
        self.demo_checked_button.configure(style="Primary.TButton")
        self.demo_checked_button.pack(side="left", padx=(0, 6))
        self.demo_all_button = self.application.button(actions, "全部运行", self.start_all_demos)
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
        refresh = self.application.button(task_tools, "刷新", self.refresh_demo_tasks)
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
        self.demo_grid = DemoGrid(tasks, self.application.font_family, self.start_demo)
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
        self.demo_grid.bind("<<DemoSelect>>", self.demo_selection_changed)
        self.demo_grid.bind("<<DemoCheck>>", lambda event: self.update_controls())

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
        self.application.scrollable_tree(table, self.demo_results, horizontal=True)
        self.demo_results.bind("<<TreeviewSelect>>", lambda event: self.demo_result_selected())
        self.demo_results.bind("<Double-1>", self.show_demo_result_log)
        self.demo_results.bind("<Return>", self.show_demo_result_log)
        self.demo_detail_frame = ttk.Frame(results)
        self.demo_detail_frame.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        self.demo_detail_frame.columnconfigure(0, weight=1)
        self.demo_result_detail = tk.Text(self.demo_detail_frame, wrap="word", height=4, width=16,
                                          padx=7, pady=4, state="disabled")
        self.demo_result_detail.grid(row=0, column=0, sticky="ew")
        self.demo_result_detail.tag_configure("module", font=(self.application.font_family, 9, "bold"))
        detail_scroll = ttk.Scrollbar(self.demo_detail_frame, command=self.demo_result_detail.yview)
        detail_scroll.grid(row=0, column=1, sticky="ns")
        self.demo_result_detail.configure(yscrollcommand=detail_scroll.set)
        self.demo_detail_frame.grid_remove()

    def update_controls(self):
        selection = self.demo_grid.selected
        valid = selection and self.demo_tasks.get(selection, {}).get("valid")
        has_valid = any(item["valid"] for item in self.demo_tasks.values())
        checked = len(self.demo_grid.checked_keys())
        can_run = not self.application.busy and not self.demo_needs_refresh
        self.demo_run_button.configure(state="normal" if valid and can_run else "disabled")
        self.demo_all_button.configure(state="normal" if can_run and has_valid else "disabled")
        self.demo_checked_button.configure(text="运行勾选 ({})".format(checked) if checked else "运行勾选",
                                           state="normal" if checked and can_run else "disabled")
        self.demo_select_all_button.configure(state="normal" if has_valid and not self.application.busy else "disabled")
        self.demo_clear_button.configure(state="normal" if checked and not self.application.busy else "disabled")
        self.demo_grid.enabled = not self.application.busy or self.running
        self.demo_grid.enable_checking(not self.application.busy)
        self.demo_stop_button.configure(state="normal" if self.running else "disabled")
        self.update_demo_controls()
        self.update_demo_result_controls()

    def handle_state(self, data):
        self.demo_grid.update_state(data)
        if data["phase"] == "running" and data["task_id"] != getattr(self, "demo_follow_id", None):
            self.demo_follow_id = data["task_id"]
            if self.demo_log_mode.get() == "全部日志" or self.demo_log_at_end():
                self.demo_grid.reveal(data["task_id"])
        self.demo_live_summary()
        self.update_demo_controls()

    def handle_failure(self, data, preflight):
        self.demo_needs_refresh = preflight
        self.finish_demo_cards("failed", error=data)
        self.demo_status.set("Demo 未能完成：" + data)
        self.append_demo("Demo 未能完成：" + data)

    def finish_run(self):
        was_running = self.running
        self.running = False
        return was_running

    def invalidate_demo_tasks(self):
        self.demo_tasks = {}
        self.demo_grid.clear()
        self.demo_grid.empty.configure(text="选择 publish 目录后，点击“刷新”读取模块。")
        self.reset_demo_run()
        self.demo_count.configure(text="尚未读取模块")
        self.demo_status.set("目录或配置已变化，请刷新任务列表；运行前会重新读取当前配置。")
        self.application.update_ready()

    def refresh_demo_tasks(self):
        if self.application.busy or self.application.closing or not self.application.ensure_engine():
            return
        engine = self.application.engine
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
                    self.application.status.set("模块列表已刷新。")
                return
            self.demo_tasks = tasks
            self.demo_grid.set_tasks(cards)
            self.reset_demo_run()
            if not rows:
                self.demo_count.configure(text="读取失败" if read_error else "没有 IoT 模块")
                self.demo_grid.empty.configure(text=read_error or "当前任务配置没有 IoT 模块。请在“配置切换”选择包含 IoT 模块的版本，或检查 TrainTaskInfo.json。")
                self.demo_status.set("检查任务配置后点击“刷新”。")
                self.application.status.set("模块读取失败。" if read_error else "已读取任务配置。")
                return
            valid = sum(item["valid"] for item in self.demo_tasks.values())
            self.demo_count.configure(text="{} / {} 可运行".format(valid, len(rows)))
            self.demo_status.set("点击卡片查看脚本。勾选模块后，可按顺序运行勾选项。" if valid else
                                 "当前模块均不可运行。请查看卡片上的原因，处理后点击“刷新”。")
            self.application.status.set("模块列表已刷新。")
        self.application.run(work, done)

    def demo_selection_changed(self, event=None):
        self.update_controls()
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
        if self.running and self.demo_log_mode.get() == "当前模块日志" and self.demo_current_id:
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
            self.application.status.set("当前没有可复制的日志。")
            return
        self.application.root.clipboard_clear()
        self.application.root.clipboard_append(output)
        self.application.status.set("已复制当前显示的日志；完整日志可通过“导出”保存。")

    def export_demo_logs(self):
        path = self.demo_module_logs.get(self.demo_grid.selected) if self.demo_log_mode.get() == "当前模块日志" else self.demo_all_log
        if path is None or not path.is_file():
            messagebox.showinfo("暂无日志", "当前范围尚无本次运行日志文件。")
            return
        destination = filedialog.asksaveasfilename(parent=self.application.root, title="导出完整日志", initialfile=path.name,
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
        self.application.status.set("已导出完整日志" + ("（截至当前时刻）" if self.running else "") + "：" + destination)

    def start_demo(self):
        if self.application.busy or self.demo_needs_refresh or not self.application.ensure_engine() or not self.demo_grid.selected:
            return
        key = self.demo_grid.selected
        item = self.demo_tasks.get(key)
        if not item or not item["valid"]:
            return
        engine = self.application.engine
        if not messagebox.askyesno("运行 IoT Demo", "任务：{} / {}\n脚本：{}\n\n将执行当前配置中的原脚本，并可能操作硬件、写入结果文件。\n请先退出主程序和其他硬件任务，是否运行？".format(
                key, task_name(item["task"]), item["task"]["PythonScriptPath"])):
            return
        self.begin_demo([key])
        def done(code):
            self.complete_demo(code)
        self.application.run(lambda: run_selected(engine.target, key, self.log_directory(), cancel=self.application.cancel,
                                      output=lambda line: None,
                                      log_event=lambda event: self.application.events.put(("demo_log", event)),
                                      progress=lambda event: self.application.events.put(("demo_progress", event)),
                                      state=lambda event: self.application.events.put(("demo_state", event))), done)

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
        if self.application.busy or self.demo_needs_refresh or not self.application.ensure_engine():
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
        engine = self.application.engine
        snapshot = [item["task"] for item in self.demo_tasks.values()]
        self.begin_demo(keys)
        self.demo_control = DemoQueueControl()
        self.application.run(lambda: run_many(engine.target, keys, self.log_directory(), cancel=self.application.cancel,
                                 output=lambda line: None, control=self.demo_control,
                                 log_event=lambda event: self.application.events.put(("demo_log", event)),
                                 progress=lambda event: self.application.events.put(("demo_progress", event)),
                                 state=lambda event: self.application.events.put(("demo_state", event)), expected_tasks=snapshot), self.complete_demo)

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
        self.application.files_view.invalidate_check()
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
        self.running = True

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
        elif self.demo_timings or not self.running:
            self.demo_progress_text.set("{} · 已处理 {} / {} 个模块".format("正在准备下一个" if self.running else "队列已结束", completed, len(self.demo_order)))

    def update_demo_controls(self):
        can_skip = (self.running and not self.application.cancel.is_set() and self.demo_control is not None and
                    self.demo_control.can_skip(self.demo_current_id))
        self.demo_skip_button.configure(state="normal" if can_skip else "disabled")

    def skip_demo(self):
        if (self.running and not self.application.cancel.is_set() and self.demo_control is not None and
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
            state="normal" if not self.application.busy and selected and selected[0] in self.demo_module_logs else "disabled")
        self.demo_retry_button.configure(
            state="normal" if not self.application.busy and self.demo_finished_at is not None and self.demo_retry_keys() else "disabled")

    def show_demo_result_log(self, event=None):
        if self.application.busy:
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
        stopped = "stopped" in phases or (code == 130 and self.application.cancel.is_set() and "failed" not in phases)
        self.finish_demo_cards("stopped" if stopped else "failed" if code else "completed")
        skipped = sum(t["phase"] == "skipped" for t in self.demo_timings.values())
        if stopped:
            text = "Demo 已停止。"
        elif code:
            text = "Demo 异常退出（{}），请查看右侧日志。".format(code)
        else:
            text = "Demo 队列结束，已跳过 {} 个模块。".format(skipped) if skipped else "Demo 正常结束。"
        self.demo_status.set(text)
        self.application.status.set(text)
        self.application.files_view.invalidate_check()

    def stop_demo(self):
        if self.running:
            self.application.cancel.set()
            self.update_demo_controls()
            self.demo_status.set("正在停止本次启动的 Demo，请等待进程退出…")
