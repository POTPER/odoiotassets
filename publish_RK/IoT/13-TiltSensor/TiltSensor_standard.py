#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==================== 教学任务 ====================
# 在设备管理区完成倾角监测调试：启动时保持传感器静止，随后缓慢改变倾角。
# TODO：填写 experiment_info；将采集间隔设为2秒，Y轴目标偏角设为50度。
# 观察归零、正向倾斜、反向倾斜及回到初始位置，至少采集10次后按 Ctrl+C 结束。
# 目标值仅用于记录与上报，不控制报警；默认参数可运行。
# 提交同次CSV、自动归档源码和现场观察记录。

# ==================== 01 标准库与用户设置 ====================
import argparse
import csv
import ctypes
import json
import math
import os
import re
import signal
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

experiment_info = {
    "姓名/小组": "任务小组",
    "学号": "",
    "任务项目": "倾角传感器模块",
    "任务位置": "物联实训箱13",
}
SLEEP_TIME = 1              # 每次采集后的等待时间，秒
ANGLE_Y_TARGET_VALUE = 30  # Y轴目标偏角，度；按题面修改

# ==================== 02 驱动与通信配置 ====================
MODULE_INDEX = 13
SCL_PIN, SDA_PIN = 23, 22
I2C_ADDRESS, I2C_FREQUENCY = 0x19, 400000
ZERO_DEADBAND = 0.3         # 严格小于此绝对偏差时置零，度
SCAN_WAIT_SECONDS = 2
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000

# ==================== 03 保存路径与配置检查 ====================
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
    for name, value in (("SLEEP_TIME", SLEEP_TIME), ("ANGLE_Y_TARGET_VALUE", ANGLE_Y_TARGET_VALUE)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} 必须为有限数值")
    if SLEEP_TIME <= 0:
        raise ValueError("SLEEP_TIME 必须大于0")
    if not isinstance(experiment_info, dict) or not experiment_info:
        raise ValueError("experiment_info 必须为非空字典")
    for key, value in experiment_info.items():
        if not isinstance(key, str) or not key.strip() or key.strip() in Recorder.FIELDS:
            raise ValueError(f"实验字段为空或与系统列重名：{key}")
        if not isinstance(value, str):
            raise ValueError(f"实验信息必须为字符串：{key}")
    if not (SCRIPT_DIRECTORY / "libSmartSensorDriver.so").is_file():
        raise ValueError("缺少 libSmartSensorDriver.so")


def relative_angle(raw_y, baseline):
    if not math.isfinite(raw_y) or not math.isfinite(baseline):
        raise ValueError("Y轴读数或基准不是有限数值")
    difference = raw_y - baseline
    return round(0.0 if abs(difference) < ZERO_DEADBAND else difference, 1)


