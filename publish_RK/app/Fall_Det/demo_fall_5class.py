"""使用 YOLO26 五分类模型检测人员跌倒。"""

from fall_demo import run_demo


def main(argv=None):
    return run_demo(
        "fall_5class_rk3588",
        ("Walking", "Sleeping", "falling", "Standing", "Sitting"),
        "falling",
        argv,
    )


if __name__ == "__main__":
    raise SystemExit(main())
