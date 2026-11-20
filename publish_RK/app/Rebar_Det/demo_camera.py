"""从终端启动摄像头窗口，显示钢筋检测框和数量。"""

import sys

from detect import main as run_detection


def main(argv=None):
    options = list(sys.argv[1:] if argv is None else argv)
    if not {"-h", "--help", "--detail"}.intersection(options):
        print("钢筋计数\n  1. 普通模式\n  2. 精细模式（适合密集小钢筋，刷新较慢）\n  0. 退出")
        while True:
            try:
                choice = input("请选择模式，回车默认普通模式：").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if choice == "0":
                return 0
            if choice in ("", "1", "2"):
                if choice == "2":
                    options.append("--detail")
                break
            print("请输入 1、2 或 0。")
    return run_detection(["--show", "--no-udp", "--conf", "0.25", *options])


if __name__ == "__main__":
    raise SystemExit(main())
