#!/usr/bin/env python3
# ==================== 教学任务 ====================
# 某施工通道需开展红外光栅遮挡检测调试，任务名称为“通道光栅状态采集”，位置为“施工通道01”。
# TODO：填写 experiment_info，将 SLEEP_TIME 调整为0.2秒/次。
# 依次保持无遮挡、遮挡、恢复无遮挡各至少3秒，重复3轮，观察电平变化后按Ctrl+C结束。
# 提交同次CSV、自动归档源码与现场观察记录，说明0/1分别对应哪种现场状态。
# 本程序只记录原始电平，不预设遮挡极性，也不实现防夹、计数或报警控制。
# 运行：python3 InfraredGratingSensor_standard.py；支持 --module、--output-dir。

# ==================== 01 标准库导入 ====================
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

# ==================== 02 用户设置 ====================
experiment_info = {
    "姓名/小组": "任务小组",
    "学号": "",
    "任务项目": "红外光栅传感器",
    "任务位置": "物联实训箱08",
}
SLEEP_TIME = 0.1  # 采集间隔，秒，须为有限正数

# ==================== 03 驱动及通信参数 ====================
MODULE_INDEX = 8
IR_PIN = 5
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000
HISTORY_SIZE = 5
SENSOR_NAME = "InfraredGratingSensor"
SCAN_WAIT_SECONDS = 2

# ==================== 04 参数检查与成果归档 ====================
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
    for name, value in (("SLEEP_TIME", SLEEP_TIME),):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数值")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须为有限正数")


# ==================== 05 CSV 与运行代码归档 ====================
class CsvExperimentLog:
    SYSTEM_FIELDS = [
        "记录时间", "实验累计毫秒", "模块编号", "序号", "动作", "原始电平",
        "采集间隔(秒)",
        "执行结果", "错误信息",
    ]

    def __init__(self, metadata, module_index, output_root=None):
        if not isinstance(metadata, dict):
            raise ValueError("experiment_info 必须是字典")
        self.metadata = dict(metadata)
        for key in self.metadata:
            if not isinstance(key, str) or not key.strip() or key.strip() in self.SYSTEM_FIELDS:
                raise ValueError(f"自定义字段名为空、不是字符串或与系统列重名：{key}")
        self.module_index = module_index
        self.started = time.monotonic()
        self.field_names = [self.SYSTEM_FIELDS[0], *self.metadata, *self.SYSTEM_FIELDS[1:]]
        root = Path(output_root).expanduser() if output_root is not None else find_desktop() / "成果输出"
        person = str(self.metadata.get("姓名/小组") or self.metadata.get("小组/姓名") or "未命名").strip() or "未命名"
        # 归档名称取自用户设置中的“任务项目”。
        project = str(self.metadata.get("任务项目") or "未命名实验").strip() or "未命名实验"
        folder = root / safe_path_component(person) / safe_path_component(project)
        folder.mkdir(parents=True, exist_ok=True)
        started = datetime.now()
        date, clock = started.strftime("%Y%m%d"), started.strftime("%H%M%S")
        sequence = 1
        while True:
            suffix = "" if sequence == 1 else f"_{sequence}"
            self.file_path = folder / f"{safe_path_component(project)}_{safe_path_component(person)}_{date}{suffix}_{clock}.csv"
            self.code_path = self.file_path.with_suffix(".py")
            if self.code_path.exists():
                sequence += 1
                continue
            try:
                handle = self.file_path.open("x", encoding="utf-8-sig", newline="")
                break
            except FileExistsError:
                sequence += 1
        with handle:
            csv.writer(handle).writerow(self.field_names)
        print(f"CSV 保存位置：{self.file_path}", flush=True)
        try:
            source = Path(__file__).resolve().read_bytes()
            with self.code_path.open("xb") as handle:
                handle.write(source)
            print(f"运行代码保存位置：{self.code_path}", flush=True)
        except OSError as error:
            self.record("保存运行代码", "未执行", error=error)
            print(f"运行代码保存失败：{error}", file=sys.stderr, flush=True)

    @staticmethod
    def spreadsheet_text(value):
        if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
            return "'" + value
        return value

    def make_event(self, action, result, group=0, error=""):
        # 累计毫秒用于核对采样时间；序号0为生命周期或异常事件。
        return {
            "记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "实验累计毫秒": round((time.monotonic() - self.started) * 1000, 3),
            "模块编号": self.module_index,
            "序号": group,
            "原始电平": "",
            "动作": action,
            "采集间隔(秒)": SLEEP_TIME,
            "执行结果": result,
            "错误信息": f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error),
        }

    def write_event(self, event):
        row = {**event, **self.metadata}
        with self.file_path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow([self.spreadsheet_text(row[key]) for key in self.field_names])

    def record(self, action, result, group=0, error=""):
        event = self.make_event(action, result, group, error)
        try:
            self.write_event(event)
        except OSError as write_error:
            print(f"CSV 写入失败：{write_error}；动作：{action}；原始错误：{error}", file=sys.stderr, flush=True)
        return event


