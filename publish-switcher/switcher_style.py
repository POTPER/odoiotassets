"""Epic-inspired dark desktop styling; standalone Tk/ttk, no external assets."""
import tkinter as tk
from tkinter import font, ttk


COLORS = {
    "bg": "#101014", "sidebar": "#17171c", "panel": "#1c1c23",
    "field": "#202027", "hover": "#303039", "border": "#2d2d36",
    "text": "#f5f5f7", "muted": "#9999a6", "disabled": "#696976",
    "accent": "#c0d5ff", "selection": "#35435c", "primary": "#eeeef2",
    "green": "#91e2bb", "green_bg": "#16352a",
    "red": "#ffaaa6", "red_bg": "#392027",
    "amber": "#e6bd7d", "amber_bg": "#362e20",
}


def rounded(canvas, x1, y1, x2, y2, radius=7, **options):
    points = (x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
              x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
              x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1)
    return canvas.create_polygon(points, smooth=True, splinesteps=20, **options)


def apply_theme(root):
    c = COLORS
    available = set(font.families(root=root))
    family = next((name for name in ("Noto Sans CJK SC", "Noto Sans SC", "Microsoft YaHei UI",
                                    "Microsoft YaHei", "微软雅黑", "WenQuanYi Micro Hei") if name in available),
                  font.Font(root=root, name="TkDefaultFont", exists=True).actual("family"))
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont", "TkTooltipFont"):
        try:
            font.Font(root=root, name=name, exists=True).configure(family=family, size=9)
        except tk.TclError:
            pass  # Some minimal Tk distributions omit tooltip/menu named fonts.
    root.configure(background=c["bg"])
    for pattern, value in (("*background", c["bg"]), ("*foreground", c["text"]),
                           ("*Text.background", c["field"]), ("*Text.foreground", c["text"]),
                           ("*Text.insertBackground", c["text"]), ("*Text.selectBackground", c["selection"]),
                           ("*Text.selectForeground", c["text"]), ("*Text.highlightThickness", 0),
                           ("*Text.borderWidth", 0), ("*TCombobox*Listbox.background", c["field"]),
                           ("*TCombobox*Listbox.foreground", c["text"]),
                           ("*TCombobox*Listbox.selectBackground", c["selection"]),
                           ("*TCombobox*Listbox.selectForeground", c["text"])):
        root.option_add(pattern, value)
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=c["bg"], foreground=c["text"], font=(family, 9),
                    bordercolor=c["border"], lightcolor=c["border"], darkcolor=c["border"], focuscolor=c["accent"])
    style.configure("TFrame", background=c["bg"])
    style.configure("Toolbar.TFrame", background=c["panel"])
    style.configure("TLabel", background=c["bg"], foreground=c["text"])
    style.configure("Muted.TLabel", foreground=c["muted"])
    style.configure("Title.TLabel", font=(family, 17, "bold"))
    style.configure("PageTitle.TLabel", font=(family, 21, "bold"))
    style.configure("CompactTitle.TLabel", font=(family, 17, "bold"))
    style.configure("Section.TLabel", font=(family, 10, "bold"))
    style.configure("TLabelframe", background=c["bg"], bordercolor=c["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", foreground=c["muted"], background=c["bg"], font=(family, 9, "bold"))
    style.configure("TButton", background="#25252e", foreground=c["text"], bordercolor="#3b3b46",
                    borderwidth=1, relief="flat", padding=(10, 4), anchor="center", focusthickness=1)
    style.map("TButton", background=[("disabled", "#1c1c23"), ("pressed", "#1a1a21"), ("active", c["hover"])],
              foreground=[("disabled", c["disabled"])], bordercolor=[("focus", c["accent"]), ("disabled", c["border"])])
    style.configure("Primary.TButton", background=c["primary"], foreground="#111116", bordercolor=c["primary"],
                    font=(family, 9, "bold"), padding=(14, 5))
    style.map("Primary.TButton", background=[("disabled", "#2b2b34"), ("pressed", "#d7d7df"), ("active", "#ffffff")],
              foreground=[("disabled", "#a5a5b1"), ("!disabled", "#111116")],
              bordercolor=[("focus", c["accent"]), ("disabled", "#2b2b34"), ("!disabled", c["primary"])])
    style.configure("Quiet.TButton", background=c["bg"], bordercolor=c["border"], padding=(10, 5))
    style.configure("Compact.TButton", padding=(6, 4))
    style.configure("Panel.TLabel", background=c["panel"])
    style.configure("PanelMuted.TLabel", background=c["panel"], foreground=c["muted"])
    for name in ("TEntry", "TCombobox"):
        style.configure(name, fieldbackground=c["field"], foreground=c["text"], insertcolor=c["text"],
                        bordercolor=c["border"], arrowcolor=c["muted"], padding=6)
        style.map(name, fieldbackground=[("disabled", c["panel"]), ("readonly", c["field"])],
                  foreground=[("disabled", c["disabled"]), ("readonly", c["text"])],
                  bordercolor=[("focus", c["accent"])], selectbackground=[("!disabled", c["selection"])],
                  selectforeground=[("!disabled", c["text"])])
    style.configure("Path.TEntry", fieldbackground=c["panel"], borderwidth=0, padding=(6, 4))
    style.map("Path.TEntry", fieldbackground=[("readonly", c["panel"])], foreground=[("readonly", c["muted"])])
    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(name, background=c["bg"], foreground=c["text"], indicatorbackground=c["field"],
                        indicatorforeground=c["accent"], padding=2)
        style.map(name, background=[("active", c["bg"])], foreground=[("disabled", c["disabled"])],
                  indicatorbackground=[("disabled", c["panel"]), ("selected", c["accent"])],
                  indicatorforeground=[("selected", "#111116")])
    style.configure("Card.TCheckbutton", background=c["panel"], padding=1)
    style.map("Card.TCheckbutton", background=[("active", c["panel"])])
    style.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["text"],
                    bordercolor=c["border"], borderwidth=0, rowheight=max(25, font.Font(root=root, name="TkDefaultFont", exists=True).metrics("linespace") + 4))
    style.configure("Treeview.Heading", background="#282830", foreground="#b6b6c2", borderwidth=0,
                    relief="flat", padding=(8, 6), font=(family, 9, "bold"))
    style.map("Treeview", background=[("selected", c["selection"])], foreground=[("selected", c["text"])])
    style.map("Treeview.Heading", background=[("active", c["hover"])])
    for orientation in ("Vertical", "Horizontal"):
        style.configure(orientation + ".TScrollbar", background="#3b3b46", troughcolor=c["field"],
                        arrowcolor=c["muted"], borderwidth=0, arrowsize=11, relief="flat")
        style.map(orientation + ".TScrollbar", background=[("active", "#555562"), ("pressed", "#696978")])
    style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 2, 0, 0))
    style.configure("TNotebook.Tab", background=c["panel"], foreground=c["muted"], padding=(16, 9), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", "#2b2b33"), ("active", c["hover"])], foreground=[("selected", c["text"])])
    style.layout("Workspace.TNotebook.Tab", [])
    style.configure("Workspace.TNotebook", background=c["bg"], borderwidth=0, padding=0)
    style.configure("TPanedwindow", background=c["bg"])
    style.configure("Sash", sashthickness=5, background=c["border"])
    style.configure("Horizontal.TProgressbar", troughcolor=c["panel"], background="#8bb5ec", borderwidth=0,
                    lightcolor="#8bb5ec", darkcolor="#8bb5ec", thickness=3)
    return family


def style_dialog(window):
    window.configure(background=COLORS["bg"])
    def fit(event):
        if event.widget is not window:
            return
        width = max(200, event.width - 36)
        def visit(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Label) and child.cget("wraplength"):
                    if not hasattr(child, "_preferred_wrap"):
                        child._preferred_wrap = int(float(str(child.cget("wraplength"))))
                    child.configure(wraplength=min(child._preferred_wrap, width))
                visit(child)
        visit(window)
    window.bind("<Configure>", fit, add="+")


def icon(canvas, name, x, y, color, size=18):
    s = size / 20
    def line(*points):
        canvas.create_line(*[value * s + (x if i % 2 == 0 else y) for i, value in enumerate(points)], fill=color, width=1.5)
    def rect(a, b, c, d):
        canvas.create_rectangle(x + a * s, y + b * s, x + c * s, y + d * s, outline=color, width=1.5)
    if name == "update":
        line(5, 17, 5, 3, 1, 7)
        line(5, 3, 9, 7)
        line(15, 3, 15, 17, 11, 13)
        line(15, 17, 19, 13)
    elif name == "assets":
        rect(1, 2, 19, 18)
        line(2, 16, 7, 10, 11, 14, 15, 9, 19, 14)
        canvas.create_oval(x + 5*s, y + 5*s, x + 8*s, y + 8*s, fill=color, outline="")
    elif name == "config":
        for row, pos in ((4, 6), (10, 14), (16, 8)):
            line(1, row, 19, row)
            rect(pos-2, row-2, pos+2, row+2)
    elif name == "demo":
        rect(1, 2, 19, 16)
        line(7, 20, 13, 20)
        line(10, 16, 10, 20)
        canvas.create_polygon(x+8*s, y+6*s, x+8*s, y+12*s, x+13*s, y+9*s, fill=color)
    elif name == "tools":
        line(3, 17, 15, 5)
        line(10, 4, 10, 8, 14, 10, 18, 8, 18, 3)
        line(2, 15, 5, 18)
    else:
        canvas.create_oval(x+4*s, y+4*s, x+16*s, y+16*s, outline=color, width=1.5)
        canvas.create_oval(x+8*s, y+8*s, x+12*s, y+12*s, outline=color, width=1.5)
        for points in ((10, 0, 10, 4), (10, 16, 10, 20), (0, 10, 4, 10), (16, 10, 20, 10),
                       (3, 3, 6, 6), (14, 14, 17, 17), (3, 17, 6, 14), (14, 6, 17, 3)):
            line(*points)


class NavButton(tk.Canvas):
    def __init__(self, master, text, short, symbol, command, family):
        super().__init__(master, height=52, background=COLORS["sidebar"], highlightthickness=0, takefocus=1, cursor="hand2")
        self.label, self.short, self.symbol, self.command, self.family = text, short, symbol, command, family
        self.selected = self.hovered = self.focused = self.compact = False
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Enter>", lambda _: self.hover(True))
        self.bind("<Leave>", lambda _: self.hover(False))
        self.bind("<FocusIn>", lambda _: self.set_focused(True))
        self.bind("<FocusOut>", lambda _: self.set_focused(False))
        self.bind("<ButtonRelease-1>", self.click)
        self.bind("<Return>", lambda _: self.invoke())
        self.bind("<space>", lambda _: self.invoke())

    def invoke(self):
        self.focus_set()
        self.command()
        return "break"

    def click(self, event):
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            return self.invoke()

    def set_focused(self, value):
        self.focused = value
        self.draw()

    def hover(self, value):
        self.hovered = value
        self.draw()

    def set_selected(self, value):
        self.selected = value
        self.draw()

    def set_compact(self, value):
        self.compact = value
        self.draw()

    def draw(self):
        self.delete("all")
        width = max(40, self.winfo_width())
        fill = "#2b2b33" if self.selected else "#222229" if self.hovered else COLORS["sidebar"]
        ink = COLORS["text"] if self.selected or self.hovered else COLORS["muted"]
        rounded(self, 3, 2, width-3, 50, fill=fill, outline=COLORS["accent"] if self.focused else "")
        if self.selected:
            self.create_rectangle(3, 16, 6, 36, fill=COLORS["accent"], outline="")
        icon(self, self.symbol, (width-18)/2 if self.compact else 19, 9 if self.compact else 16, ink)
        self.create_text(width/2 if self.compact else 52, 39 if self.compact else 26, text=self.short if self.compact else self.label,
                         anchor="center" if self.compact else "w", fill=ink,
                         font=(self.family, 8 if self.compact else 10, "bold" if self.selected else "normal"))


class StatusBadge(tk.Canvas):
    def __init__(self, master, family):
        super().__init__(master, width=100, height=28, background=COLORS["bg"], highlightthickness=0)
        self.family, self.phase = family, None
        self.set_phase("idle")

    def set_phase(self, phase):
        if self.phase == phase:
            return
        self.phase = phase
        self.delete("all")
        label, color = {"idle": ("就绪", COLORS["green"]), "busy": ("处理中", "#83b7ff"),
                        "running": ("运行中", COLORS["green"]), "error": ("需检查", COLORS["amber"])}[phase]
        rounded(self, 0, 0, 100, 28, radius=8, fill="#222229", outline="")
        self.create_oval(13, 11, 19, 17, fill=color, outline="")
        self.create_text(29, 14, text=label, anchor="w", fill=color, font=(self.family, 9))
