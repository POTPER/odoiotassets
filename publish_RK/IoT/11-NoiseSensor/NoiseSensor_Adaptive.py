#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
import argparse
import math
import signal
import sys
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Event

from NoiseSensor_Teaching import (
    EXPERIMENT_FIELDS,
    MODULE_INDEX,
    CsvExperimentLog,
    SensorDataOutput,
    check_driver_file,
    connect_sensor,
    load_driver,
    read_noise,
    validate_experiment_info,
)

# ==================== 02 用户设置 ====================

# ==================== 考试任务：施工通道噪声自适应采样 ====================
# 某施工项目在“施工通道01”布置11号噪声传感器，平时每5秒记录一次读数。
# 当一条有效读数高于60 dB时，下一次起每1秒采样，以观察之后几秒的噪声变化。
# 快采期间连续3次有效读数等于或低于60 dB后，下一次起恢复5秒间隔。
# 读取失败时记录错误，恢复计数清零，并继续按当前模式采样。60 dB为课堂阈值。
#
# 请填写实验信息、配置采样参数，并编写自动切换逻辑。改变声环境，验证快采及恢复。
# 提交CSV和同次源码。从CSV各选一段慢采、快采记录，核对实际间隔，并解释快采记录到了哪些变化。

experiment_info = {
    "考试编号": "考号",
    "项目名称": "噪声自适应采样",
    "项目位置": "物联实训箱11",
}

# >>>>>>>>>>>>>>>>>>>> TODO 1：根据题面设置采样参数 >>>>>>>>>>>>>>>>>>>>
NOISE_TARGET_VALUE = 50        # 切换阈值，单位dB。
NORMAL_INTERVAL_SECONDS = 4    # 慢采间隔，秒/次。
FAST_INTERVAL_SECONDS = 2      # 快采间隔，秒/次。
RECOVERY_SAMPLES = 2           # 恢复慢采所需的连续正常读数数目。
# <<<<<<<<<<<<<<<<<<<< TODO：设置区结束 <<<<<<<<<<<<<<<<<<<<<<


# >>>>>>>>>>>>>>>>>>>> TODO 2：编写自动切换逻辑 >>>>>>>>>>>>>>>>>>>>
def next_sampling_mode(mode, consecutive_normal, decibel):
    """根据本次模式、此前连续正常次数和本次读数，决定下次采样模式。

    mode 为 NORMAL_MODE（慢采）或 FAST_MODE（快采）。decibel 为 None 表示读取失败。
    返回 (下次模式, 更新后的连续正常次数)。阈值和恢复次数使用上方的配置。
    """
    # 在这里实现题面中的切换、恢复和读取失败处理。
    return None  # 练习占位，CSV 会显示“切换逻辑待完成”。
# <<<<<<<<<<<<<<<<<<<< TODO：自动切换逻辑结束 <<<<<<<<<<<<<<<<<<<<<<


# ==================== 03 系统配置 ====================
SCRIPT_PATH = Path(__file__).resolve()
SAMPLE_COUNT = 12
NORMAL_MODE = "慢采"
FAST_MODE = "快采"
CSV_FIELDS = ("记录时间", *EXPERIMENT_FIELDS, "实验累计毫秒", "模块编号", "采样序号",
              "噪声读数(dB)", "切换阈值(dB)", "本次模式", "实际间隔(秒)", "判定",
              "连续正常次数", "下次模式", "下次设定间隔(秒)", "错误信息")


# ==================== 04 参数检查 ====================
@dataclass(frozen=True)
class SamplingSettings:
    threshold: float
    normal_interval: float
    fast_interval: float
    recovery_samples: int


def validate_settings(metadata, settings):
    validate_experiment_info(metadata)
    for name, value in (("NOISE_TARGET_VALUE", settings.threshold),
                        ("NORMAL_INTERVAL_SECONDS", settings.normal_interval),
                        ("FAST_INTERVAL_SECONDS", settings.fast_interval)):
        if type(value) not in (int, float) or not 0 < value < math.inf:
            raise ValueError(f"{name} 须为有限正数")
    if settings.fast_interval >= settings.normal_interval:
        raise ValueError("快采间隔须小于慢采间隔")
    if type(settings.recovery_samples) is not int or settings.recovery_samples <= 0:
        raise ValueError("恢复所需的连续正常次数须为正整数")
    check_driver_file()