# ==================== 05 原厂驱动 ====================
def load_driver():
    # 延迟加载，导入模块和 --help 均不连接硬件。
    driver = ctypes.CDLL(str(DRIVER_PATH))
    for name in ("SmartSensorLibInit", "SmartSensorLibUnInit"):
        getattr(driver, name).argtypes = []
        getattr(driver, name).restype = None
    for name, count in (
        ("startScanSensors", 0), ("isModReady", 1), ("connectToMod", 1),
        ("disconnectToMod", 1), ("GpioInInit", 5), ("GpioGetLevel", 2),
    ):
        function = getattr(driver, name)
        function.argtypes = [ctypes.c_int] * count
        function.restype = ctypes.c_int
    return driver


class GratingController:
    def __init__(self, driver, module_index):
        self.driver = driver
        self.module_index = module_index
        self.library_attempted = False
        self.connection_attempted = False
        self.connected = False

    @staticmethod
    def checked(result, message):
        if result < 0:
            raise RuntimeError(f"{message}，驱动返回值：{result}")

    def initialize(self):
        self.library_attempted = True
        self.driver.SmartSensorLibInit()
        self.checked(self.driver.startScanSensors(), "扫描失败")
        time.sleep(SCAN_WAIT_SECONDS)
        if self.driver.isModReady(self.module_index) != 1:
            raise RuntimeError(f"模块 {self.module_index} 未在线")
        self.connection_attempted = True
        if self.driver.connectToMod(self.module_index) <= 0:
            raise RuntimeError("连接模块失败")
        self.connected = True
        # 沿用原厂参数：GPIO5，pullup=0、pulldown=1、intrflag=0。
        self.checked(self.driver.GpioInInit(self.module_index, IR_PIN, 0, 1, 0), "GPIO初始化失败")

    def read(self):
        level = self.driver.GpioGetLevel(self.module_index, IR_PIN)
        if level not in (0, 1):
            raise RuntimeError(f"读取电平失败或返回无效值：{level}")
        return level

    def disconnect(self):
        try:
            self.checked(self.driver.disconnectToMod(self.module_index), "断开模块失败")
        finally:
            self.connected = False

    def uninitialize(self):
        self.driver.SmartSensorLibUnInit()


