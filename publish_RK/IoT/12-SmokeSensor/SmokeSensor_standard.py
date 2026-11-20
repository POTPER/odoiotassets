#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
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

# ==================== 02 用户设置与教学任务 ====================
# 施工现场需对“设备间01”开展烟雾状态采集调试，项目名称为“设备间烟雾状态监测”。
# TODO：填写 experiment_info，将采集间隔设为0.5秒，观察正常、触发、恢复三种过程。
# 每种状态至少保留3条有效采样，按 Ctrl+C 结束，提交同次CSV、源码与现场观察记录。
# 初始参数可运行；本程序读取数字电平，不能测得ppm浓度，触发含义需现场核对。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "烟雾传感器模块",
    "项目位置": "物联实训箱12",
}
SLEEP_TIME = 1  # 每次处理完成后的等待时间，秒，必须为有限正数。

# ==================== 03 驱动与通信配置 ====================
MODULE_INDEX = 12
SMOKE_PIN = 5  # 原厂模块GPIO编号，不是RK3588排针物理脚号。
TRIGGER_LEVEL = 0  # 沿用原Demo循环的低电平触发约定，实际极性待板端核对。
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000
HISTORY_SIZE = 5
SENSOR_NAME = "SmokeSensor"
SCAN_WAIT_SECONDS = 2

# ==================== 04 参数检查与成果归档 ====================
def safe_path_component(text):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', text).strip(' .')
    cleaned = cleaned[:80].rstrip(' .') or "未命名"
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    if cleaned.split('.')[0].upper() in reserved:
        cleaned = "_" + cleaned
    return cleaned


def find_desktop():
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
# 保存至桌面/成果输出/考试编号/项目名称；可用 --output-dir 指定其他根目录。
# 单文件包含全部实验逻辑，归档源码与同次运行的CSV配对。
class CsvExperimentLog:
    SYSTEM_FIELDS = [
        "记录时间", "实验累计毫秒", "模块编号", "采样序号", "动作",
        "采集间隔(秒/次)", "原始电平", "烟雾状态", "执行结果", "错误信息",
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
        person = str(self.metadata.get("考试编号") or "未命名").strip() or "未命名"
        # 归档名称取自用户设置中的“项目名称”。
        project = str(self.metadata.get("项目名称") or "未命名实验").strip() or "未命名实验"
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
        return {
            "记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "实验累计毫秒": round((time.monotonic() - self.started) * 1000, 3),
            "模块编号": self.module_index,
            "采样序号": group,
            "动作": action,
            "采集间隔(秒/次)": SLEEP_TIME,
            "原始电平": "",
            "烟雾状态": "未知",
            "执行结果": result,
            "错误信息": f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error),
        }

    def write_event(self, event):
        row = {**event, **self.metadata}
        with self.file_path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow([self.spreadsheet_text(row[key]) for key in self.field_names])

    def record(self, action, result, group=0, error="", level="", status="未知"):
        event = self.make_event(action, result, group, error)
        event.update({"原始电平": level, "烟雾状态": status})
        try:
            self.write_event(event)
        except OSError as write_error:
            print(f"CSV 写入失败：{write_error}；动作：{action}；原始错误：{error}", file=sys.stderr, flush=True)
        return event


# ==================== 06 原厂数字输入驱动 ====================
def load_driver():
    driver = ctypes.CDLL(str(DRIVER_PATH))
    for name in ("SmartSensorLibInit", "SmartSensorLibUnInit"):
        getattr(driver, name).argtypes = []
        getattr(driver, name).restype = None
    for name, count in (("startScanSensors", 0), ("isModReady", 1),
                        ("connectToMod", 1), ("disconnectToMod", 1),
                        ("GpioInInit", 5), ("GpioGetLevel", 2)):
        function = getattr(driver, name)
        function.argtypes = [ctypes.c_int] * count
        function.restype = ctypes.c_int
    return driver


class SmokeController:
    def __init__(self, driver, module_index):
        self.driver, self.module_index = driver, module_index
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
        self.checked(self.driver.startScanSensors(), "扫描模块失败")
        time.sleep(SCAN_WAIT_SECONDS)
        if self.driver.isModReady(self.module_index) != 1:
            raise RuntimeError(f"模块 {self.module_index} 未在线")
        self.connection_attempted = True
        if self.driver.connectToMod(self.module_index) <= 0:
            raise RuntimeError("连接模块失败")
        self.connected = True
        self.checked(self.driver.GpioInInit(self.module_index, SMOKE_PIN, 0, 1, 0),
                     "初始化烟雾GPIO失败")

    def read(self):
        level = self.driver.GpioGetLevel(self.module_index, SMOKE_PIN)
        if level not in (0, 1):
            raise RuntimeError(f"烟雾GPIO读取失败或返回非法电平：{level}")
        return level, "触发" if level == TRIGGER_LEVEL else "正常"

    def disconnect(self):
        try:
            self.checked(self.driver.disconnectToMod(self.module_index), "断开模块失败")
        finally:
            self.connected = False

    def uninitialize(self):
        self.driver.SmartSensorLibUnInit()


