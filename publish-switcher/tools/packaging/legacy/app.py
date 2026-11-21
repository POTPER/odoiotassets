"""图形界面入口（兼容旧安装）。

转发到 publish_switcher.gui.app；直接运行本文件等价于打开 gui。
"""
import sys

from publish_switcher.gui import app as implementation


if __name__ == "__main__":
    from publish_switcher.cli.main import main
    raise SystemExit(main(["gui"]))


sys.modules[__name__] = implementation
