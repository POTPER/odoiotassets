#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
import sys
from pathlib import Path

from NoiseSensor_Adaptive import FAST_MODE, NORMAL_MODE, SamplingSettings, launch


# ==================== 02 参考设置 ====================
experiment_info = {
    "考试编号": "教师参考",
    "项目名称": "施工通道噪声自适应采样",
    "项目位置": "施工通道01",
}

NOISE_TARGET_VALUE = 60
NORMAL_INTERVAL_SECONDS = 5
FAST_INTERVAL_SECONDS = 1
RECOVERY_SAMPLES = 3


# ==================== 03 自动切换逻辑 ====================
def next_sampling_mode(mode, consecutive_normal, decibel):
    if decibel is None:
        return mode, 0
    if decibel > NOISE_TARGET_VALUE:
        return FAST_MODE, 0
    if mode == NORMAL_MODE:
        return NORMAL_MODE, 0

    consecutive_normal += 1
    if consecutive_normal >= RECOVERY_SAMPLES:
        return NORMAL_MODE, consecutive_normal
    return FAST_MODE, consecutive_normal


# ==================== 04 程序启动 ====================
def main():
    settings = SamplingSettings(NOISE_TARGET_VALUE, NORMAL_INTERVAL_SECONDS,
                                FAST_INTERVAL_SECONDS, RECOVERY_SAMPLES)
    return launch(experiment_info, settings, next_sampling_mode, Path(__file__).resolve())


if __name__ == "__main__":
    sys.exit(main())