# ==================== 07 CSV、JSON与UDP上报 ====================
class EventOutput:
    def __init__(self, log):
        self.log = log
        self.udp_socket = None
        self.group_id = 0

    def emit(self, action, result, controller=None, group=0, error="", level="", status="未知"):
        event = self.log.record(action, result, group, error, level, status)
        print(f"{event['记录时间']} {action}：{result}，电平={level}，状态={status}"
              + (f"；{error}" if error else ""), flush=True)
        valid = result == "读取成功"
        value = str(int(level == TRIGGER_LEVEL)) if valid else "未知"
        data = {
            "Name": SENSOR_NAME,
            "Answer": {"SmokeSensor_Status": value},
            "Target_Value": {"SmokeSensor_Status": "0"},
            "Output_Frequency": f"{SLEEP_TIME} s/次",
            "Status": {
                "Connection_Status": int(controller is not None and controller.connected),
                "Communication_Status": int(valid),
                "Output_Status": int(valid),
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
            self.log.record("JSON 保存失败", "未执行", group, write_error)
            print(f"JSON 保存失败：{write_error}", file=sys.stderr, flush=True)
            return
        try:
            if self.udp_socket is None:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            payload = json.dumps(history).encode("utf-8")
            self.group_id = (self.group_id + 1) % (1 << 32)
            count = (len(payload) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE
            for index in range(count):
                chunk = payload[index * UDP_CHUNK_SIZE:(index + 1) * UDP_CHUNK_SIZE]
                header = b"".join(v.to_bytes(4, "little") for v in (self.group_id, count, index, len(chunk)))
                self.udp_socket.sendto(header + chunk, UDP_DESTINATION)
        except OSError as send_error:
            self.log.record("UDP 上报失败", "未执行", group, send_error)
            print(f"UDP 上报失败：{send_error}", file=sys.stderr, flush=True)

    def close(self):
        if self.udp_socket is not None:
            self.udp_socket.close()


# ==================== 08 连续采样与退出清理 ====================
def run_samples(controller, output):
    sequence = 0
    while True:
        sequence += 1
        try:
            level, status = controller.read()
        except Exception as error:
            output.emit("采样", "读取失败", controller, sequence, error)
            return 1
        output.emit("采样", "读取成功", controller, sequence, level=level, status=status)
        time.sleep(SLEEP_TIME)


def cleanup(controller, output):
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
            output.emit(action, "清理失败", controller, error=error)
        else:
            output.emit(action, "清理完成", controller)
    try:
        output.close()
    except OSError as error:
        failed = True
        output.log.record("关闭 UDP 连接", "清理失败", error=error)
    return failed


def run_smoke(metadata, module_index=MODULE_INDEX, output_root=None):
    log = CsvExperimentLog(metadata, module_index, output_root)
    output = EventOutput(log)
    controller = None
    exit_code = 0
    stage = "检查用户设置"
    try:
        validate_settings()
        stage = "加载驱动"
        controller = SmokeController(load_driver(), module_index)
        stage = "初始化模块与GPIO"
        controller.initialize()
        output.emit("初始化", "初始化完成", controller)
        stage = "烟雾采样"
        exit_code = run_samples(controller, output)
    except KeyboardInterrupt:
        output.emit("用户停止", "已停止", controller)
    except Exception as error:
        exit_code = 1
        output.emit(f"{stage}异常，停止实验", "未执行", controller, error=error)
    finally:
        if cleanup(controller, output):
            exit_code = 1
    return exit_code


# ==================== 09 命令行入口 ====================
def main():
    parser = argparse.ArgumentParser(description="烟雾数字状态采集标准版：保存CSV与同次源码")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块编号，默认12")
    parser.add_argument("--output-dir", type=Path, help="成果根目录，默认当前用户桌面/成果输出")
    parser.add_argument("--check", action="store_true", help="只检查设置和驱动文件，不连接硬件")
    args = parser.parse_args()
    try:
        if args.module <= 0:
            raise ValueError("模块编号必须为正整数")
        if args.check:
            validate_settings()
            if not DRIVER_PATH.is_file():
                raise FileNotFoundError(DRIVER_PATH)
            print("参数及驱动文件检查通过；未加载驱动，未验证硬件。")
            return 0
        return run_smoke(experiment_info, args.module, args.output_dir)
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序无法启动或保存记录：{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


def request_stop(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, request_stop)
    sys.exit(main())
