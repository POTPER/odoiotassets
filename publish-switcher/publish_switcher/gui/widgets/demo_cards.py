"""IoT Demo 任务卡片。

可滚动卡片网格，显示每个脚本的运行状态、耗时与退出码。
"""
import tkinter as tk
from tkinter import ttk

from publish_switcher.gui.widgets.style import COLORS


PHASES = {"queued": "等待启动", "running": "运行中", "completed": "已完成", "failed": "异常",
          "stopped": "已停止", "not_started": "未启动", "skipped": "已跳过"}


def format_duration(seconds):
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return "{}:{:02d}:{:02d}".format(hours, minutes, seconds) if hours else "{:02d}:{:02d}".format(minutes, seconds)


class DemoCard(tk.Frame):
    def __init__(self, master, key, name, scripts, error, family, select, activate, check_changed):
        super().__init__(master, background=COLORS["panel"], highlightthickness=1,
                         highlightbackground=COLORS["border"], padx=9, pady=7, takefocus=True)
        self.elapsed = None
        self.key, self.error, self.scripts = key, error, {}
        self.selected = False
        header = tk.Frame(self, background=COLORS["panel"])
        header.pack(fill="x")
        self.checked = tk.BooleanVar(master=self, value=False)
        self.check = ttk.Checkbutton(header, variable=self.checked, command=check_changed, style="Card.TCheckbutton")
        self.check.pack(side="left", padx=(0, 3))
        tk.Label(header, text="#" + key, background=COLORS["panel"], foreground=COLORS["muted"],
                 font=(family, 8)).pack(side="left")
        self.phase = tk.Label(header, text="不可运行" if error else "就绪", background=COLORS["panel"],
                              foreground=COLORS["red"] if error else COLORS["muted"], font=(family, 8, "bold"))
        self.phase.pack(side="right")
        self.name_label = tk.Label(self, text=name, font=(family, 11, "bold"), height=2,
                                   background=COLORS["panel"], foreground=COLORS["text"], anchor="nw", justify="left")
        self.name_label.pack(fill="x", pady=(5, 2))
        self.subtitle = tk.Label(self, text="脚本与实时状态", background=COLORS["panel"],
                                 foreground=COLORS["muted"], font=(family, 8), anchor="w")
        self.subtitle.pack(fill="x")
        detailbox = tk.Frame(self, background=COLORS["panel"])
        detailbox.pack(fill="both", expand=True)
        self.details = tk.Text(detailbox, height=4, width=1, wrap="word", background=COLORS["panel"],
                               foreground=COLORS["muted"], borderwidth=0, highlightthickness=0,
                               font=(family, 8), cursor="arrow", takefocus=False, padx=0, pady=4)
        self.details.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(detailbox, command=self.details.yview)
        scroll.pack(side="right", fill="y")
        self.details.configure(yscrollcommand=scroll.set)
        self.details.tag_configure("running", foreground=COLORS["green"])
        self.details.tag_configure("failed", foreground=COLORS["red"])
        for script in scripts:
            self.scripts[script] = {"phase": "queued", "pid": None, "initial": True}
        self.bind("<Return>", lambda event: select(key))
        self.bind("<space>", lambda event: select(key))
        def bind_children(widget):
            if widget is self.check:
                return
            widget.bind("<Button-1>", lambda event: select(key))
            widget.bind("<Double-1>", lambda event: activate(key))
            for child in widget.winfo_children():
                bind_children(child)
        bind_children(self)
        self.render()

    def fit(self, width):
        self.name_label.configure(wraplength=max(120, width - 24))

    def highlight(self, selected):
        self.selected = selected
        self.configure(highlightbackground=COLORS["accent"] if selected else COLORS["border"])

    def update_state(self, event):
        script = event["script"]
        # Runtime events are generated from the scripts actually started, not log text.
        self.scripts[script] = dict(event)
        self.render()

    def set_elapsed(self, seconds):
        self.elapsed = seconds
        running = any(s.get("phase") == "running" for s in self.scripts.values())
        text = "正在运行的脚本" if running else "脚本与实时状态"
        if seconds is not None:
            text += " · " + format_duration(seconds)
        self.subtitle.configure(text=text)

    def render(self):
        states = list(self.scripts.values())
        running = [s for s in states if s.get("phase") == "running"]
        failed = any(s.get("phase") == "failed" for s in states)
        if self.error:
            text, colour = "不可运行", COLORS["red"]
        elif running:
            text, colour = "运行中 {}".format(len(running)), COLORS["green"]
        elif failed:
            text, colour = "异常结束", COLORS["red"]
        elif states and all(s.get("phase") == "completed" for s in states):
            text, colour = "已完成", COLORS["green"]
        elif any(s.get("phase") == "skipped" for s in states):
            text, colour = "已跳过", COLORS["amber"]
        elif any(s.get("phase") == "stopped" for s in states):
            text, colour = "已停止", COLORS["amber"]
        elif any(s.get("phase") == "not_started" for s in states):
            text, colour = "未启动", COLORS["muted"]
        elif any(not s.get("initial") for s in states):
            text, colour = "等待启动", COLORS["amber"]
        else:
            text, colour = "就绪", COLORS["muted"]
        self.phase.configure(text=text, foreground=colour)
        self.set_elapsed(self.elapsed)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if self.error:
            self.details.insert("end", self.error, "failed")
        else:
            for script, event in self.scripts.items():
                phase = event.get("phase")
                description = "待运行" if event.get("initial") else PHASES.get(phase, phase)
                if event.get("pid"):
                    description += " · PID {}".format(event["pid"])
                if event.get("exit_code") is not None:
                    description += " · 退出码 {}".format(event["exit_code"])
                self.details.insert("end", script + "\n")
                self.details.insert("end", "  " + description + "\n", phase if phase in ("running", "failed") else ())
                if event.get("error"):
                    self.details.insert("end", "  " + event["error"] + "\n", "failed")
        self.details.configure(state="disabled")


