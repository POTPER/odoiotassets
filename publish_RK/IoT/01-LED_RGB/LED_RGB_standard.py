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

# ==================== 考试任务：设备状态指示调试 ====================
# 某施工项目开展智能建造设备管理试点，拟为现场终端增加彩色指示灯，
# 帮助工作人员识别设备状态。项目部将本次工作定名为“设备状态指示调试”，
# 选取“设备管理区01”开展模拟测试。
#
# 方案约定每轮依次点亮红色、绿色、蓝色，每种颜色持续1秒，
# 同轮相邻两种颜色之间全部熄灯0.3秒，任何时刻只允许一种颜色点亮。
# 从首轮开始计时，后续各轮按5秒周期启动；最后一种颜色结束后全部熄灯，
# 等待下一轮，并保存颜色切换、亮灭动作及执行结果，供检查追溯。
#
# 正式接入前，由你使用物联实训箱完成调试，设备管理人员现场观察。
# 验收须连续看到3轮完整指示，确认颜色顺序、持续时间及轮次节奏符合要求，
# 无混色或常亮，方可结束，并归档运行记录及同次程序。

# ====================================================
# 请阅读顶部任务背景，在本分区填写实验信息并调整指示灯参数。
# TODO：根据题面设置颜色顺序、每色持续时间、轮内熄灯间隔及轮次周期。
# 当前示例可以运行，请检查配置并现场观察；其他参数和程序逻辑无需修改。
# 连续完成3轮完整指示后按Ctrl+C结束，提交同次CSV及自动保存的Python源码。

experiment_info = {
    "考试编号": "考号",
    "项目名称": "RGB指示灯模块",
    "项目位置": "物联实训箱01",
}

# >>>>>>>>>>>>>>>>>>>> TODO：指示灯参数设置区 >>>>>>>>>>>>>>>>>>>>
COLOR_SEQUENCE = ["红色"]  # 每轮点亮顺序，可选“红色”“绿色”“蓝色”，可重复。
LIGHT_DURATION = 0.2       # 每种颜色持续时间，秒。
LIGHT_INTERVAL = 0.1       # 同轮相邻两种颜色之间的全部熄灯时间，秒。
CYCLE_INTERVAL = 8         # 相邻两轮开始之间的周期，秒/轮。
# <<<<<<<<<<<<<<<<<<<< TODO：设置区结束 <<<<<<<<<<<<<<<<<<<<<<

