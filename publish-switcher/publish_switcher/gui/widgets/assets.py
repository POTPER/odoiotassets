"""界面插画资源。

加载包内生成的 PNG（侧栏、更新页装饰等）；仅依赖 Tk 的 PNG 支持。
"""
import logging
import math
from pathlib import Path
from publish_switcher.common.paths import INSTALL_ROOT


ASSET_DIRECTORY = INSTALL_ROOT / "assets/ui"


def asset(widget, name, cover=None):
    import tkinter as tk
    root = widget._root()
    cache = getattr(root, "_swicher_artwork", None)
    if cache is None:
        cache = root._swicher_artwork = {}
    if name not in cache:
        try:
            cache[name] = tk.PhotoImage(master=widget, file=str(ASSET_DIRECTORY / name))
        except (OSError, tk.TclError) as exc:
            logging.getLogger("publish-switcher").warning("界面图片未加载，使用基本绘制：%s；%s", name, exc)
            cache[name] = None
    source = cache[name]
    if source is None or cover is None:
        return source
    width, height = cover
    zoom = max(1, int(math.ceil(max(width/source.width(), height/source.height()))))
    shrink = max(1, min(source.width()*zoom//max(1, width), source.height()*zoom//max(1, height)))
    key = (name, zoom, shrink)
    if key not in cache:
        # Bound background variants to the current zoom/shrink recipe.
        for previous in list(cache):
            if isinstance(previous, tuple) and previous[0] == name:
                del cache[previous]
        image = source.zoom(zoom) if zoom > 1 else source
        cache[key] = image.subsample(shrink) if shrink > 1 else image
    return cache[key]
