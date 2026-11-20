#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""激光测距标准实训入口；原厂驱动名称沿用 VL53L0X，实际型号须板端核对。"""
import argparse
import csv
import json
import math
import os
import re
import shutil
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

# ==================== 01 教学任务与用户设置 ====================
# 在物联实训箱上完成距离采集调试，改变被测物距离，观察读数变化。
# TODO：填写个人信息；将采集间隔调整为2秒，目标距离设置为300 mm。
# 目标值仅用于记录和上报，不控制报警。至少观察10次采样后按 Ctrl+C 结束。
# 分别观察正常距离、过近和超范围场景，提交同次CSV与自动归档的源码。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "激光测距模块",
    "项目位置": "物联实训箱04",
}
SLEEP_TIME = 1           # 两次采集之间的等待时间，秒
LASER_TARGET_VALUE = 50 # 目标距离，mm；按任务要求修改

# ==================== 02 系统配置 ====================
MODULE_INDEX = 4
SCL_PIN, SDA_PIN = 22, 23
I2C_ADDRESS = 0x29
I2C_FREQUENCY = 400000
DISTANCE_MIN, DISTANCE_MAX = 50, 2000  # 有效区间 [50, 2000)，mm
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
    if isinstance(LASER_TARGET_VALUE, bool) or not isinstance(LASER_TARGET_VALUE, (int, float)) or not math.isfinite(LASER_TARGET_VALUE) or not DISTANCE_MIN <= LASER_TARGET_VALUE < DISTANCE_MAX:
        raise ValueError("目标距离必须在 [50, 2000) mm 内")
    if not isinstance(experiment_info, dict) or not experiment_info:
        raise ValueError("experiment_info 必须为非空字典")
    for key, value in experiment_info.items():
        if not isinstance(key, str) or not key.strip() or key in Recorder.FIELDS:
            raise ValueError(f"实验字段为空或与系统列重名：{key}")
        if not isinstance(value, str):
            raise ValueError(f"实验信息必须为字符串：{key}")
    for name in ("SensorModule.py", "LaserSensor.py", "UdpPackage.py", "libSmartSensorDriver.so"):
        if not (SCRIPT_DIRECTORY / name).is_file():
            raise ValueError(f"缺少配套文件：{name}")


def classify_distance(raw):
    if raw is None or raw == -1:
        raise ValueError("传感器读取失败")
    if not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise ValueError(f"距离格式无效：{raw!r}")
    if raw < DISTANCE_MIN or raw >= DISTANCE_MAX:
        return 0, "超出有效范围"
    return raw, "有效"


# ==================== 04 完整历史与源码归档 ====================
class Recorder:
    FIELDS = ("记录时间", "采样序号", "模块编号", "原始距离(mm)", "上报距离(mm)",
              "目标距离(mm)", "采集间隔(秒)", "记录类型", "结果", "错误信息")

    def __init__(self, root=None):
        self.metadata = dict(experiment_info)
        self.fields = [*self.metadata, *self.FIELDS]
        person = safe_path_component(self.metadata.get("考试编号", "未填写"))
        project = safe_path_component(self.metadata.get("项目名称", "激光测距模块"))
        folder = (Path(root).expanduser() if root else find_desktop() / "成果输出") / person / project
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.path = folder / f"{project}_{person}_{stamp}.csv"
        with self.path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(self.fields)
        shutil.copyfile(Path(__file__).resolve(), self.path.with_suffix(".py"))
        print(f"成果位置：{self.path}", flush=True)

    def record(self, kind, result, sequence=0, raw="", distance="", error=""):
        values = [datetime.now().isoformat(timespec="milliseconds"), sequence, MODULE_INDEX,
                  raw, distance, LASER_TARGET_VALUE, SLEEP_TIME, kind, result, str(error)]
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

    def send(self, distance, online):
        from UdpPackage import UdpPackage
        status = int(online)
        self.history.append({
            "Name": "LaserSensor", "Answer": {"distance_mm": distance},
            "Target_Value": {"distance_mm": LASER_TARGET_VALUE},
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
    modules = tof = reporter = None
    connection_attempted = False
    failed = False
    sequence = 0
    previous_directory = Path.cwd()

    def report(distance, online):
        nonlocal failed
        if reporter:
            try:
                reporter.send(distance, online)
            except Exception as error:
                failed = True
                recorder.record("上报", "失败", sequence, error=error)
                print(f"JSON/UDP上报失败：{error}", file=sys.stderr)

    try:
        reporter = Reporter()
        # 原厂封装按当前工作目录加载动态库，仅在实际运行时导入。
        os.chdir(SCRIPT_DIRECTORY)
        from SensorModule import SensorModule
        from LaserSensor import LaserSensor
        modules = SensorModule()
        if modules.startScanSensors() < 0:
            raise RuntimeError("扫描模块失败")
        time.sleep(SCAN_WAIT_SECONDS)
        if modules.isModReady(MODULE_INDEX) != 1:
            raise RuntimeError("模块4未在线")
        connection_attempted = True
        if modules.modConnect(MODULE_INDEX) <= 0:
            raise RuntimeError("连接模块失败")
        tof = LaserSensor(MODULE_INDEX, SCL_PIN, SDA_PIN, I2C_ADDRESS, I2C_FREQUENCY)
        tof.init()
        if tof.begin() != 1:
            raise RuntimeError("激光传感器初始化失败，请核对实际型号与配套驱动")
        recorder.record("初始化", "成功")
        while True:
            sequence += 1
            raw = tof.getDistance()
            distance, result = classify_distance(raw)
            recorder.record("采样", result, sequence, raw, distance)
            print(f"第{sequence}次：原始={raw} mm，上报={distance} mm，{result}", flush=True)
            report(distance, True)
            time.sleep(SLEEP_TIME)
    except KeyboardInterrupt:
        recorder.record("停止", "用户中断", sequence)
    except Exception as error:
        failed = True
        recorder.record("运行", "失败", sequence, error=error)
        print(f"运行失败：{error}", file=sys.stderr)
    finally:
        report(0, False)
        for label, action in (
            ("释放I2C", tof.uninit if tof else None),
            ("断开模块", (lambda: modules.modDisconnect(MODULE_INDEX)) if modules and connection_attempted else None),
            ("注销驱动库", modules.uninit if modules else None),
            ("关闭UDP", reporter.socket.close if reporter else None),
        ):
            if action:
                try:
                    result = action()
                    if isinstance(result, int) and result < 0:
                        raise RuntimeError(f"驱动返回 {result}")
                except Exception as error:
                    failed = True
                    recorder.record(label, "失败", sequence, error=error)
                    print(f"{label}失败：{error}", file=sys.stderr)
    os.chdir(previous_directory)
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description="激光测距标准实训程序")
    parser.add_argument("--check", action="store_true", help="仅检查配置、语法和配套文件，不加载驱动")
    parser.add_argument("--output-root", help="指定成果根目录，默认当前用户桌面/成果输出")
    args = parser.parse_args()
    try:
        validate_settings()
        if args.check:
            for name in (Path(__file__).name, "SensorModule.py", "LaserSensor.py", "UdpPackage.py"):
                path = SCRIPT_DIRECTORY / name
                compile(path.read_text(encoding="utf-8-sig"), str(path), "exec")
            print("静态检查通过；未加载动态库，未验证硬件、网络接收或实测精度。")
            return 0
        return run(Recorder(args.output_root))
    except Exception as error:
        print(f"程序失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
