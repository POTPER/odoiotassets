"""Embedded results browser and file selection; never executes selected files."""
from datetime import datetime
from pathlib import Path, PurePosixPath
import queue
import logging
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from launcher_style import palette
from results_files import list_results, copy_submission


class ResultsPanel(tk.Frame):
    def __init__(self, master, source, settings, theme, family, on_home):
        super().__init__(master, padx=24, pady=20)
        self.family = family
        self.source = Path(source).expanduser().absolute()
        self.relative = ""
        self.selected = set()
        self.rows = {}
        self.signature = None
        self.submitting = False
        self.thread = None
        self.scan_thread = None
        self.cancel = threading.Event()
        self.events = queue.Queue()
        self.closed, self.visible, self.loading, self.pending = False, True, False, False
        self.generation = 0
        self.header = tk.Frame(self)
        self.header.pack(fill="x")
        self.title = tk.Label(self.header, text="成果文件", font=(family, 16, "bold"))
        self.title.pack(side="left")
        self.home_button = tk.Button(self.header, text="返回首页", command=on_home, relief="flat", padx=14, pady=6)
        self.home_button.pack(side="right")
        self.toolbar = tk.Frame(self)
        self.toolbar.pack(fill="x", pady=(16, 10))
        self.up_button = tk.Button(self.toolbar, text="上一级", command=self.up, relief="flat", padx=12)
        self.up_button.pack(side="left")
        self.refresh_button = tk.Button(self.toolbar, text="刷新", command=self.refresh, relief="flat", padx=12)
        self.refresh_button.pack(side="left", padx=8)
        self.location = tk.StringVar(master=self, value=self.source.name)
        self.breadcrumb = tk.Label(self.toolbar, textvariable=self.location, anchor="w", font=(family, 10))
        self.breadcrumb.pack(side="left", fill="x", expand=True)
        self.table_frame = tk.Frame(self)
        self.table_frame.pack(fill="both", expand=True)
        self.table = ttk.Treeview(self.table_frame, columns=("pick", "name", "kind", "size", "modified"),
                                  show="headings", selectmode="browse", style="Results.Treeview")
        for column, label, width in (("pick", "选择", 48), ("name", "文件名", 320), ("kind", "类型", 70),
                                     ("size", "大小", 80), ("modified", "修改时间", 150)):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=width if column != "name" else 120,
                              stretch=column == "name", anchor="w" if column in ("name", "modified") else "center")
        self.scroll = ttk.Scrollbar(self.table_frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.table.pack(side="left", fill="both", expand=True)
        self.table.bind("<Button-1>", self.click)
        self.table.bind("<Double-1>", self.activate)
        self.table.bind("<space>", self.space)
        self.footer = tk.Frame(self)
        self.footer.pack(fill="x", pady=(12, 0))
        self.status = tk.StringVar(master=self, value="正在读取…")
        self.status_label = tk.Label(self.footer, textvariable=self.status, anchor="w", font=(family, 10), width=30)
        self.status_label.pack(side="left", fill="x", expand=True)
        self.submit_button = tk.Button(self.footer, text="提交成果", command=self.submit, relief="flat", padx=16, pady=6)
        self.clear_button = tk.Button(self.footer, text="取消选择", command=self.clear, relief="flat", padx=12, pady=6)
        self.all_button = tk.Button(self.footer, text="全选文件", command=self.select_all, relief="flat", padx=12, pady=6)
        self.configure_submission(settings)
        self.apply_theme(theme)
        self.poll_id = self.after(50, self.poll)
        self.refresh_id = self.after(2000, self.auto_refresh)
        self.refresh()

    def configure_submission(self, settings):
        self.publish_dir = settings.get('publish_dir')
        self.enabled = settings.get("submission_enabled", False) is True
        self.destination = settings.get("submission_dir", "")
        if not self.enabled:
            self.selected.clear()
        self.table.configure(displaycolumns=("pick", "name", "kind", "size", "modified") if self.enabled else
                             ("name", "kind", "size", "modified"))
        for button in (self.submit_button, self.clear_button, self.all_button):
            button.pack_forget()
        if self.enabled:
            self.submit_button.pack(side="right")
            self.clear_button.pack(side="right", padx=8)
            self.all_button.pack(side="right")
        self.update_selection()

    def apply_theme(self, theme):
        colors = palette(theme)
        for frame in (self, self.header, self.toolbar, self.table_frame, self.footer):
            frame.configure(background=colors["bg"])
        for label in (self.title, self.breadcrumb, self.status_label):
            label.configure(background=colors["bg"], foreground=colors["text"])
        for button in (self.home_button, self.up_button, self.refresh_button, self.clear_button, self.all_button):
            button.configure(background=colors["selected"], foreground=colors["text"],
                             activebackground=colors["border"], activeforeground=colors["text"], disabledforeground=colors["muted"])
        self.submit_button.configure(background=colors["primary"], foreground=colors["primary_text"],
                                     activebackground=colors["primary"], activeforeground=colors["primary_text"],
                                     disabledforeground=colors["muted"])
        style = ttk.Style(self)
        style.configure("Results.Treeview", background=colors["sidebar"], fieldbackground=colors["sidebar"],
                        foreground=colors["text"], rowheight=30, borderwidth=0, font=(self.family, 10))
        style.map("Results.Treeview", background=[("selected", colors["selected"])], foreground=[("selected", colors["text"])])
        style.configure("Results.Treeview.Heading", background=colors["selected"], foreground=colors["text"],
                        relief="flat", font=(self.family, 10, "bold"))

    def reconfigure(self, source, settings):
        source = Path(source).expanduser().absolute()
        if source != self.source:
            self.source, self.relative = source, ""
            self.selected.clear()
            self.signature = None
            self.generation += 1
        self.configure_submission(settings)
        if self.visible:
            self.refresh()

    def refresh(self):
        if self.closed or self.submitting:
            return
        if self.loading:
            self.pending = True
            return
        self.loading = True
        source, relative, generation = self.source, self.relative, self.generation
        events = self.events
        def scan():
            try:
                result, error = list_results(source, relative), None
            except Exception as exc:
                result, error = [], str(exc)
            events.put(("listing", (generation, result, error)))
        self.scan_thread = threading.Thread(target=scan, daemon=True)
        self.scan_thread.start()

    def auto_refresh(self):
        if self.visible:
            self.refresh()
        self.refresh_id = self.after(2000, self.auto_refresh)

    def render_rows(self, rows):
        signature = [(row["relative"], row["kind"], row["size"], row["modified"]) for row in rows]
        if signature != self.signature:
            focus = self.table.focus()
            self.table.delete(*self.table.get_children())
            self.rows = {row["relative"]: row for row in rows}
            current = PurePosixPath(self.relative or ".")
            self.selected.difference_update(key for key in list(self.selected)
                                            if PurePosixPath(key).parent == current and
                                            self.rows.get(key, {}).get("kind") != "file")
            for key, row in self.rows.items():
                kind = {"directory": "文件夹", "file": "文件", "link": "链接", "other": "其他"}[row["kind"]]
                size = "" if row["kind"] != "file" else self.format_size(row["size"])
                self.table.insert("", "end", iid=key, values=("", row["name"], kind, size,
                                  datetime.fromtimestamp(row["modified"]).strftime("%Y-%m-%d %H:%M")))
            if self.table.exists(focus):
                self.table.focus(focus)
            self.signature = signature
        self.location.set(self.source.name + (" / " + self.relative if self.relative else ""))
        self.up_button.configure(state="normal" if self.relative and not self.submitting else "disabled")
        self.update_selection()

    @staticmethod
    def format_size(size):
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return "{:.0f} {}".format(size, unit) if unit == "B" else "{:.1f} {}".format(size, unit)
            size /= 1024

    def update_selection(self):
        for key, row in self.rows.items():
            self.table.set(key, "pick", ("☑" if key in self.selected else "☐") if row["kind"] == "file" else "")
        self.submit_button.configure(state="normal" if self.enabled and self.selected and not self.submitting else "disabled")
        if not self.submitting:
            self.status.set("已选 {} 个文件".format(len(self.selected)) if self.enabled else "共 {} 项".format(len(self.rows)))

    def toggle(self, key):
        if not self.enabled or self.submitting or self.rows.get(key, {}).get("kind") != "file":
            return
        self.selected.symmetric_difference_update({key})
        self.update_selection()

    def click(self, event):
        if self.enabled and self.table.identify_column(event.x) == "#1":
            self.toggle(self.table.identify_row(event.y))

    def activate(self, event):
        if self.submitting:
            return "break"
        key = self.table.identify_row(event.y)
        if self.rows.get(key, {}).get("kind") == "directory":
            self.navigate(key)
        elif not self.enabled or self.table.identify_column(event.x) != "#1":
            self.toggle(key)
        return "break"

    def space(self, event):
        self.toggle(self.table.focus())
        return "break"

    def navigate(self, relative):
        if self.submitting:
            return
        self.relative = relative
        self.generation += 1
        self.signature = None
        self.refresh()

    def up(self):
        parent = PurePosixPath(self.relative).parent.as_posix()
        self.navigate("" if parent == "." else parent)

    def clear(self):
        if not self.submitting:
            self.selected.clear()
            self.update_selection()

    def select_all(self):
        if self.enabled and not self.submitting:
            self.selected.update(key for key, row in self.rows.items() if row["kind"] == "file")
            self.update_selection()

    def submit(self):
        if not self.enabled or self.submitting or not self.selected:
            return
        self.submitting = True
        self.cancel.clear()
        files, source, target = sorted(self.selected), self.source, self.destination
        publish = self.publish_dir
        cancel, events = self.cancel, self.events
        for button in (self.submit_button, self.clear_button, self.all_button, self.up_button, self.refresh_button):
            button.configure(state="disabled")
        self.status.set("正在提交…")
        def copy():
            try:
                result = copy_submission(source, target, files, enabled=True, cancel=cancel,
                                         progress=lambda done, total: events.put(("progress", (done, total))),
                                         publish_dir=publish)
                events.put(("submitted", (result, None)))
            except Exception as exc:
                events.put(("submitted", (None, str(exc))))
        self.thread = threading.Thread(target=copy, daemon=False)
        self.thread.start()

    def poll(self):
        if self.closed:
            return
        try:
            self.poll_events()
        except Exception:
            logging.getLogger(__name__).exception('成果面板刷新失败，将继续处理后续状态。')
        finally:
            if not self.closed:
                self.poll_id = self.after(50, self.poll)

    def poll_events(self):
        try:
            while True:
                event, data = self.events.get_nowait()
                if event == "listing":
                    self.loading = False
                    generation, rows, error = data
                    if generation == self.generation and not self.submitting:
                        if error:
                            self.status.set("读取失败：" + error)
                        else:
                            self.render_rows(rows)
                    if self.pending:
                        self.pending = False
                        self.refresh()
                elif event == "progress":
                    self.status.set("正在提交 {}/{}…".format(*data))
                elif event == "submitted":
                    self.submitting = False
                    paths, error = data
                    if not error:
                        self.selected.clear()
                    for button in (self.clear_button, self.all_button, self.refresh_button):
                        button.configure(state="normal")
                    self.up_button.configure(state="normal" if self.relative else "disabled")
                    self.update_selection()
                    self.status.set("已提交 {} 个文件".format(len(paths)) if not error else "提交失败，请重试。")
                    if error:
                        messagebox.showerror("成果提交失败", error, parent=self.winfo_toplevel())
        except queue.Empty:
            pass

    def shutdown(self):
        self.cancel.set()

    def wait(self):
        if self.thread is not None:
            self.thread.join()
        if self.scan_thread is not None:
            self.scan_thread.join()

    def destroy(self):
        if self.closed:
            return
        self.closed = True
        self.shutdown()
        self.after_cancel(self.poll_id)
        self.after_cancel(self.refresh_id)
        super().destroy()
