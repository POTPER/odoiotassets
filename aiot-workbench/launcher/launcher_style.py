"""Dark launcher chrome and keyboard-accessible Canvas buttons; Tk only."""
import tkinter as tk
import logging
from pathlib import Path
import sys

from core import SyncError


BG = "#101014"
SIDEBAR = "#17171c"
TEXT = "#f5f5f7"
MUTED = "#9999a6"
BORDER = "#2d2d36"
BACKGROUND_OPACITY = 0.48
APP_NAME = "2026金砖赛事-物联传感技术应用"
SIDEBAR_NAME = "物联传感技术应用"
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 620
THEMES = {
    "dark": {"bg": BG, "sidebar": SIDEBAR, "text": TEXT, "muted": MUTED,
             "border": BORDER, "selected": "#2b2b33", "accent": "#c0d5ff",
             "primary": "#eeeeF2", "primary_text": "#111116", "button": BG,
             "button_edge": "#545460", "disabled": "#686875", "running": "#173b30", "running_text": "#91e2bb"},
    "light": {"bg": "#edf1f6", "sidebar": "#fafbfe", "text": "#182337", "muted": "#627087",
              "border": "#ced6e2", "selected": "#e1e8f2", "accent": "#3268bb",
              "primary": "#244d85", "primary_text": "#ffffff", "button": "#fafbfe",
              "button_edge": "#a8b5c8", "disabled": "#8895a7", "running": "#d8efe1", "running_text": "#226744"},
}


def palette(theme):
    return THEMES[theme if theme in THEMES else "dark"]


def image_component_error(exc):
    return SyncError("高清图片组件不可用，请重新运行 install-launcher.sh，或为当前 Python 安装 "
                     "python3-pil 和 python3-pil.imagetk。\nPython：{}\n原因：{}".format(sys.executable, exc))


