"""使用 YOLO26 二分类模型检测人员跌倒。"""

from fall_demo import run_demo


def main(argv=None):
    return run_demo("fall_2class_rk3588", ("non-fall", "fall"), "fall", argv)


if __name__ == "__main__":
    raise SystemExit(main())
