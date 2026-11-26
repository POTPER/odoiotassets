"""参考风格界面部件。

深蓝侧栏、配置列表行与真实「应用」按钮，全部用标准 Tk 绘制。
"""
import tkinter as tk
from tkinter import ttk

from publish_switcher.gui.widgets.style import COLORS, rounded


class Surface(tk.Canvas):
    def __init__(self, parent, height=110, tone="#ffffff"):
        super().__init__(parent, height=height, width=1, highlightthickness=0, background=COLORS["bg"])
        self.tone = tone
        self.body = tk.Frame(self, background=tone)
        self.window = self.create_window(18, 16, window=self.body, anchor="nw")
        self.bind("<Configure>", self.draw)

    def draw(self, event):
        w, h = event.width, event.height
        self.delete("surface")
        rounded(self, 1, 1, w-2, h-2, radius=12, fill=self.tone, outline=COLORS["border"], tags="surface")
        self.itemconfigure(self.window, width=max(1, w-36), height=max(1, h-30))
        self.tag_lower("surface", self.window)


class InfoCard(Surface):
    def __init__(self, parent, title, value, family, tone="#ffffff"):
        super().__init__(parent, height=92, tone=tone)
        self.body.columnconfigure(0, weight=1)
        tk.Label(self.body, text=title, background=tone, foreground=COLORS["muted"],
                 font=(family, 9), anchor="w").grid(row=0, column=0, sticky="ew")
        self.value = tk.Label(self.body, text=value, background=tone, foreground=COLORS["text"],
                              font=(family, 12, "bold"), anchor="nw", justify="left", height=2)
        self.value.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.body.bind("<Configure>", lambda event: self.value.configure(wraplength=max(1, event.width)))

    def set(self, text, color=None):
        self.value.configure(text=text, foreground=color or COLORS["text"])


class VersionBanner(Surface):
    def __init__(self, parent, version, family):
        super().__init__(parent, height=104)
        self.body.rowconfigure((0, 1), weight=1)
        self.body.columnconfigure(1, weight=1)
        tk.Label(self.body, text="当前版本", background=self.tone, foreground=COLORS["muted"],
                 font=(family, 9), anchor="w").grid(row=0, column=0, sticky="w")
        tk.Label(self.body, text="v" + version, background=self.tone, foreground=COLORS["text"],
                 font=(family, 17, "bold")).grid(row=1, column=0, sticky="w")
        self.badge = tk.Label(self.body, text="未检查", font=(family, 10, "bold"), padx=12, pady=7)
        self.badge.grid(row=0, column=1, rowspan=2, padx=20, sticky="w")
        self.checked = tk.StringVar(value="—")
        self.recent = tk.Frame(self.body, background=self.tone)
        self.recent.grid(row=0, column=2, rowspan=2, sticky="w", padx=(12, 0))
        tk.Label(self.recent, text="最近成功检查", background=self.tone, foreground=COLORS["muted"],
                 font=(family, 9), anchor="w").pack(anchor="w")
        tk.Label(self.recent, textvariable=self.checked, background=self.tone, foreground=COLORS["text"],
                 font=(family, 10)).pack(anchor="w", pady=(4, 0))
        self.set_state("idle")

    def set_state(self, state, checked=None):
        self.state = state
        text, ink, fill = {
            "idle": ("未检查", COLORS["muted"], "#edf1f7"),
            "checking": ("检查中", COLORS["accent"], "#e3edff"),
            "current": ("已是最新版", COLORS["green"], COLORS["green_bg"]),
            "update": ("有新版本", COLORS["accent"], "#e3edff"),
            "error": ("检查失败", COLORS["amber"], COLORS["amber_bg"]),
        }[state]
        self.badge.configure(text=text, foreground=ink, background=fill)
        if checked is not None:
            self.checked.set(checked)

    def compact(self, compact):
        self.recent.grid_remove() if compact else self.recent.grid()


