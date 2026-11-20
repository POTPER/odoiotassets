"""Keep launched programs from inheriting the launcher's desktop identity."""
import os


LAUNCH_METADATA = ("DESKTOP_STARTUP_ID", "XDG_ACTIVATION_TOKEN", "GIO_LAUNCHED_DESKTOP_FILE",
                   "GIO_LAUNCHED_DESKTOP_FILE_PID", "BAMF_DESKTOP_FILE_HINT")


def child_environment(environment=None):
    result = dict(os.environ if environment is None else environment)
    for name in LAUNCH_METADATA:
        result.pop(name, None)
    return result


def configure_launcher_window(root):
    """An independent normal X11 window, not a tool/dialog in AIoT's group."""
    if root.tk.call("tk", "windowingsystem") == "x11":
        root.wm_attributes("-type", "normal")
        root.wm_transient("")
        root.wm_group("")
