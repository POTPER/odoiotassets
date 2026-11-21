"""命令行主入口（兼容旧安装）。

设备上常用：python3 switcher.py gui
本文件把调用转发到 publish_switcher.cli.main，并保持旧的 import switcher 可用。
"""
import sys

from publish_switcher.cli import main as implementation


if __name__ == "__main__":
    raise SystemExit(implementation.main())


sys.modules[__name__] = implementation