class ConfigTable(Surface):
    columns = (("name", "版本名称", 150), ("release_version", "版本号", 80), ("updated_at", "更新时间", 145),
               ("status", "状态", 100), ("description", "说明", 140), ("action", "操作", 86))

    def __init__(self, parent, family, apply):
        super().__init__(parent, height=300, tone="#ffffff")
        self.family, self.apply = family, apply
        self.rows, self.items, self.enabled, self.narrow = {}, [], True, False
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(1, weight=1)
        self.head = tk.Frame(self.body, background="#eaf0f9", padx=6, pady=10)
        self.head.grid(row=0, column=0, sticky="ew")
        self.heads = {}
        for col, (key, text, width) in enumerate(self.columns):
            label = tk.Label(self.head, text=text, background="#eaf0f9", foreground="#344560",
                             font=(family, 9, "bold"), anchor="w")
            label.grid(row=0, column=col, sticky="ew", padx=8)
            self.heads[key] = label
        self.canvas = tk.Canvas(self.body, background="#ffffff", highlightthickness=0, width=1)
        self.canvas.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        scroll = ttk.Scrollbar(self.body, command=self.canvas.yview)
        scroll.grid(row=1, column=1, sticky="ns", pady=(4, 0))
        self.canvas.configure(yscrollcommand=scroll.set)
        self.list = tk.Frame(self.canvas, background="#ffffff")
        self.list_window = self.canvas.create_window(0, 0, window=self.list, anchor="nw")
        self.list.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(self.list_window, width=event.width))
        self.empty = tk.Label(self.list, text="未读取配置", background="#ffffff", foreground=COLORS["muted"])
        self.empty.pack(pady=35)
        self.bind_wheel(self.canvas)
        self.layout_columns()

    def bind_wheel(self, widget):
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(event, self.wheel)

    def wheel(self, event):
        step = -1 if getattr(event, "num", None) == 4 or getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step * 3, "units")
        return "break"

    def clear(self, message="读取中…"):
        for row in self.rows.values():
            row["frame"].destroy()
        self.rows, self.items = {}, []
        self.canvas.yview_moveto(0)
        self.empty.configure(text=message)
        self.empty.pack(pady=35)

    def set_items(self, items):
        self.clear("暂无可用配置")
        self.items = list(items)
        if not items:
            return
        self.empty.pack_forget()
        for index, item in enumerate(items):
            active = item.get("active", False)
            fill = "#e8f1ff" if active else "#ffffff"
            frame = tk.Frame(self.list, background=fill, height=64, padx=6, highlightthickness=1,
                             highlightbackground=fill, takefocus=True)
            frame.pack(fill="x", pady=(0, 3))
            frame.grid_propagate(False)
            cells = {}
            values = {"name": item.get("display_name", item["version"]),
                      "status": "当前使用" if active else "可切换" if item["valid"] else "不可用"}
            for col, (key, title, width) in enumerate(self.columns[:-1]):
                text = values.get(key, item.get(key) or "—")
                if key == "status":
                    ink, bg = (COLORS["green"], COLORS["green_bg"]) if active else (COLORS["accent"], "#e5efff")
                else:
                    ink, bg = COLORS["text"], fill
                cell = tk.Label(frame, text=text, anchor="w", justify="left", height=2, width=1,
                                background=bg, foreground=ink, font=(self.family, 9, "bold" if key == "name" else "normal"))
                cell.grid(row=0, column=col, sticky="ew", padx=8, pady=8)
                cells[key] = cell
                self.bind_wheel(cell)
            button = ttk.Button(frame, text="使用中" if active else "应用", style="CompactPrimary.TButton", width=7,
                                command=lambda name=item["version"]: self.apply(name))
            button.grid(row=0, column=5, padx=8, pady=13, sticky="e")
            cells["action"] = button
            self.rows[item["version"]] = {"frame": frame, "cells": cells, "item": item, "button": button}
            for widget in (frame, button):
                self.bind_wheel(widget)
                for key, offset in (("<Up>", -1), ("<Down>", 1), ("<Home>", -100000), ("<End>", 100000)):
                    widget.bind(key, lambda event, i=index, move=offset: self.focus_row(i + move))
            frame.bind("<Return>", lambda event, name=item["version"]: self.activate(name))
            frame.bind("<Configure>", lambda event, row=self.rows[item["version"]]: self.wrap_row(row))
        self.layout_columns()
        self.set_enabled(self.enabled)

    def activate(self, name):
        row = self.rows[name]
        if self.enabled and row["item"]["valid"] and not row["item"].get("active"):
            self.apply(name)
        return "break"

    def focus_row(self, index):
        if not self.items:
            return "break"
        index = min(len(self.items)-1, max(0, index))
        row = self.rows[self.items[index]["version"]]
        row["frame"].focus_set()
        self.canvas.yview_moveto(max(0, row["frame"].winfo_y()-30) / max(1, self.list.winfo_height()))
        return "break"

    def set_enabled(self, enabled):
        self.enabled = enabled
        for row in self.rows.values():
            ready = enabled and row["item"]["valid"] and not row["item"].get("active")
            row["button"].configure(state="normal" if ready else "disabled")

    def compact(self, compact):
        if self.narrow != compact:
            self.narrow = compact
            self.layout_columns()

    def layout_columns(self):
        for col, (key, title, width) in enumerate(self.columns):
            hidden = self.narrow and key in ("updated_at", "description")
            frames = [self.head] + [row["frame"] for row in self.rows.values()]
            for frame in frames:
                frame.columnconfigure(col, weight=0 if hidden else 3 if key in ("name", "description") else 0,
                                      minsize=0 if hidden else width)
            widgets = [self.heads[key]] + [row["cells"][key] for row in self.rows.values()]
            for widget in widgets:
                widget.grid_remove() if hidden else widget.grid()

    def wrap_row(self, row):
        for col, (key, title, width) in enumerate(self.columns[:-1]):
            cell = row["cells"][key]
            if cell.winfo_manager():
                cell.configure(wraplength=max(40, row["frame"].grid_bbox(col, 0)[2]-20))