# ==================== 06 CSV、JSON 与 UDP 输出 ====================
class EventOutput:
    def __init__(self, log):
        self.log = log
        self.udp_socket = None
        self.group_id = 0

    def emit(self, action, result, controller=None, sequence=0, level=None, error=""):
        event = self.log.make_event(action, result, sequence, error)
        event["原始电平"] = "" if level is None else level
        self.log.write_event(event)
        print(f"{event['记录时间']} 序号{sequence} {action}：{result} 电平={event['原始电平']}"
              + (f"；{error}" if error else ""), flush=True)
        success = result == "采集成功" and level in (0, 1)
        data = {
            "Name": SENSOR_NAME,
            "Answer": {"Grating_Status": str(level) if success else "未知"},
            "Target_Value": {"Grating_Status": "0"},
            "Output_Frequency": f"{SLEEP_TIME} s/次",
            "Status": {
                "Connection_Status": int(controller is not None and controller.connected),
                "Communication_Status": int(success),
                "Output_Status": int(success),
            },
        }
        try:
            DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
            history = []
            if DATA_PATH.exists():
                try:
                    history = json.loads(DATA_PATH.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    history = []
            if not isinstance(history, list):
                history = []
            history = [row for row in history if isinstance(row, dict)][-(HISTORY_SIZE - 1):]
            history.append(data)
            DATA_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=4), encoding="utf-8")
        except OSError as write_error:
            self.log.record("JSON 保存失败", "未执行", sequence, write_error)
            print(f"JSON 保存失败：{write_error}", file=sys.stderr, flush=True)
            return
        try:
            if self.udp_socket is None:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            payload = json.dumps(history).encode("utf-8")
            self.group_id = (self.group_id + 1) % (1 << 32)
            packet_count = (len(payload) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE
            for index in range(packet_count):
                chunk = payload[index * UDP_CHUNK_SIZE:(index + 1) * UDP_CHUNK_SIZE]
                header = b"".join(value.to_bytes(4, "little") for value in (self.group_id, packet_count, index, len(chunk)))
                self.udp_socket.sendto(header + chunk, UDP_DESTINATION)
        except OSError as send_error:
            self.log.record("UDP 上报失败", "未执行", sequence, send_error)
            print(f"UDP 上报失败：{send_error}", file=sys.stderr, flush=True)

    def close(self):
        if self.udp_socket is not None:
            self.udp_socket.close()


# ==================== 07 连续采集与退出清理 ====================
def run_samples(controller, output):
    sequence = 0
    while True:
        sequence += 1
        try:
            level = controller.read()
            sampled_at = time.monotonic()
        except Exception as error:
            output.emit("读取电平", "采集失败", controller, sequence, error=error)
            raise
        output.emit("读取电平", "采集成功", controller, sequence, level)
        # 从本次读取返回起计时，写盘和上报耗时计入等待。
        time.sleep(max(0.0, sampled_at + SLEEP_TIME - time.monotonic()))


def cleanup(controller, output):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    failed = False
    actions = []
    if controller is not None:
        if controller.connection_attempted:
            actions.append(("断开模块", controller.disconnect))
        if controller.library_attempted:
            actions.append(("注销驱动", controller.uninitialize))
    for action, operation in actions:
        try:
            operation()
        except Exception as error:
            failed = True
            output.log.record(action, "指令失败", error=error)
        else:
            output.log.record(action, "驱动指令成功")
    # 结束状态仅表示本次采集停止，不代表设备物理掉线。
    try:
        output.emit("采集结束", "已停止", controller)
    except Exception as error:
        failed = True
        print(f"结束状态保存失败：{error}", file=sys.stderr, flush=True)
    try:
        output.close()
    except OSError as error:
        failed = True
        output.log.record("关闭 UDP 连接", "指令失败", error=error)
    return failed


# ==================== 08 主流程与命令行入口 ====================
def run_sensor(metadata, module_index=MODULE_INDEX, output_root=None):
    log = CsvExperimentLog(metadata, module_index, output_root)
    output = EventOutput(log)
    controller = None
    exit_code = 0
    stage = "检查用户设置"
    try:
        validate_settings()
        stage = "加载驱动"
        controller = GratingController(load_driver(), module_index)
        stage = "初始化模块与GPIO"
        controller.initialize()
        output.emit("初始化", "驱动指令成功", controller)
        stage = "连续采集"
        run_samples(controller, output)
    except KeyboardInterrupt:
        log.record("用户停止", "未执行")
    except Exception as error:
        exit_code = 1
        log.record(f"{stage}异常，停止实验", "未执行", error=error)
        print(f"{stage}：{error}", file=sys.stderr, flush=True)
    finally:
        if cleanup(controller, output):
            exit_code = 1
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="红外光栅教学实验：采集原始电平并保存CSV和运行代码")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块编号，默认8")
    parser.add_argument("--output-dir", type=Path, help="保存根目录，默认当前用户桌面下的成果输出目录")
    args = parser.parse_args()

    def request_stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        return run_sensor(experiment_info, args.module, args.output_dir)
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序无法启动或保存记录：{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


# ==================== 09 程序启动 ====================
if __name__ == "__main__":
    sys.exit(main())
