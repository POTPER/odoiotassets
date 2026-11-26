"""界面主题与基础控件。

浅色主题色板、导航按钮、状态徽标等；仅用 Tk/ttk，不依赖外部样式库。
"""
import tkinter as tk
from tkinter import font, ttk


COLORS = {
    "bg": "#f5f7fa", "sidebar": "#142238", "panel": "#ffffff",
    "sidebar_text": "#f3f7ff", "sidebar_muted": "#b9c7dc",
    "field": "#ffffff", "hover": "#edf2f7", "border": "#dce2ea",
    "text": "#172033", "muted": "#5e6a7d", "disabled": "#8792a3",
    "accent": "#2563eb", "selection": "#dbeafe", "primary": "#2563eb",
    "green": "#176c44", "green_bg": "#eaf7ef",
    "red": "#b42318", "red_bg": "#fff0ee",
    "amber": "#8a5700", "amber_bg": "#fff6df",
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
    style.configure("TButton", background=c["bg"], foreground=c["text"], bordercolor=c["border"],
                    borderwidth=1, relief="flat", padding=(10, 4), anchor="center", focusthickness=1)
    style.map("TButton", background=[("disabled", c["panel"]), ("pressed", c["selection"]), ("active", c["hover"])],
              foreground=[("disabled", c["disabled"])], bordercolor=[("focus", c["accent"]), ("disabled", c["border"])])
    style.configure("Primary.TButton", background=c["primary"], foreground="#ffffff", bordercolor=c["primary"],
                    font=(family, 9, "bold"), padding=(14, 5))
    style.map("Primary.TButton", background=[("disabled", "#e5e7eb"), ("pressed", "#1e40af"), ("active", "#1d4ed8")],
              foreground=[("disabled", "#6b7280"), ("!disabled", "#ffffff")],
              bordercolor=[("focus", c["accent"]), ("disabled", c["border"]), ("!disabled", c["primary"])])
    style.layout("Channel.TRadiobutton", style.layout("TButton"))
    style.configure("Channel.TRadiobutton", padding=(12, 5), background=c["bg"],
                    foreground=c["text"], bordercolor=c["border"], borderwidth=1, relief="flat")
    style.map("Channel.TRadiobutton", background=[("disabled", c["panel"]), ("selected", c["accent"]), ("active", c["hover"])],
              foreground=[("disabled", c["disabled"]), ("selected", "#ffffff")],
              bordercolor=[("selected", c["accent"]), ("focus", c["accent"])])
    style.configure("Quiet.TButton", background=c["bg"], bordercolor=c["border"], padding=(10, 5))
    style.configure("Compact.TButton", padding=(6, 4))
    style.configure("CompactPrimary.TButton", background=c["primary"], foreground="#ffffff", padding=(10, 5), borderwidth=0)
    style.map("CompactPrimary.TButton", background=[("disabled", "#e0e8f3"), ("active", "#1d4ed8")],
              foreground=[("disabled", "#64748b"), ("!disabled", "#ffffff")])
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
                  indicatorforeground=[("selected", "#ffffff")])
    style.configure("Card.TCheckbutton", background=c["panel"], padding=1)
    style.map("Card.TCheckbutton", background=[("active", c["panel"])])
    style.configure("Treeview", background=c["field"], fieldbackground=c["field"], foreground=c["text"],
                    bordercolor=c["border"], borderwidth=0, rowheight=max(25, font.Font(root=root, name="TkDefaultFont", exists=True).metrics("linespace") + 4))
    style.configure("Treeview.Heading", background="#f1f5f9", foreground="#475569", borderwidth=0,
                    relief="flat", padding=(8, 6), font=(family, 9, "bold"))
    style.map("Treeview", background=[("selected", c["selection"])], foreground=[("selected", c["text"])])
    style.map("Treeview.Heading", background=[("active", c["hover"])])
    for orientation in ("Vertical", "Horizontal"):
        style.configure(orientation + ".TScrollbar", background="#cbd5e1", troughcolor=c["field"],
                        arrowcolor=c["muted"], borderwidth=0, arrowsize=11, relief="flat")
        style.map(orientation + ".TScrollbar", background=[("active", "#94a3b8"), ("pressed", "#64748b")])
    style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(0, 2, 0, 0))
    style.configure("TNotebook.Tab", background=c["panel"], foreground=c["muted"], padding=(16, 9), borderwidth=0)
    style.map("TNotebook.Tab", background=[("selected", c["bg"]), ("active", c["hover"])], foreground=[("selected", c["text"])])
    style.layout("Workspace.TNotebook.Tab", [])
    style.configure("Workspace.TNotebook", background=c["bg"], borderwidth=0, padding=0)
    style.configure("TPanedwindow", background=c["bg"])
    style.configure("Sash", sashthickness=5, background=c["border"])
    style.configure("Horizontal.TProgressbar", troughcolor=c["panel"], background=c["accent"], borderwidth=0,
                    lightcolor=c["accent"], darkcolor=c["accent"], thickness=3)
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


class NavButton(tk.Canvas):
    def __init__(self, master, text, short, command, family):
        super().__init__(master, height=52, background=COLORS["sidebar"], highlightthickness=0, takefocus=1, cursor="hand2")
        self.label, self.short, self.command, self.family = text, short, command, family
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
        fill = COLORS["accent"] if self.selected else "#203e69" if self.hovered else COLORS["sidebar"]
        ink = COLORS["sidebar_text"] if self.selected or self.hovered else COLORS["sidebar_muted"]
        height = self.winfo_reqheight()
        rounded(self, 3, 2, width - 3, height - 2, fill=fill,
                outline=COLORS["sidebar_text"] if self.focused else "")
        self.create_text(width / 2 if self.compact else 20, height / 2,
                         text=self.short if self.compact else self.label,
                         anchor="center" if self.compact else "w", fill=ink,
                         font=(self.family, 9 if self.compact else 10, "bold" if self.selected else "normal"))


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
        label, color = {"idle": ("就绪", COLORS["green"]), "busy": ("处理中", COLORS["accent"]),
                        "running": ("运行中", COLORS["green"]), "error": ("需检查", COLORS["amber"])}[phase]
        rounded(self, 0, 0, 100, 28, radius=8, fill=COLORS["panel"], outline="")
        self.create_oval(13, 11, 19, 17, fill=color, outline="")
        self.create_text(29, 14, text=label, anchor="w", fill=color, font=(self.family, 9))
