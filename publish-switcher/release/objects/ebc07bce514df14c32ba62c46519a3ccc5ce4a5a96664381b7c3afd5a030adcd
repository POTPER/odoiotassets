"""IoT Demo 运行器兼容入口。

转发到 publish_switcher.demo.runner；也可 python3 iot_runner.py 直接跑任务菜单。
"""
import sys

from publish_switcher.demo import runner as implementation


if __name__ == "__main__":
    raise SystemExit(implementation.main())


sys.modules[__name__] = implementation
