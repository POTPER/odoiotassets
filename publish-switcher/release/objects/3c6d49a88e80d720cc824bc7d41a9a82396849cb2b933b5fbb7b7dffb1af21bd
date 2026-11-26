"""方案生成器兼容入口。

实施人员从完整 publish 生成资源仓库目录；转发到 publish_switcher.repositories.generate。
"""
import sys

from publish_switcher.repositories import generate as implementation


if __name__ == "__main__":
    raise SystemExit(implementation.main())


sys.modules[__name__] = implementation
