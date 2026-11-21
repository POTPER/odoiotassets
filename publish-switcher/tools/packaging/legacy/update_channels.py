"""更新通道兼容入口。

转发到 publish_switcher.updates.channels。
"""
import sys

from publish_switcher.updates import channels as implementation


sys.modules[__name__] = implementation
