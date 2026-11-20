"""从终端启动摄像头窗口，显示钢管检测框和数量。"""

import sys

from detect import main as run_detection


def main(argv=None):
    options = sys.argv[1:] if argv is None else argv
    return run_detection(["--show", "--no-udp", "--conf", "0.25", *options], show_detection_text=False)


if __name__ == "__main__":
    raise SystemExit(main())