# ==================== 03 系统配置 ====================
# 以下为实训箱驱动与通信参数，本次任务通常无需修改。
MODULE_INDEX = 1
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000
HISTORY_SIZE = 5
SENSOR_NAME = "LED_RGB"
# 沿用 LED_RGB_Demo1.py 的原厂驱动引脚与电平：1=点亮，0=熄灭。
PIN_LED_R = 23
PIN_LED_G = 25
PIN_LED_B = 22
COLOR_PINS = {"红色": PIN_LED_R, "绿色": PIN_LED_G, "蓝色": PIN_LED_B}
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
    if not isinstance(COLOR_SEQUENCE, (list, tuple)) or not COLOR_SEQUENCE:
        raise ValueError("COLOR_SEQUENCE 必须为非空列表或元组")
    for color in COLOR_SEQUENCE:
        if not isinstance(color, str) or color not in COLOR_PINS:
            raise ValueError("COLOR_SEQUENCE 只能包含“红色”“绿色”“蓝色”")
    for name, value, allow_zero in (
        ("LIGHT_DURATION", LIGHT_DURATION, False),
        ("LIGHT_INTERVAL", LIGHT_INTERVAL, True),
        ("CYCLE_INTERVAL", CYCLE_INTERVAL, False),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数值")
        if not math.isfinite(value) or value < 0 or (not allow_zero and value == 0):
            raise ValueError(f"{name} 必须为有限的{'非负数' if allow_zero else '正数'}")
    count = len(COLOR_SEQUENCE)
    action_duration = count * LIGHT_DURATION + (count - 1) * LIGHT_INTERVAL
    if not math.isfinite(action_duration) or CYCLE_INTERVAL < action_duration:
        raise ValueError("轮次周期不能小于 颜色数量×持续时间＋(颜色数量−1)×轮内熄灯间隔")


# ==================== 05 CSV 与运行代码归档 ====================
# 默认保存到当前用户桌面/成果输出/考试编号/项目名称，每次运行新建CSV及同次入口源码。
# CSV记录实际参数、目标颜色、亮灭动作与驱动执行结果，灯光效果需现场观察核对。
class CsvExperimentLog:
    SYSTEM_FIELDS = [
        "记录时间", "实验累计毫秒", "模块编号", "轮号", "轮内颜色序号", "动作", "目标颜色",
        "颜色顺序", "每色持续时间(秒)", "轮内熄灯间隔(秒)", "轮次周期(秒/轮)",
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
        person = str(self.metadata.get("考试编号") or "未命名").strip() or "未命名"
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

    def make_event(self, action, result, group=0, step=0, color="", error=""):
        return {
            "记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "实验累计毫秒": round((time.monotonic() - self.started) * 1000, 3),
            "模块编号": self.module_index,
            "轮号": group,
            "轮内颜色序号": step,
            "动作": action,
            "目标颜色": color,
            "颜色顺序": str(COLOR_SEQUENCE),
            "每色持续时间(秒)": LIGHT_DURATION,
            "轮内熄灯间隔(秒)": LIGHT_INTERVAL,
            "轮次周期(秒/轮)": CYCLE_INTERVAL,
            "执行结果": result,
            "错误信息": f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error),
        }

    def write_event(self, event):
        row = {**event, **self.metadata}
        with self.file_path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow([self.spreadsheet_text(row[key]) for key in self.field_names])

    def record(self, action, result, group=0, step=0, color="", error=""):
        event = self.make_event(action, result, group, step, color, error)
        try:
            self.write_event(event)
        except OSError as write_error:
            print(f"CSV 写入失败：{write_error}；动作：{action}；原始错误：{error}", file=sys.stderr, flush=True)
        return event


# ==================== 06 原厂驱动加载与指示灯控制 ====================
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


class LedController:
    def __init__(self, driver, module_index):
        self.driver = driver
        self.module_index = module_index
        self.library_attempted = False
        self.connection_attempted = False
        self.gpio_attempted = []
        self.connected = False
        self.color = "未知"
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
        for pin in COLOR_PINS.values():
            self.gpio_attempted.append(pin)
            self.checked(self.driver.GpioOutInit(self.module_index, pin), f"初始化 GPIO {pin} 失败")

    def switch(self, color):
        if color is not None and color not in COLOR_PINS:
            raise ValueError(f"不支持的颜色：{color}")
        self.color, self.state = "未知", "未知"
        errors = []
        # 切换前先全部熄灭，防止上一种颜色残留而混色。
        # 某一路失败也继续关闭其余已尝试初始化的引脚，退出清理同样适用。
        for pin in self.gpio_attempted:
            try:
                self.checked(self.driver.GpioSetLevel(self.module_index, pin, 0), f"熄灭 GPIO {pin} 失败")
            except Exception as error:
                errors.append(str(error))
        if errors:
            raise RuntimeError("；".join(errors))
        self.color, self.state = "无", "关闭"
        if color is not None:
            self.color, self.state = "未知", "未知"
            self.checked(self.driver.GpioSetLevel(self.module_index, COLOR_PINS[color], 1), f"点亮{color}失败")
            self.color, self.state = color, "开启"

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

    def emit(self, action, result, controller=None, group=0, step=0, color="", error=""):
        event = self.log.record(action, result, group, step, color, error)
        print(f"{event['记录时间']} 轮{group} 第{step}色 {action} {color}：{result}" + (f"；{error}" if error else ""), flush=True)
        success = result == "驱动指令成功"
        data = {
            "Name": SENSOR_NAME,
            "Answer": {
                "LED_Color": controller.color if controller is not None else "未知",
                "LED_Status": controller.state if controller is not None else "未知",
            },
            "Target_Value": {"LED_Color": color or "-"},
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
            self.log.record("JSON 保存失败", "未执行", group, step, color, write_error)
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
            self.log.record("UDP 上报失败", "未执行", group, step, color, send_error)
            print(f"UDP 上报失败：{send_error}", file=sys.stderr, flush=True)

    def close(self):
        if self.udp_socket is not None:
            self.udp_socket.close()


# ==================== 08 动作执行与轮次周期调度 ====================
def execute_color(controller, output, color, group=0, step=0, action=None):
    action = action or ("点亮" if color is not None else "全部熄灭")
    target = color if color is not None else "熄灭"
    try:
        controller.switch(color)
        completed_at = time.monotonic()
    except Exception as error:
        output.emit(action, "指令失败", controller, group, step, target, error)
        raise
    output.emit(action, "驱动指令成功", controller, group, step, target)
    return completed_at


def wait_until(deadline):
    time.sleep(max(0.0, deadline - time.monotonic()))


def run_groups(controller, output):
    group = 0
    next_start = time.monotonic()
    while True:
        wait_until(next_start)
        group += 1
        for step, color in enumerate(COLOR_SEQUENCE, 1):
            on_time = execute_color(controller, output, color, group, step)
            wait_until(on_time + LIGHT_DURATION)
            off_time = execute_color(controller, output, None, group, step)
            if step < len(COLOR_SEQUENCE):
                wait_until(off_time + LIGHT_INTERVAL)
        output.emit("本轮完成", "驱动指令成功", controller, group)
        next_start += CYCLE_INTERVAL
        now = time.monotonic()
        if now > next_start:
            output.emit("轮次周期超时", "未执行", controller, group,
                        error="动作或处理耗时超过设定周期，跳过已错过的计划时刻，不补亮")
            now = time.monotonic()
            skipped = math.floor((now - next_start) / CYCLE_INTERVAL) + 1
            next_start += skipped * CYCLE_INTERVAL


# ==================== 09 失败停机与退出清理 ====================
def cleanup(controller, output):
    failed = False
    actions = []
    if controller is not None:
        if controller.gpio_attempted:
            actions.append(("退出全部熄灭", lambda: controller.switch(None)))
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
def run_led(metadata, module_index=MODULE_INDEX, output_root=None):
    log = CsvExperimentLog(metadata, module_index, output_root)
    output = EventOutput(log)
    controller = None
    exit_code = 0
    stage = "检查用户设置"
    try:
        validate_settings()
        stage = "加载驱动"
        driver = load_driver()
        controller = LedController(driver, module_index)
        stage = "初始化模块与 GPIO"
        controller.initialize()
        execute_color(controller, output, None, action="初始化全部熄灭")
        stage = "指示灯控制"
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
    parser = argparse.ArgumentParser(description="RGB指示灯教学实验：配置颜色与亮灭动作并保存 CSV 和运行代码")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块编号，默认1")
    parser.add_argument("--output-dir", type=Path, help="保存根目录，默认当前用户桌面下的“成果输出”目录")
    args = parser.parse_args()
    try:
        return run_led(experiment_info, args.module, args.output_dir)
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序无法启动或保存记录：{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


# ==================== 11 程序启动 ====================
# 在本目录运行：python3 LED_RGB.py
# 先保存用户设置再启动，完成现场观察后按Ctrl+C停止并检查归档文件。
if __name__ == "__main__":
    sys.exit(main())
