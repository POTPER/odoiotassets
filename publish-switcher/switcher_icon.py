"""Bundled desktop/window branding. No Pillow or network dependency at runtime."""
import logging
from pathlib import Path


ICON_DIRECTORY = Path(__file__).resolve().parent / "icons"
WM_CLASS = "PublishSwitcher"


def load_icons(root):
    # Imported only by the GUI; SSH entry points remain usable without Tkinter.
    import tkinter as tk
    images = {}
    for size in (16, 32, 48, 64, 128, 256):
        try:
            images[size] = tk.PhotoImage(master=root, file=str(
                ICON_DIRECTORY / "publish-switcher-{}.png".format(size)))
        except (OSError, tk.TclError) as exc:
            logging.getLogger("publish-switcher").warning("无法加载 %s px 图标：%s", size, exc)
    if images:
        try:
            root.iconphoto(True, *images.values())
        except tk.TclError as exc:
            logging.getLogger("publish-switcher").warning("无法设置窗口图标：%s", exc)
    # Tk photos must stay referenced for the lifetime of the window.
    root._switcher_icons = images
    return images