class DemoGrid(ttk.Frame):
    def __init__(self, master, family, activate):
        super().__init__(master)
        self.family, self.activate = family, activate
        self.cards, self.selected, self.enabled = {}, None, True
        self.checking_enabled = True
        self.columns = 0
        self.canvas = tk.Canvas(self, background=COLORS["bg"], highlightthickness=0, width=365, height=270)
        scroll = ttk.Scrollbar(self, command=self.canvas.yview)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", self.reflow)
        self.canvas.bind("<MouseWheel>", self.wheel)
        self.canvas.bind("<Button-4>", lambda event: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda event: self.canvas.yview_scroll(3, "units"))
        self.empty = ttk.Label(self.content, text="选择 publish 目录后，点击“刷新”读取模块。",
                               style="Muted.TLabel", wraplength=230, justify="left")
        self.empty.grid(padx=14, pady=20)

    def wheel(self, event):
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def set_tasks(self, rows):
        old = self.selected
        self.clear()
        for key, name, scripts, error in rows:
            card = DemoCard(self.content, key, name, scripts, error, self.family, self.select, self.open_task,
                            self.check_changed)
            self.cards[key] = card
            def bind_wheel(widget):
                widget.bind("<MouseWheel>", self.wheel)
                widget.bind("<Button-4>", lambda event: self.canvas.yview_scroll(-3, "units"))
                widget.bind("<Button-5>", lambda event: self.canvas.yview_scroll(3, "units"))
                for child in widget.winfo_children():
                    bind_wheel(child)
            bind_wheel(card)
        if rows:
            self.empty.grid_remove()
        self.columns = 0
        self.reflow()
        self.enable_checking(self.checking_enabled)
        if old in self.cards:
            self.select(old)

    def clear(self):
        for card in self.cards.values():
            card.destroy()
        self.cards.clear()
        self.selected = None
        self.empty.grid()

    def check_changed(self):
        self.event_generate("<<DemoCheck>>")

    def checked_keys(self):
        return [key for key, card in self.cards.items() if not card.error and card.checked.get()]

    def check_all(self, checked):
        if self.checking_enabled:
            for card in self.cards.values():
                card.checked.set(bool(checked and not card.error))
            self.check_changed()

    def enable_checking(self, enabled):
        self.checking_enabled = enabled
        for card in self.cards.values():
            card.check.state(["!disabled"] if enabled and not card.error else ["disabled"])

    def select(self, key):
        if not self.enabled or key not in self.cards:
            return
        self.selected = key
        for item, card in self.cards.items():
            card.highlight(item == key)
        self.event_generate("<<DemoSelect>>")

    def open_task(self, key):
        if self.enabled:
            self.select(key)
            self.activate()

    def reveal(self, key):
        if key not in self.cards:
            return
        self.select(key)
        card = self.cards[key]
        top = card.winfo_y()
        bottom = top + card.winfo_height()
        view_top = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        if top < view_top or bottom > view_top + height:
            self.canvas.yview_moveto(top / max(1, self.content.winfo_height()))

    def update_state(self, event):
        card = self.cards.get(str(event["task_id"]))
        if card:
            card.update_state(event)

    def reflow(self, event=None):
        width = max(170, self.canvas.winfo_width())
        columns = max(1, width // 205)
        self.canvas.itemconfigure(self.window, width=width)
        if columns != self.columns:
            for column in range(max(columns, self.columns)):
                self.content.columnconfigure(column, weight=1 if column < columns else 0, uniform="cards")
            for index, card in enumerate(self.cards.values()):
                card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=4, pady=4)
            self.columns = columns
        for card in self.cards.values():
            card.fit(width // columns - 10)