# ==================== 04 CSV与运行源码归档 ====================
class Recorder:
    FIELDS = ("记录时间", "实验累计毫秒", "模块编号", "采样序号", "记录类型",
              "原始X(度)", "原始Y(度)", "原始Z(度)", "Y轴基准(度)",
              "相对Y(度)", "目标Y(度)", "采集间隔(秒)", "结果", "错误信息")

    def __init__(self, module_index, root=None):
        self.metadata = dict(experiment_info)
        self.module_index = module_index
        self.started = time.monotonic()
        self.fields = [*self.metadata, *self.FIELDS]
        person = safe_path_component(self.metadata.get("姓名/小组") or "未填写")
        project = safe_path_component(self.metadata.get("任务项目") or "倾角传感器模块")
        folder = (Path(root).expanduser() if root else find_desktop() / "成果输出") / person / project
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.path = folder / f"{project}_{person}_{stamp}.csv"
        with self.path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(self.fields)
        with self.path.with_suffix(".py").open("xb") as handle:
            handle.write(Path(__file__).resolve().read_bytes())
        print(f"成果位置：{self.path}", flush=True)

    def record(self, kind, result, sequence=0, raw=None, baseline="", angle="", error=""):
        x, y, z = raw if raw is not None else ("", "", "")
        values = [datetime.now().isoformat(timespec="milliseconds"),
                  round((time.monotonic() - self.started) * 1000, 3), self.module_index,
                  sequence, kind, x, y, z, baseline, angle, ANGLE_Y_TARGET_VALUE,
                  SLEEP_TIME, result, str(error)]
        row = [*self.metadata.values(), *values]
        row = ["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row]
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(row)


# ==================== 05 原厂驱动接口 ====================
def load_driver():
    driver = ctypes.CDLL(str(SCRIPT_DIRECTORY / "libSmartSensorDriver.so"))
    signatures = {
        "SmartSensorLibInit": ([], None),
        "SmartSensorLibUnInit": ([], None),
        "startScanSensors": ([], ctypes.c_int),
        "isModReady": ([ctypes.c_int], ctypes.c_int),
        "connectToMod": ([ctypes.c_int], ctypes.c_int),
        "disconnectToMod": ([ctypes.c_int], ctypes.c_int),
        "lis2dh12Init": ([ctypes.c_int] * 5, ctypes.c_int),
        "readLis2dh12Angel": ([ctypes.c_int] + [ctypes.POINTER(ctypes.c_float)] * 3, ctypes.c_int),
        "unLis2dh12Init": ([ctypes.c_int], ctypes.c_int),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(driver, name)
        function.argtypes, function.restype = arguments, result
    return driver


def checked(result, action):
    if result < 0:
        raise RuntimeError(f"{action}失败，驱动返回 {result}")


def read_angles(driver, module_index):
    values = [ctypes.c_float(float("nan")) for _ in range(3)]
    result = driver.readLis2dh12Angel(module_index, *(ctypes.byref(v) for v in values))
    # 原Demo将0视为失败，负值同时按驱动错误处理。
    if result <= 0:
        raise RuntimeError(f"读取倾角失败，驱动返回 {result}")
    raw = tuple(value.value for value in values)
    if not all(math.isfinite(value) for value in raw):
        raise ValueError(f"倾角读数无效：{raw}")
    return raw


# ==================== 06 JSON与UDP上报 ====================
class Reporter:
    def __init__(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packet_id = 0
        self.history = []
        try:
            saved = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            if isinstance(saved, list):
                self.history = [row for row in saved if isinstance(row, dict)][-5:]
        except (OSError, ValueError):
            pass

    def send(self, angle, connected, valid):
        # TileSensor是原Demo使用的协议名称，保留以兼容接收端。
        self.history.append({
            "Name": "TileSensor", "Answer": {"angleY": angle},
            "Target_Value": {"angleYSensor": ANGLE_Y_TARGET_VALUE},
            "Output_Frequency": f"{SLEEP_TIME} s/次",
            "Status": {"Connection_Status": int(connected),
                       "Communication_Status": int(valid), "Output_Status": int(valid)},
        })
        self.history = self.history[-5:]
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(json.dumps(self.history, ensure_ascii=False, indent=4), encoding="utf-8")
        data = json.dumps(self.history).encode("utf-8")
        self.packet_id = self.packet_id % 0xffffffff + 1
        count = math.ceil(len(data) / UDP_CHUNK_SIZE)
        for index in range(count):
            chunk = data[index * UDP_CHUNK_SIZE:(index + 1) * UDP_CHUNK_SIZE]
            header = b"".join(value.to_bytes(4, "little") for value in
                              (self.packet_id, count, index, len(chunk)))
            self.socket.sendto(header + chunk, UDP_DESTINATION)


# ==================== 07 采集与退出清理 ====================
def run(recorder):
    driver = reporter = None
    library_attempted = connection_attempted = sensor_attempted = False
    connected = failed = False
    sequence = 0

    def report(angle, valid):
        nonlocal failed
        if reporter is not None:
            try:
                reporter.send(angle, connected, valid)
            except Exception as error:
                failed = True
                recorder.record("上报", "失败", sequence, error=error)
                print(f"JSON/UDP上报失败：{error}", file=sys.stderr, flush=True)

    try:
        reporter = Reporter()
        driver = load_driver()
        library_attempted = True
        driver.SmartSensorLibInit()
        checked(driver.startScanSensors(), "扫描模块")
        time.sleep(SCAN_WAIT_SECONDS)
        if driver.isModReady(recorder.module_index) != 1:
            raise RuntimeError(f"模块{recorder.module_index}未在线")
        connection_attempted = True
        if driver.connectToMod(recorder.module_index) <= 0:
            raise RuntimeError("连接模块失败")
        connected = True
        sensor_attempted = True
        checked(driver.lis2dh12Init(recorder.module_index, SCL_PIN, SDA_PIN,
                                  I2C_ADDRESS, I2C_FREQUENCY), "初始化倾角传感器")
        raw = read_angles(driver, recorder.module_index)
        baseline = raw[1]
        recorder.record("启动归零", "成功", raw=raw, baseline=baseline, angle=0.0)
        print(f"Y轴启动基准：{baseline:.3f}度，之后的angleY均为相对偏角。", flush=True)
        while True:
            sequence += 1
            raw = read_angles(driver, recorder.module_index)
            angle = relative_angle(raw[1], baseline)
            recorder.record("采样", "有效", sequence, raw, baseline, angle)
            print(f"第{sequence}次：X={raw[0]:.1f}，Y={raw[1]:.1f}，Z={raw[2]:.1f}，相对Y={angle:.1f}度", flush=True)
            report(angle, True)
            time.sleep(SLEEP_TIME)
    except KeyboardInterrupt:
        recorder.record("停止", "用户中断", sequence)
    except Exception as error:
        failed = True
        recorder.record("运行", "失败", sequence, error=error)
        print(f"运行失败：{error}", file=sys.stderr, flush=True)
    finally:
        # None表示当前无有效读数，不能用0冒充回零成功。
        report(None, False)
        actions = []
        if sensor_attempted:
            actions.append(("注销倾角传感器", lambda: driver.unLis2dh12Init(recorder.module_index)))
        if connection_attempted:
            actions.append(("断开模块", lambda: driver.disconnectToMod(recorder.module_index)))
        if library_attempted:
            actions.append(("注销驱动库", driver.SmartSensorLibUnInit))
        for label, action in actions:
            try:
                result = action()
                if isinstance(result, int):
                    checked(result, label)
            except Exception as error:
                failed = True
                recorder.record(label, "失败", sequence, error=error)
                print(f"{label}失败：{error}", file=sys.stderr, flush=True)
        connected = False
        report(None, False)
        if reporter is not None:
            try:
                reporter.socket.close()
            except OSError as error:
                failed = True
                recorder.record("关闭UDP", "失败", sequence, error=error)
    return int(failed)


# ==================== 08 命令行入口 ====================
def main():
    parser = argparse.ArgumentParser(description="倾角传感器标准实训程序：启动归零、Y轴采集与成果归档")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块编号，默认13")
    parser.add_argument("--output-dir", type=Path, help="成果根目录，默认当前用户桌面/成果输出")
    parser.add_argument("--check", action="store_true", help="仅检查配置与语法，不加载硬件或写入成果")
    args = parser.parse_args()

    def request_stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        validate_settings()
        if args.check:
            compile(Path(__file__).read_text(encoding="utf-8-sig"), __file__, "exec")
            print("静态检查通过；未加载动态库，未验证硬件、实测精度或接收端。")
            return 0
        return run(Recorder(args.module, args.output_dir))
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序无法启动或保存记录：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
