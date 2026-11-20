#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""激光测距标准实训入口；原厂驱动名称沿用 VL53L0X，实际型号须板端核对。"""
import argparse
import csv
import ctypes
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
# 完成空气颗粒物采集，观察 PM2.5、PM10 与估算 TSP。
# TODO：填写实验信息，将采集间隔改为2秒，三个目标值按教师任务设置。
# 目标值仅记录和上报，不用于报警或空气质量等级判定。
# 至少观察10次采样，按 Ctrl+C 结束，提交同次 CSV 与归档源码。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "空气质量模块",
    "项目位置": "物联实训箱14",
}
SLEEP_TIME = 1
PM25_TARGET_VALUE = 0
PM10_TARGET_VALUE = 0
TSP_TARGET_VALUE = 0

# ==================== 02 系统配置 ====================
MODULE_INDEX = 14
COM_INDEX, TX_PIN, RX_PIN = 2, 22, 23
READ_TIMEOUT = 5  # 秒，原厂接口使用整数
TSP_FACTOR = 1.2  # 沿用原厂估算系数，TSP 非独立实测值
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
    for value in (PM25_TARGET_VALUE, PM10_TARGET_VALUE, TSP_TARGET_VALUE):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError("颗粒物目标值必须为有限非负数")
    if not isinstance(experiment_info, dict) or not experiment_info:
        raise ValueError("experiment_info 必须为非空字典")
    for key, value in experiment_info.items():
        if not isinstance(key, str) or not key.strip() or key in Recorder.FIELDS:
            raise ValueError(f"实验字段为空或与系统列重名：{key}")
        if not isinstance(value, str):
            raise ValueError(f"实验信息必须为字符串：{key}")
    for name in ("SensorModule.py", "AirQualitySensor.py", "RS232Module.py", "UdpPackage.py", "libSmartSensorDriver.so"):
        if not (SCRIPT_DIRECTORY / name).is_file():
            raise ValueError(f"缺少配套文件：{name}")


def exchange(sensor, command):
    send = (ctypes.c_ubyte * len(command))(*command)
    recv = (ctypes.c_ubyte * 32)()
    count = sensor.SendHexDataAndReadData(send, len(command), recv, len(recv), READ_TIMEOUT)
    if count <= 0 or count > len(recv):
        raise RuntimeError(f"串口读取失败，返回值={count}")
    return bytes(recv[:count])


def parse_reading(frame):
    # 原厂按偏移6~9解析；尚无协议手册，不猜测帧头或校验算法。
    if len(frame) < 10:
        raise ValueError(f"环境数据回包不足10字节：{len(frame)}")
    pm25 = (frame[6] << 8) | frame[7]
    pm10 = (frame[8] << 8) | frame[9]
    return pm25, pm10, round(pm10 * TSP_FACTOR, 1)


# ==================== 04 完整历史与源码归档 ====================
class Recorder:
    FIELDS = ("记录时间", "采样序号", "模块编号", "PM2.5", "PM10", "TSP估算值",
              "PM2.5目标", "PM10目标", "TSP目标", "采集间隔(秒)", "记录类型", "结果", "错误信息")

    def __init__(self, root=None):
        self.metadata = dict(experiment_info)
        self.fields = [*self.metadata, *self.FIELDS]
        person = safe_path_component(self.metadata.get("考试编号", "未填写"))
        project = safe_path_component(self.metadata.get("项目名称", "空气质量模块"))
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
                  *values, PM25_TARGET_VALUE, PM10_TARGET_VALUE, TSP_TARGET_VALUE,
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

    def send(self, values, online):
        from UdpPackage import UdpPackage
        status = int(online)
        self.history.append({
            "Name": "AirQuality", "Answer": dict(zip(("PM2.5_value", "PM10_value", "TSP_value"), values)),
            "Target_Value": {"PM2.5_value": PM25_TARGET_VALUE, "PM10_value": PM10_TARGET_VALUE, "TSP_value": TSP_TARGET_VALUE},
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

    def report(values, online):
        nonlocal failed
        if reporter:
            try:
                reporter.send(values, online)
            except Exception as error:
                failed = True
                recorder.record("上报", "失败", sequence, error=error)
                print(f"JSON/UDP上报失败：{error}", file=sys.stderr)

    try:
        reporter = Reporter()
        # 原厂封装按当前工作目录加载动态库，仅在实际运行时导入。
        os.chdir(SCRIPT_DIRECTORY)
        from SensorModule import SensorModule
        from AirQualitySensor import AirQualitySensor
        modules = SensorModule()
        if modules.startScanSensors() < 0:
            raise RuntimeError("扫描模块失败")
        time.sleep(SCAN_WAIT_SECONDS)
        if modules.isModReady(MODULE_INDEX) != 1:
            raise RuntimeError("模块14未在线")
        connection_attempted = True
        if modules.modConnect(MODULE_INDEX) <= 0:
            raise RuntimeError("连接模块失败")
        tof = AirQualitySensor(MODULE_INDEX, COM_INDEX, TX_PIN, RX_PIN)
        tof.init()
        exchange(tof, (0xff, 0x01, 0x03, 0x02, 0, 0, 0, 0, 0x05))
        recorder.record("初始化", "成功")
        while True:
            sequence += 1
            frame = exchange(tof, (0xff, 0x01, 0x07, 0x01, 0, 0, 0, 0, 0x07))
            values = parse_reading(frame)
            recorder.record("采样", "成功", sequence, values)
            print(f"第{sequence}次：PM2.5={values[0]}，PM10={values[1]}，TSP估算={values[2]}", flush=True)
            report(values, True)
            time.sleep(SLEEP_TIME)
    except KeyboardInterrupt:
        recorder.record("停止", "用户中断", sequence)
    except Exception as error:
        failed = True
        recorder.record("运行", "失败", sequence, error=error)
        print(f"运行失败：{error}", file=sys.stderr)
    finally:
        report((0, 0, 0), False)
        for label, action in (
            ("释放串口", tof.uninit if tof else None),
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
    parser = argparse.ArgumentParser(description="空气质量标准实训程序")
    parser.add_argument("--check", action="store_true", help="仅检查配置、语法和配套文件，不加载驱动")
    parser.add_argument("--output-root", help="指定成果根目录，默认当前用户桌面/成果输出")
    args = parser.parse_args()
    try:
        validate_settings()
        if args.check:
            for name in (Path(__file__).name, "SensorModule.py", "AirQualitySensor.py", "RS232Module.py", "UdpPackage.py"):
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