# ==================== 05 采样、归档与上报 ====================
def run_sampling(driver, output, log, stop, settings, decide_next_mode):
    intervals = {NORMAL_MODE: settings.normal_interval, FAST_MODE: settings.fast_interval}
    mode = NORMAL_MODE
    consecutive_normal = failures = 0
    started = deadline = time.monotonic()
    previous_sample = None
    for number in range(1, SAMPLE_COUNT + 1):
        if stop.wait(max(0, deadline - time.monotonic())):
            raise KeyboardInterrupt
        sample_at = time.monotonic()
        elapsed_ms = round((sample_at - started) * 1000, 3)
        actual_interval = None if previous_sample is None else round(sample_at - previous_sample, 3)
        timestamp = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        error = ""
        try:
            decibel = read_noise(driver)
        except OSError as exc:
            decibel = None
            error = str(exc)
        else:
            try:
                output.publish(decibel, target=settings.threshold, interval=intervals[mode])
            except OSError as exc:
                error = f"JSON 保存或 UDP 上报失败，{exc}"

        decision = decide_next_mode(mode, consecutive_normal, decibel)
        if decision is None:
            next_mode = mode
            recorded_count = None
        else:
            if not isinstance(decision, tuple) or len(decision) != 2:
                raise ValueError("next_sampling_mode 须返回 (下次模式, 连续正常次数)")
            next_mode, consecutive_normal = decision
            if next_mode not in (NORMAL_MODE, FAST_MODE) or type(consecutive_normal) is not int or consecutive_normal < 0:
                raise ValueError("下次模式须为 NORMAL_MODE 或 FAST_MODE，连续正常次数须为非负整数")
            recorded_count = consecutive_normal
        if decibel is None:
            verdict = "读取失败"
        elif decision is None:
            verdict = "切换逻辑待完成"
        else:
            verdict = "偏高" if decibel > settings.threshold else "正常"
        next_interval = intervals[next_mode]
        log.write_row(timestamp, elapsed_ms, MODULE_INDEX, number, decibel, settings.threshold,
                      mode, actual_interval, verdict, recorded_count, next_mode, next_interval,
                      log.spreadsheet_text(error))
        failures += bool(error)
        reading = "" if decibel is None else f"{decibel} dB，"
        detail = f"，{error}" if error else ""
        print(f"{timestamp} 第 {number}/{SAMPLE_COUNT} 次，{mode}，{reading}{verdict}，"
              f"下次{next_mode} {next_interval} 秒{detail}", flush=True)

        mode, previous_sample = next_mode, sample_at
        deadline = sample_at + next_interval
        finished = time.monotonic()
        if finished > deadline:
            # 处理耗时已超过设定间隔，从本次处理结束后重新计时。
            deadline = finished + next_interval
    if stop.is_set():
        raise KeyboardInterrupt
    print(f"采样结束，共 {SAMPLE_COUNT} 次，其中 {failures} 次有读取或上报错误。")
    return int(bool(failures))


# ==================== 06 程序主流程与命令行入口 ====================
def run_experiment(metadata, settings, decide_next_mode, entry_path, output_root, stop):
    log = CsvExperimentLog(metadata, output_root, entry_path=entry_path, fields=CSV_FIELDS)
    driver = load_driver()
    output = SensorDataOutput()
    with ExitStack() as cleanup:
        cleanup.callback(output.close)
        connect_sensor(driver, cleanup, stop)
        return run_sampling(driver, output, log, stop, settings, decide_next_mode)


def launch(metadata, settings, decide_next_mode, entry_path):
    parser = argparse.ArgumentParser(description="施工通道噪声自适应采样")
    parser.add_argument("--check", action="store_true", help="检查用户设置与驱动文件")
    parser.add_argument("--output-dir", type=Path, help="成果根目录，默认为桌面/成果输出")
    args = parser.parse_args()
    try:
        validate_settings(metadata, settings)
        if args.check:
            print(f"静态检查通过，阈值 {settings.threshold} dB，慢采 {settings.normal_interval} 秒，"
                  f"快采 {settings.fast_interval} 秒，恢复次数设为 {settings.recovery_samples} 次。")
            print("请通过采样记录验证切换逻辑。")
            return 0
        stop = Event()
        previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
        try:
            return run_experiment(metadata, settings, decide_next_mode, entry_path, args.output_dir, stop)
        finally:
            signal.signal(signal.SIGINT, previous)
    except KeyboardInterrupt:
        print("采集已停止，已写入的记录保留。")
        return 130
    except (OSError, ValueError, AttributeError) as error:
        print(f"运行失败，{error}", file=sys.stderr, flush=True)
        return 1


# ==================== 07 程序启动 ====================
def main():
    settings = SamplingSettings(NOISE_TARGET_VALUE, NORMAL_INTERVAL_SECONDS,
                                FAST_INTERVAL_SECONDS, RECOVERY_SAMPLES)
    return launch(experiment_info, settings, next_sampling_mode, SCRIPT_PATH)


if __name__ == "__main__":
    sys.exit(main())
