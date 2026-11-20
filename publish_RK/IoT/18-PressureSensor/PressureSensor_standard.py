#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""压力传感器标准实训入口：ADC均值、两点线性估算及完整成果记录。"""
import argparse
import csv
import ctypes
import json
import math
import os
import re
import shutil
import signal
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

# ==================== 01 教学任务与用户设置 ====================
# TODO：填写实验信息，将采集间隔改为2秒，按教师任务填写目标值及最大值。
# 空载、轻压、逐步加压并释放，至少观察10次有效采样。
# 原厂两点换算仅为质量估算，不是压力单位Pa，也未执行去皮。
# 提交同次CSV、归档源码和现场观察记录。按 Ctrl+C 结束。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "压力传感器模块",
    "项目位置": "物联实训箱18",
}
SLEEP_TIME = 1
PRESSURE_TARGET_VALUE = 0
PRESSURE_MAXIMUM_VALUE = 0  # 0表示未设置；非零时统计严格大于最大值的采样次数

# ==================== 02 系统配置 ====================
MODULE_INDEX = 15  # 沿用原厂地址，与目录序号18不同，须核对实训箱
ADC_CHANNEL = 0  # 原厂通道0：GPIO32；通道1：GPIO33
BIT_WIDTH = 3  # 原厂枚举3：12位
SAMPLE_COUNT = 3
SAMPLE_DELAY = 0.02
DEAD_ZONE = 0.5
CALIBRATION_ADC_1 = 3100
CALIBRATION_MASS_1 = 20
CALIBRATION_ADC_2 = 0
CALIBRATION_MASS_2 = 2000
SCAN_WAIT_SECONDS = 2
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000

# ==================== 03 路径与配置检查 ====================
def safe_path_component(text):
    # 清理路径分隔符和文件名非法字符，避免姓名或位置变成其他目录。
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip(' .')
    cleaned = cleaned[:80].rstrip(' .') or "未命名"
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if cleaned.split('.')[0].upper() in reserved:
        cleaned = "_" + cleaned
    return cleaned


def find_desktop():
    # 使用运行程序的当前用户桌面，支持 Linux 中文和自定义桌面路径。
    home = Path.home()
    if os.name == "nt":
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
            return Path(os.path.expandvars(value))
        except OSError:
            pass
    else:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        try:
            config = (config_home / "user-dirs.dirs").read_text(encoding="utf-8")
            for line in config.splitlines():
                if line.strip().startswith("XDG_DESKTOP_DIR="):
                    value = line.split("=", 1)[1].strip().strip('"')
                    value = value.replace("${HOME}", str(home)).replace("$HOME", str(home))
                    desktop = Path(value).expanduser()
                    if desktop.is_absolute():
                        return desktop
        except OSError:
            pass
    if (home / "桌面").is_dir():
        return home / "桌面"
    return home / "Desktop"


def validate_settings():
    if isinstance(SLEEP_TIME, bool) or not isinstance(SLEEP_TIME, (int, float)) or not math.isfinite(SLEEP_TIME) or SLEEP_TIME <= 0:
        raise ValueError("SLEEP_TIME 必须为有限正数")
    for value in (PRESSURE_TARGET_VALUE, PRESSURE_MAXIMUM_VALUE):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("压力目标值和最大值必须为有限非负数")
    if not isinstance(experiment_info, dict) or not experiment_info:
        raise ValueError("experiment_info 必须为非空字典")
    for key, value in experiment_info.items():
        if not isinstance(key, str) or not key.strip() or key in Recorder.FIELDS:
            raise ValueError(f"实验字段为空或与系统列重名：{key}")
        if not isinstance(value, str):
            raise ValueError(f"实验信息必须为字符串：{key}")
    for name in ("UdpPackage.py", "libSmartSensorDriver.so"):
        if not (SCRIPT_DIRECTORY / name).is_file():
            raise ValueError(f"缺少配套文件：{name}")
    for name, value in (("MODULE_INDEX", MODULE_INDEX), ("SAMPLE_COUNT", SAMPLE_COUNT)):
        if type(value) is not int or value <= 0:
            raise ValueError(f"{name}必须为正整数")
    if type(ADC_CHANNEL) is not int or ADC_CHANNEL not in (0, 1):
        raise ValueError("ADC_CHANNEL必须为0或1")
    if type(BIT_WIDTH) is not int or BIT_WIDTH not in range(5):
        raise ValueError("BIT_WIDTH必须为0~4的整数枚举")
    for value in (SAMPLE_DELAY, DEAD_ZONE, CALIBRATION_ADC_1, CALIBRATION_ADC_2,
                  CALIBRATION_MASS_1, CALIBRATION_MASS_2, SCAN_WAIT_SECONDS):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("采样等待、死区、标定点与扫描等待须为有限非负数")
    if CALIBRATION_ADC_1 == CALIBRATION_ADC_2:
        raise ValueError("两个标定ADC值不能相同")


