#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
# 标准库负责参数读取、驱动调用、计时、文件归档及状态上报。
import argparse
import csv
import ctypes
import json
import math
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

# ==================== 02 用户设置 ====================
# ==================== 实训任务：设备间辅助照明定时控制 ====================
# 某施工项目拟对设备间辅助照明回路开展定时控制调试。
# RK3588通过单路继电器下发回路开启、关闭指令，并向管理软件上报状态。
# 本次使用实训箱继电器模拟照明回路：每轮开启2秒，随后关闭；
# 从首轮开始计时，相邻两轮按10秒周期启动，连续观察3轮后结束。
# 请填写考试编号、项目名称及项目位置，并根据题面修改以下参数。
# 当前示例可以运行，但参数尚未达到题面要求；其他系统配置无需修改。
# 验收：核对3轮开关顺序与时序，按Ctrl+C结束，检查退出关闭记录，
# 提交同次CSV和自动归档的Python源码。
# 工程概念：驱动指令成功不等于触点已闭合或照明负载已正常运行；
# 负载效果反馈需另接电流或光照检测，本程序不将指令结果当作实测反馈。

experiment_info = {
    "考试编号": "考号",
    "项目名称": "单路继电器模块",
    "项目位置": "物联实训箱03",
}

# >>>>>>>>>>>>>>>>>>>> TODO：继电器参数设置区 >>>>>>>>>>>>>>>>>>>>
ON_DURATION = 1       # 每轮开启持续时间，秒。
CYCLE_INTERVAL = 5    # 相邻两轮开始之间的周期，秒/轮，包含开启时间。
# 关闭等待时间约为 CYCLE_INTERVAL - ON_DURATION，不是再等待一个完整周期。
# <<<<<<<<<<<<<<<<<<<< TODO：设置区结束 <<<<<<<<<<<<<<<<<<<<<<

# ==================== 03 系统配置 ====================
MODULE_INDEX = 3
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000
HISTORY_SIZE = 5
SENSOR_NAME = "RelayModule"
RELAY_CONTROLLER_PIN = 25  # 沿用原厂驱动参数，不作为RK3588排针物理脚号使用。
RELAY_ON_LEVEL = 1
RELAY_OFF_LEVEL = 0
SCAN_WAIT_SECONDS = 2

# ==================== 04 保存路径与参数检查 ====================
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
    for name, value in (("ON_DURATION", ON_DURATION), ("CYCLE_INTERVAL", CYCLE_INTERVAL)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数值")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须为有限正数")
    if CYCLE_INTERVAL <= ON_DURATION:
        raise ValueError("轮次周期必须大于开启持续时间，为关闭状态保留等待时间")


