"""权限预设兼容入口。

转发到 publish_switcher.sync.permissions。
"""
import sys

from publish_switcher.sync import permissions as implementation


if __name__ == "__main__":
    raise SystemExit(implementation.main())


sys.modules[__name__] = implementation
