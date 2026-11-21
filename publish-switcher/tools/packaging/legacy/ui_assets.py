"""界面插画兼容入口。

转发到 publish_switcher.gui.widgets.assets。
"""
import sys

from publish_switcher.gui.widgets import assets as implementation


sys.modules[__name__] = implementation
