"""一键更新兼容入口。

旧代码「import unified_update」时指向 publish_switcher.updates.unified。
"""
import sys

from publish_switcher.updates import unified as implementation


sys.modules[__name__] = implementation