def load_image_pixels(path):
    """Read the original file; never round-trip through Tk's getimage hook."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        from PIL import Image
    except ImportError as exc:
        raise image_component_error(exc) from exc
    try:
        with Image.open(str(path)) as source:
            return source.convert("RGBA")
    except OSError as exc:
        logging.getLogger(__name__).warning("无法读取图片 %s：%s", path, exc)
        return None


def image_photo(pixels, master):
    try:
        from PIL import ImageTk
        return ImageTk.PhotoImage(pixels, master=master)
    except (ImportError, tk.TclError, RuntimeError) as exc:
        raise image_component_error(exc) from exc


def rounded(canvas, x1, y1, x2, y2, radius=8, **options):
    points = (x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius,
              x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2,
              x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1)
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **options)


def blend(first, second, amount):
    a = [int(first[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(second[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join("{:02x}".format(round(x + (y - x) * amount)) for x, y in zip(a, b))


class LauncherButton(tk.Canvas):
    def __init__(self, master, text, command, family, primary=False, width=160, theme="dark", sidebar=False):
        self.label, self.command, self.family = text, command, family
        self.primary, self.enabled = primary, False
        self.colors, self.sidebar = palette(theme), sidebar
        self.hovered, self.pressed, self.focused = False, False, False
        super().__init__(master, width=width, height=54, background=self.colors["sidebar" if sidebar else "bg"],
                         highlightthickness=0, borderwidth=0, takefocus=0)
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Enter>", lambda _: self._hover(True))
        self.bind("<Leave>", lambda _: self._hover(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<FocusIn>", lambda _: self._focus(True))
        self.bind("<FocusOut>", lambda _: self._focus(False))
        for key in ("space", "Return"):
            self.bind("<KeyPress-" + key + ">", self._key_press)
            self.bind("<KeyRelease-" + key + ">", self._key_release)

    def configure(self, cnf=None, **options):
        if cnf is not None:
            if isinstance(cnf, str):
                return super().configure(cnf, **options)
            options = dict(cnf, **options)
        if "text" in options:
            self.label = options.pop("text")
        if "state" in options:
            self.enabled = options.pop("state") == "normal"
            self.pressed = False
            options["takefocus"] = int(self.enabled)
            options["cursor"] = "hand2" if self.enabled else "arrow"
        if options:
            super().configure(**options)
        if hasattr(self, "_w"):
            self.draw()

    config = configure

    def cget(self, key):
        if key == "text":
            return self.label
        if key == "state":
            return "normal" if self.enabled else "disabled"
        return super().cget(key)

    def invoke(self):
        if self.enabled:
            return self.command()

    def set_theme(self, theme):
        self.colors = palette(theme)
        super().configure(background=self.colors["sidebar" if self.sidebar else "bg"])
        self.draw()

    def _hover(self, value):
        self.hovered = value
        if not value:
            self.pressed = False
        self.draw()

    def _focus(self, value):
        self.focused = value
        if not value:
            self.pressed = False
        self.draw()

    def _press(self, event):
        if self.enabled:
            self.focus_set()
            self.pressed = True
            self.draw()
        return "break"

    def _release(self, event):
        activate = self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self.pressed = False
        self.draw()
        if activate:
            self.invoke()
        return "break"

    def _key_press(self, event):
        if self.enabled:
            self.pressed = True
            self.draw()
        return "break"

    def _key_release(self, event):
        activate = self.pressed
        self.pressed = False
        self.draw()
        if activate:
            self.invoke()
        return "break"

    def draw(self):
        width = max(self.winfo_width(), int(super().cget("width")))
        height = 54
        self.delete("all")
        running = self.label == "运行中"
        colors = self.colors
        if self.primary:
            fill, ink, edge = (colors["running"], colors["running_text"], colors["running_text"]) if running else (
                colors["primary"], colors["primary_text"], colors["primary"])
            if self.hovered and self.enabled:
                fill = blend(fill, colors["text"], 0.12 if self.pressed else 0.06)
            if not self.enabled and not running:
                fill, ink, edge = colors["selected"], colors["muted"], colors["selected"]
        else:
            fill = colors["selected"] if self.hovered and self.enabled else colors["sidebar" if self.sidebar else "button"]
            ink, edge = colors["text"], colors["border" if self.sidebar else "button_edge"]
            if not self.enabled:
                ink, edge = colors["disabled"], colors["border"]
        rounded(self, 1, 1, width - 1, height - 1, fill=fill, outline=edge, width=1)
        if self.focused and self.enabled:
            rounded(self, 4, 4, width - 4, height - 4, radius=5, fill="", outline="#71a9ff", width=2)
        text_width = self.tk.call("font", "measure", (self.family, 12, "bold"), self.label)
        x = (width - int(text_width) - 26) / 2
        if running:
            self.create_oval(x, 21, x + 11, 32, fill=ink, outline="")
        elif self.label == "设置":
            self.create_oval(x, 20, x + 13, 33, outline=ink, width=2)
            self.create_oval(x + 5, 25, x + 8, 28, fill=ink, outline="")
        elif self.label == "查看成果":
            self.create_polygon(x, 21, x + 5, 21, x + 8, 24, x + 15, 24,
                                x + 15, 33, x, 33, fill="", outline=ink, width=1.5)
        elif self.primary:
            self.create_polygon(x, 19, x, 35, x + 12, 27, fill=ink, outline="")
        else:
            self.create_rectangle(x, 22, x + 10, 32, outline=ink, width=1.5)
        self.create_text(x + 25, 27, text=self.label, font=(self.family, 12, "bold"), fill=ink, anchor="w")


class LauncherChrome(tk.Canvas):
    def __init__(self, master, family, photo=None, icon=None, theme="dark", source_pixels=None, icon_pixels=None):
        self.theme, self.colors = theme, palette(theme)
        super().__init__(master, background=self.colors["bg"], highlightthickness=0)
        self.family, self.photo = family, photo
        self._source_pixels = source_pixels
        self.brand_icon = self.app_icon = None
        if icon is not None:
            extent = max(icon.width(), icon.height())
            if icon_pixels is not None:
                from PIL import Image
                pixels = icon_pixels
                resampling = getattr(Image, "Resampling", Image).LANCZOS
                self.brand_icon, self.app_icon = (
                    image_photo(pixels.resize((max(1, round(icon.width() * size / extent)),
                                               max(1, round(icon.height() * size / extent))),
                                              resampling), self)
                    for size in (32, 23))
            else:
                self.brand_icon = icon.subsample(max(1, (extent + 31) // 32))
                self.app_icon = icon.subsample(max(1, (extent + 22) // 23))
        self.cover = None
        self._cover_size = None
        self.phase, self.message = "loading", "正在加载…"
        self.message_item = None
        self._rendered_size = None
        self.layout_callback = None
        self.resize_job = None
        self.bind("<Configure>", self._resize)

    def _resize(self, event):
        if event.width < 200 or event.height < 200:
            return
        # Place the real controls immediately; debounce only artwork repainting.
        rail = 76 if event.width < 850 else 192
        pad = 24 if event.width < 850 else 32
        if self.layout_callback:
            self.layout_callback(event.width - pad, event.height - 74, rail + pad,
                                 event.height - 8, event.width - rail - pad * 2)
        if self._rendered_size is None:
            self.render(event.width, event.height)
            return
        if self.resize_job is not None:
            self.after_cancel(self.resize_job)
        self.resize_job = self.after(50, lambda: self.render(event.width, event.height))

    def text(self, x, y, value, size=11, color=None, bold=False, **options):
        options.setdefault("anchor", "w")
        return self.create_text(x, y, text=value, font=(self.family, size, "bold" if bold else "normal"),
                                fill=color or self.colors["text"], tags="chrome", **options)

    def rect(self, *coords, **options):
        return self.create_rectangle(*coords, tags="chrome", **options)

    def render(self, width, height):
        self.resize_job = None
        if width < 200 or height < 200:
            return
        self.delete("chrome")
        compact = width < 850
        rail = 76 if compact else 192
        pad = 24 if compact else 32
        left, right = rail + pad, width - pad
        colors = self.colors
        if self.photo is None:
            for i in range(64):
                self.rect(width * i / 64, 0, width * (i + 1) / 64 + 1, height,
                          fill=blend(colors["bg"], colors["selected"], i / 63), outline="")
            cx, cy = width * 0.77, height * 0.42
            radius = min(height * 0.25, width * 0.12)
            for factor in (1, 1.32, 1.62):
                r = radius * factor
                self.create_oval(cx - r, cy - r * 0.60, cx + r, cy + r * 0.60,
                                 outline=colors["button_edge"], width=1, tags="chrome")
            for dx, dy in ((-0.95, -0.18), (0.68, -0.42), (0.85, 0.34)):
                x, y = cx + radius * dx, cy + radius * dy
                self.create_oval(x - 3, y - 3, x + 3, y + 3, fill="#9ec4ef", outline="", tags="chrome")
        else:
            self.fit_cover(width - rail, height)
            self.create_image(rail, 0, image=self.cover, anchor="nw", tags=("chrome", "content-background"))
        self.rect(0, 0, rail, height, fill=colors["sidebar"], outline="")
        self.create_line(rail, 0, rail, height, fill=colors["border"], tags="chrome")
        if self.brand_icon is not None:
            self.create_image(38, 40, image=self.brand_icon, tags="chrome")
        else:
            rounded(self, 22, 24, 54, 56, radius=7, fill=colors["text"], outline="", tags="chrome")
            self.text(38, 40, "AI", size=11, color=colors["bg"], bold=True, anchor="center")
        if not compact:
            self.text(66, 40, "AIoT", size=17, bold=True)
        rounded(self, 12, 151, rail - 12, 211, radius=7, fill=colors["selected"], outline="", tags="chrome")
        self.rect(12, 169, 15, 193, fill=colors["accent"], outline="")
        if self.app_icon is not None:
            self.create_image(37, 181, image=self.app_icon, tags="chrome")
        else:
            self.rect(26, 169, 49, 192, fill="#3c465b", outline="")
            self.text(37, 181, "AI", size=8, bold=True, anchor="center")
        if not compact:
            self.text(59, 181, SIDEBAR_NAME, size=10, bold=True)

        self.message_item = self.text(left, height - 47, "", size=10, color=colors["muted"],
                                      width=max(120, right - left - 450))
        self.set_message(self.message)
        self.tag_lower("chrome")
        self._rendered_size = (width, height)
        if self.layout_callback:
            self.layout_callback(right, height - 74, left, height - 8, right - left)

    def fit_cover(self, width, height):
        """Fill the right pane; controls float over the dimmed artwork."""
        size = (max(1, width), max(1, height))
        if self._cover_size == size and self.cover is not None:
            return
        if self._source_pixels is None:
            raise image_component_error("没有读取到原始图片像素，已停止低画质降级。")
        try:
            from PIL import Image, ImageOps
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            artwork = ImageOps.fit(self._source_pixels.convert("RGBA"), size, method=resampling)
            base = Image.new("RGBA", size, self.colors["bg"])
            pixels = Image.alpha_composite(base, artwork).convert("RGB")
            pixels = Image.blend(base.convert("RGB"), pixels, 0.84 if self.theme == "light" else BACKGROUND_OPACITY)
            self.cover = image_photo(pixels, self)
        except ImportError as exc:
            raise image_component_error(exc) from exc
        self._cover_size = size

    def set_phase(self, phase):
        self.phase = phase

    def set_theme(self, theme):
        self.theme, self.colors = theme, palette(theme)
        self.configure(background=self.colors["bg"])
        self._cover_size = None
        if self.resize_job is not None:
            self.after_cancel(self.resize_job)
            self.resize_job = None
        self.render(*(self._rendered_size or (WINDOW_WIDTH, WINDOW_HEIGHT)))

    def set_message(self, message):
        self.message = message
        if self.message_item is not None:
            self.itemconfigure(self.message_item, text=message)

    def destroy(self):
        if self.resize_job is not None:
            self.after_cancel(self.resize_job)
        super().destroy()
