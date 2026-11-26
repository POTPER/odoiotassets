"""Software icon and stable window class shared with the desktop launcher."""
from publish_switcher.common.paths import INSTALL_ROOT

WM_CLASS = "PublishSwitcher"


def set_window_icon(root):
    from tkinter import PhotoImage

    images = [PhotoImage(master=root, file=str(INSTALL_ROOT / "icons" / f"swicher-{size}.png"))
              for size in (16, 32, 48, 64, 128, 256)]
    root.iconphoto(True, *images)
    root._software_icons = images
