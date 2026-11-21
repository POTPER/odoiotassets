"""窗口与桌面图标。

加载包内 PNG 图标；运行时不依赖 Pillow 或网络。
"""
import logging
from pathlib import Path
from publish_switcher.common.paths import INSTALL_ROOT


ICON_DIRECTORY = INSTALL_ROOT / "icons"
WM_CLASS = "PublishSwitcher"


def load_icons(root):
    # Imported only by the GUI; SSH entry points remain usable without Tkinter.
    import tkinter as tk
    images = {}
    for size in (16, 32, 48, 64, 128, 256):
        try:
            path = ICON_DIRECTORY / "swicher-v10-{}.png".format(size)
            if not path.is_file():
                path = ICON_DIRECTORY / "publish-switcher-{}.png".format(size)
            images[size] = tk.PhotoImage(master=root, file=str(path))
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