# ==================== 05 CSV 与运行代码归档 ====================
# 保存至桌面/成果输出/考试编号/项目名称；可用 --output-dir 指定其他根目录。
# 单文件包含全部实验逻辑，归档源码与同次运行的CSV配对。
class CsvExperimentLog:
    SYSTEM_FIELDS = [
        "记录时间", "实验累计毫秒", "模块编号", "轮号", "动作",
        "开启持续时间(秒)", "轮次周期(秒/轮)", "执行结果", "错误信息",
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
            "轮号": group,
            "动作": action,
            "开启持续时间(秒)": ON_DURATION,
            "轮次周期(秒/轮)": CYCLE_INTERVAL,
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


# ==================== 06 原厂驱动加载与继电器控制 ====================
def load_driver():
    driver = ctypes.CDLL(str(DRIVER_PATH))
    for name in ("SmartSensorLibInit", "SmartSensorLibUnInit", "startScanSensors"):
        getattr(driver, name).argtypes = []
    for name, count in (
        ("isModReady", 1), ("connectToMod", 1), ("disconnectToMod", 1),
        ("GpioOutInit", 2), ("GpioSetLevel", 3),
    ):
        function = getattr(driver, name)
        function.argtypes = [ctypes.c_int] * count
        function.restype = ctypes.c_int
    driver.startScanSensors.restype = ctypes.c_int
    return driver


class RelayController:
    def __init__(self, driver, module_index):
        self.driver = driver
        self.module_index = module_index
        self.library_attempted = False
        self.connection_attempted = False
        self.gpio_attempted = False
        self.connected = False
        self.state = "未知"

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
        self.gpio_attempted = True
        self.checked(self.driver.GpioOutInit(self.module_index, RELAY_CONTROLLER_PIN), "初始化继电器GPIO失败")

    def switch(self, enabled):
        self.state = "未知"
        level = RELAY_ON_LEVEL if enabled else RELAY_OFF_LEVEL
        self.checked(self.driver.GpioSetLevel(self.module_index, RELAY_CONTROLLER_PIN, level), "设置继电器开关失败")
        self.state = "开启" if enabled else "关闭"

    def disconnect(self):
        try:
            self.checked(self.driver.disconnectToMod(self.module_index), "断开模块失败")
        finally:
            self.connected = False

    def uninitialize(self):
        self.driver.SmartSensorLibUnInit()


# ==================== 07 JSON 保存与 UDP 状态上报 ====================
class EventOutput:
    def __init__(self, log):
        self.log = log
        self.udp_socket = None
        self.group_id = 0

    def emit(self, action, result, controller=None, group=0, error=""):
        event = self.log.record(action, result, group, error)
        print(f"{event['记录时间']} 轮{group} {action}：{result}" + (f"；{error}" if error else ""), flush=True)
        success = result == "驱动指令成功"
        data = {
            "Name": SENSOR_NAME,
            "Answer": {"Relay_Status": controller.state if controller is not None else "未知"},
            "Target_Value": {"Relay_Status": "-"},
            "Output_Frequency": f"{CYCLE_INTERVAL} s/轮",
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
            self.log.record("JSON 保存失败", "未执行", group, write_error)
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
            self.log.record("UDP 上报失败", "未执行", group, send_error)
            print(f"UDP 上报失败：{send_error}", file=sys.stderr, flush=True)

    def close(self):
        if self.udp_socket is not None:
            self.udp_socket.close()


# ==================== 08 动作执行与轮次周期调度 ====================
def execute_switch(controller, output, enabled, group=0, action=None):
    action = action or ("开启" if enabled else "关闭")
    try:
        controller.switch(enabled)
        completed_at = time.monotonic()
    except Exception as error:
        output.emit(action, "指令失败", controller, group, error=error)
        raise
    output.emit(action, "驱动指令成功", controller, group)
    return completed_at


def wait_until(deadline):
    time.sleep(max(0.0, deadline - time.monotonic()))


def run_groups(controller, output):
    group = 0
    next_start = time.monotonic()
    while True:
        wait_until(next_start)
        group += 1
        on_time = execute_switch(controller, output, True, group)
        wait_until(on_time + ON_DURATION)
        execute_switch(controller, output, False, group)
        output.emit("本轮完成", "驱动指令成功", controller, group)
        next_start += CYCLE_INTERVAL
        now = time.monotonic()
        if now > next_start:
            output.emit("轮次周期超时", "未执行", controller, group,
                        error="动作或处理耗时超过周期，跳过已错过的计划时刻，不补开")
            now = time.monotonic()
            next_start += (math.floor((now - next_start) / CYCLE_INTERVAL) + 1) * CYCLE_INTERVAL


# ==================== 09 失败停机与退出清理 ====================
def cleanup(controller, output):
    failed = False
    actions = []
    if controller is not None:
        if controller.gpio_attempted:
            actions.extend([
                ("退出关闭", lambda: controller.switch(False)),
            ])
        if controller.connection_attempted:
            actions.append(("断开模块", controller.disconnect))
        if controller.library_attempted:
            actions.append(("注销驱动", controller.uninitialize))
    for action, operation in actions:
        try:
            operation()
        except Exception as error:
            failed = True
            output.emit(action, "指令失败", controller, error=error)
        else:
            output.emit(action, "驱动指令成功", controller)
    try:
        output.close()
    except OSError as error:
        failed = True
        output.log.record("关闭 UDP 连接", "指令失败", error=error)
        print(f"关闭 UDP 连接失败：{error}", file=sys.stderr, flush=True)
    return failed


# ==================== 10 程序主流程与命令行入口 ====================
def run_relay(metadata, module_index=MODULE_INDEX, output_root=None):
    log = CsvExperimentLog(metadata, module_index, output_root)
    output = EventOutput(log)
    controller = None
    exit_code = 0
    stage = "检查用户设置"
    try:
        validate_settings()
        stage = "加载驱动"
        driver = load_driver()
        controller = RelayController(driver, module_index)
        stage = "初始化模块与 GPIO"
        controller.initialize()
        output.emit("初始化", "驱动指令成功", controller)
        execute_switch(controller, output, False, action="初始化关闭")
        stage = "继电器控制"
        run_groups(controller, output)
    except KeyboardInterrupt:
        output.emit("用户停止", "未执行", controller)
    except Exception as error:
        exit_code = 1
        output.emit(f"{stage}异常，停止实验", "未执行", controller, error=error)
    finally:
        if cleanup(controller, output):
            exit_code = 1
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="单路继电器教学实验：配置周期控制并保存 CSV 和运行代码")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块编号，默认3")
    parser.add_argument("--output-dir", type=Path, help="保存根目录，默认当前用户桌面下的“成果输出”目录")
    args = parser.parse_args()
    try:
        return run_relay(experiment_info, args.module, args.output_dir)
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序无法启动或保存记录：{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


# ==================== 11 程序启动 ====================
# 在本目录运行：python3 RelayModule_standard.py
# 先保存用户设置再启动，完成现场观察后按Ctrl+C停止并检查归档文件。
if __name__ == "__main__":
    sys.exit(main())