def compute_reading(adc):
    # ADC单位未由原厂接口确认，保留原始数值，不标为V或mV。
    if not min(CALIBRATION_ADC_1, CALIBRATION_ADC_2) <= adc <= max(CALIBRATION_ADC_1, CALIBRATION_ADC_2):
        return None
    mass = CALIBRATION_MASS_1 + (adc - CALIBRATION_ADC_1) * (
        CALIBRATION_MASS_2 - CALIBRATION_MASS_1) / (CALIBRATION_ADC_2 - CALIBRATION_ADC_1)
    return round(0 if abs(mass) < DEAD_ZONE else mass, 2)


def load_driver():
    driver = ctypes.CDLL(str(SCRIPT_DIRECTORY / "libSmartSensorDriver.so"))
    signatures = {
        "SmartSensorLibInit": ([], None), "SmartSensorLibUnInit": ([], None),
        "startScanSensors": ([], ctypes.c_int),
        "isModReady": ([ctypes.c_int], ctypes.c_int),
        "connectToMod": ([ctypes.c_int], ctypes.c_int),
        "disconnectToMod": ([ctypes.c_int], ctypes.c_int),
        "AdcInit": ([ctypes.c_int] * 3, ctypes.c_int),
        "AdcUnInit": ([ctypes.c_int] * 2, ctypes.c_int),
        "AdcRead": ([ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(driver, name)
        function.argtypes, function.restype = arguments, result
    return driver


def read_adc(driver):
    readings = []
    for _ in range(SAMPLE_COUNT):
        value = ctypes.c_int()
        result = driver.AdcRead(MODULE_INDEX, ADC_CHANNEL, ctypes.byref(value))
        if result < 0:
            raise RuntimeError(f"ADC读取失败，返回值={result}；已读{len(readings)}/{SAMPLE_COUNT}次，本组作废")
        readings.append(value.value)
        time.sleep(SAMPLE_DELAY)
    return sum(readings) / len(readings)


# ==================== 04 完整历史与源码归档 ====================
class Recorder:
    FIELDS = ("记录时间", "采样序号", "模块编号", "ADC均值", "质量估算(g)", "量程状态",
              "压力目标值(g)", "压力最大值(g)", "超限累计次数", "采集间隔(秒)", "记录类型", "结果", "错误信息")

    def __init__(self, root=None):
        self.exceeding = 0
        self.metadata = dict(experiment_info)
        self.fields = [*self.metadata, *self.FIELDS]
        person = safe_path_component(self.metadata.get("考试编号", "未填写"))
        project = safe_path_component(self.metadata.get("项目名称", "压力传感器模块"))
        folder = (Path(root).expanduser() if root else find_desktop() / "成果输出") / person / project
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.path = folder / f"{project}_{person}_{stamp}.csv"
        with self.path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(self.fields)
        shutil.copyfile(Path(__file__).resolve(), self.path.with_suffix(".py"))
        print(f"成果位置：{self.path}", flush=True)

    def record(self, kind, result, sequence=0, values=("", "", ""), error=""):
        values = [datetime.now().isoformat(timespec="milliseconds"), sequence, MODULE_INDEX,
                  *values, PRESSURE_TARGET_VALUE, PRESSURE_MAXIMUM_VALUE, self.exceeding,
                  SLEEP_TIME, kind, result, str(error)]
        row = [*self.metadata.values(), *values]
        # 避免文本字段被表格软件当作公式执行。
        row = ["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row]
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(row)


# ==================== 05 原JSON及UDP协议 ====================
class Reporter:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packet_id = 0
        self.history = []
        try:
            saved = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, list):
                self.history = saved[-5:]
        except (OSError, ValueError):
            pass

    def send(self, value, online, exceeding=0):
        from UdpPackage import UdpPackage
        status = int(online)
        self.history.append({
            "Name": "LiftingLoadSensor", "Answer": {"LiftingLoadSensor": value},
            "Target_Value": {"LiftingLoadSensor": PRESSURE_TARGET_VALUE},
            "Maximum_Value": {"LiftingLoadSensor": PRESSURE_MAXIMUM_VALUE},
            "Exceeding_Limit_Times": exceeding,
            "Output_Frequency": f"{SLEEP_TIME} s/次",
            "Status": {"Connection_Status": status, "Communication_Status": status, "Output_Status": status},
        })
        self.history = self.history[-5:]
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(json.dumps(self.history, indent=4), encoding="utf-8")
        data = json.dumps(self.history).encode("utf-8")
        self.packet_id = self.packet_id % 0xffffffff + 1
        count = math.ceil(len(data) / UDP_CHUNK_SIZE)
        for index in range(count):
            chunk = data[index * UDP_CHUNK_SIZE:(index + 1) * UDP_CHUNK_SIZE]
            packet = UdpPackage(self.packet_id, count, index, len(chunk), chunk)
            self.socket.sendto(packet.toNetBytes(), UDP_DESTINATION)


# ==================== 06 硬件采集与资源释放 ====================
def run(recorder):
    driver = reporter = None
    library_attempted = connection_attempted = adc_attempted = False
    failed = False
    sequence = 0

    def record(*args, **kwargs):
        # 磁盘写入失败也不能阻止后续硬件清理。
        nonlocal failed
        try:
            recorder.record(*args, **kwargs)
        except Exception as error:
            failed = True
            print(f"CSV记录失败：{error}", file=sys.stderr)

    def report(value, online):
        nonlocal failed
        if reporter:
            try:
                reporter.send(value, online, recorder.exceeding)
            except Exception as error:
                failed = True
                record("上报", "失败", sequence, error=error)
                print(f"JSON/UDP上报失败：{error}", file=sys.stderr)

    try:
        reporter = Reporter()
        driver = load_driver()
        library_attempted = True
        driver.SmartSensorLibInit()
        if driver.startScanSensors() < 0:
            raise RuntimeError("扫描模块失败")
        time.sleep(SCAN_WAIT_SECONDS)
        if driver.isModReady(MODULE_INDEX) != 1:
            raise RuntimeError(f"模块{MODULE_INDEX}未在线")
        connection_attempted = True
        if driver.connectToMod(MODULE_INDEX) <= 0:
            raise RuntimeError("连接模块失败")
        adc_attempted = True
        if driver.AdcInit(MODULE_INDEX, ADC_CHANNEL, BIT_WIDTH) < 0:
            raise RuntimeError("ADC初始化失败")
        record("初始化", "成功")
        while True:
            sequence += 1
            adc = read_adc(driver)
            mass = compute_reading(adc)
            if mass is None:
                record("采样", "超出标定区间", sequence, (adc, "", "区间外"))
                report(0, False)
                print(f"第{sequence}次：ADC均值={adc:.2f}，超出标定区间", flush=True)
            else:
                if PRESSURE_MAXIMUM_VALUE > 0 and mass > PRESSURE_MAXIMUM_VALUE:
                    recorder.exceeding += 1
                recorder.record("采样", "成功", sequence, (adc, mass, "区间内"))
                report(mass, True)
                print(f"第{sequence}次：ADC均值={adc:.2f}，质量估算={mass} g", flush=True)
            time.sleep(SLEEP_TIME)
    except KeyboardInterrupt:
        record("停止", "用户中断", sequence)
    except Exception as error:
        failed = True
        record("运行", "失败", sequence, error=error)
        print(f"运行失败：{error}", file=sys.stderr)
    finally:
        report(0, False)
        for label, action in (
            ("释放ADC", (lambda: driver.AdcUnInit(MODULE_INDEX, ADC_CHANNEL)) if adc_attempted else None),
            ("断开模块", (lambda: driver.disconnectToMod(MODULE_INDEX)) if connection_attempted else None),
            ("注销驱动库", driver.SmartSensorLibUnInit if library_attempted else None),
            ("关闭UDP", reporter.socket.close if reporter else None),
        ):
            if action:
                try:
                    result = action()
                    if isinstance(result, int) and result < 0:
                        raise RuntimeError(f"驱动返回 {result}")
                except Exception as error:
                    failed = True
                    record(label, "失败", sequence, error=error)
                    print(f"{label}失败：{error}", file=sys.stderr)
        record("结束", "失败" if failed else "完成", sequence)
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description="压力传感器标准实训程序")
    parser.add_argument("--check", action="store_true", help="仅检查配置、语法和配套文件，不加载驱动")
    parser.add_argument("--output-root", help="指定成果根目录，默认当前用户桌面/成果输出")
    args = parser.parse_args()
    try:
        validate_settings()
        if args.check:
            for name in (Path(__file__).name, "UdpPackage.py"):
                path = SCRIPT_DIRECTORY / name
                compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
            print("静态检查通过；未加载动态库，未验证硬件、网络接收或实测精度。")
            return 0
        def stop_on_signal(signum, frame):
            raise KeyboardInterrupt

        previous = signal.signal(signal.SIGTERM, stop_on_signal)
        try:
            return run(Recorder(args.output_root))
        finally:
            signal.signal(signal.SIGTERM, previous)
    except Exception as error:
        print(f"程序失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
