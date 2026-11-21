"""参考风格界面部件。

深蓝侧栏、配置列表行与真实「应用」按钮，全部用标准 Tk 绘制。
"""
import tkinter as tk
from tkinter import ttk

from publish_switcher.gui.widgets.style import COLORS, rounded, icon
from publish_switcher.gui.widgets.assets import asset


class SidebarArt(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, background=COLORS["sidebar"], highlightthickness=0)
        self.bind("<Configure>", self.draw)

    def draw(self, event):
        self.delete("all")
        w, h = event.width, event.height
        self.photo = asset(self, "sidebar-background-v10.png", cover=(w, h))
        if self.photo:
            self.create_image(w/2, h/2, image=self.photo)
            return
        # Static geometry, redrawn only on resize; no animation or image dependency.
        self.create_polygon(0, h*.78, w, h*.58, w, h*.87, 0, h*.95, fill="#173d73", outline="")
        self.create_polygon(0, h*.88, w, h*.65, w, h*.71, 0, h*.93, fill="#1a4d94", outline="")
        self.create_line(0, h*.88, w, h*.65, fill="#2565ba")


class UpdateDecoration(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, width=150, height=65, background=COLORS["bg"], highlightthickness=0)
        self.photo = asset(self, "update-hero-64.png")
        if self.photo:
            self.create_image(78, 32, image=self.photo)
            return
        for dy, fill in ((25, "#e5edfc"), (12, "#dce8ff"), (0, "#caddff")):
            self.create_polygon(34, 22+dy, 78, 2+dy, 122, 22+dy, 78, 42+dy, fill=fill, outline="#eef5ff")
        self.create_line(78, 28, 78, 10, 68, 20, fill="#ffffff", width=3)
        self.create_line(78, 10, 88, 20, fill="#ffffff", width=3)


class Surface(tk.Canvas):
    def __init__(self, parent, height=110, tone="#fbfdff", art=False):
        super().__init__(parent, height=height, width=1, highlightthickness=0, background=COLORS["bg"])
        self.tone, self.art = tone, art
        self.body = tk.Frame(self, background=tone)
        self.window = self.create_window(18, 16, window=self.body, anchor="nw")
        self.bind("<Configure>", self.draw)

    def draw(self, event):
        w, h = event.width, event.height
        self.delete("surface")
        rounded(self, 3, 5, w-3, h-1, radius=14, fill="#e0e8f5", outline="", tags="surface")
        rounded(self, 1, 1, w-4, h-5, radius=14, fill=self.tone, outline="#cbdaf0", tags="surface")
        self.itemconfigure(self.window, width=max(1, w-40), height=max(1, h-36))
        if self.art and w > 650:
            for dy, color in ((28, "#e9f1ff"), (15, "#dfebff"), (2, "#d4e4ff")):
                self.create_polygon(w-150, dy+33, w-90, dy, w-30, dy+33, w-90, dy+65,
                                    fill=color, outline="#eff6ff", tags="surface")
        self.tag_lower("surface", self.window)


def symbol(canvas, kind, color):
    canvas.delete("all")
    canvas.create_oval(1, 1, 43, 43, fill="#e0edff", outline="")
    if kind == "config":
        photo = asset(canvas, "config-icon-24.png")
        if photo:
            canvas.create_image(22, 22, image=photo)
            return
    if kind == "layers":
        for offset in (0, 7, 14):
            canvas.create_line(10, 15+offset, 22, 8+offset, 34, 15+offset, 22, 22+offset, 10, 15+offset,
                               fill=color, width=2)
    elif kind == "check":
        canvas.create_oval(10, 10, 34, 34, outline=color, width=2)
        canvas.create_line(15, 22, 20, 27, 29, 17, fill=color, width=2)
    else:
        icon(canvas, kind, 11, 11, color, 24)


class InfoCard(Surface):
    def __init__(self, parent, title, value, family, kind="layers", tone="#edf4ff", color=None):
        super().__init__(parent, height=114, tone=tone)
        self.kind, self.color = kind, color or COLORS["accent"]
        self.body.columnconfigure(1, weight=1)
        self.symbol = tk.Canvas(self.body, width=46, height=46, highlightthickness=0, background=tone)
        self.symbol.grid(row=0, column=0, rowspan=2, padx=(0, 10), sticky="w")
        tk.Label(self.body, text=title, background=tone, foreground=COLORS["muted"],
                 font=(family, 9), anchor="w").grid(row=0, column=1, sticky="ew")
        self.value = tk.Label(self.body, text=value, background=tone, foreground=COLORS["text"],
                              font=(family, 12, "bold"), anchor="nw", justify="left", height=2)
        self.value.grid(row=1, column=1, sticky="ew")
        self.body.bind("<Configure>", lambda event: self.value.configure(wraplength=max(80, event.width-65)))
        symbol(self.symbol, kind, self.color)

    def set(self, text, color=None):
        self.value.configure(text=text, foreground=color or COLORS["text"])
        symbol(self.symbol, self.kind, color or self.color)


class VersionBanner(Surface):
    def __init__(self, parent, version, family):
        super().__init__(parent, height=152, art=True)
        self.body.columnconfigure(2, weight=1)
        marker = tk.Canvas(self.body, width=46, height=46, background=self.tone, highlightthickness=0)
        marker.grid(row=0, column=0, rowspan=2, padx=(0, 16))
        symbol(marker, "layers", COLORS["accent"])
        tk.Label(self.body, text="当前版本", background=self.tone, foreground=COLORS["muted"],
                 font=(family, 9), anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(self.body, text="v" + version, background=self.tone, foreground=COLORS["text"],
                 font=(family, 17, "bold")).grid(row=1, column=1, sticky="w")
        self.badge = tk.Label(self.body, text="未检查", font=(family, 10, "bold"), padx=12, pady=7)
        self.badge.grid(row=0, column=2, rowspan=2, padx=20, sticky="w")
        self.checked = tk.StringVar(value="—")
        self.recent = tk.Frame(self.body, background=self.tone)
        self.recent.grid(row=0, column=3, rowspan=2, sticky="w", padx=(12, 0))
        tk.Label(self.recent, text="最近成功检查", background=self.tone, foreground=COLORS["muted"],
                 font=(family, 9), anchor="w").pack(anchor="w")
        tk.Label(self.recent, textvariable=self.checked, background=self.tone, foreground=COLORS["text"],
                 font=(family, 10)).pack(anchor="w", pady=(4, 0))
        self.illustration = tk.Canvas(self.body, width=112, height=112, background=self.tone, highlightthickness=0)
        self.hero = asset(self, "update-hero-112.png")
        if self.hero:
            self.illustration.create_image(56, 56, image=self.hero)
        self.body.bind("<Configure>", self.fit)
        self.narrow = False
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
        self.narrow = compact
        self.recent.grid_remove() if compact else self.recent.grid()
        self.fit()

    def fit(self, event=None):
        show = not self.narrow and self.body.winfo_width() >= 880
        self.body.columnconfigure(4, minsize=130 if show else 0)
        if show:
            self.illustration.place(relx=1, rely=.5, anchor="e", width=112, height=112)
        else:
            self.illustration.place_forget()


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
