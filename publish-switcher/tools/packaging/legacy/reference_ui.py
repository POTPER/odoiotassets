"""参考风格控件兼容入口。

转发到 publish_switcher.gui.widgets.reference。
"""
import sys

from publish_switcher.gui.widgets import reference as implementation


sys.modules[__name__] = implementation
