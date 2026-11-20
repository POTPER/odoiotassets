#!/usr/bin/env python3
# ==================== 教学任务 ====================
# 某施工项目拟用电机模拟设备间歇运行，任务名称为“设备间歇运行调试”，
# 测试位置为“设备管理区01”。要求电机每次运行5秒，停止5秒后再次运行。
# 连续观察不少于3轮，核对运行、停止时间及无异常连续运行，按 Ctrl+C 结束。
# TODO：填写实验信息，根据题面调整 MOTOR_ON_TIME 和 LOOP_DELAY。
# 初始参数可运行，需由学生调整为题面目标；其他驱动及通信配置通常无需修改。
# 提交同次 CSV 和自动归档的 Python 源码，实际转动及停转效果须现场核对。
# 运行：python3 MotorModule_standard.py；支持 --module 和 --output-dir。
# 文件保存位置：当前用户桌面 / 成果输出 / 姓名或小组 / 任务项目。

# ==================== 01 标准库导入 ====================
import argparse
import csv
import ctypes
import json
import math
import os
import re
import socket
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# ==================== 02 用户设置 ====================
# 字典中的字段自动写入 CSV，运行时无需输入，可按教学需要增删字段。
experiment_info = {
    "姓名/小组": "任务小组",
    "学号": "",
    "任务项目": "电机模块",
    "任务位置": "物联实训箱05",
}
MOTOR_ON_TIME = 2   # 每次运行时间，秒，须为有限正数
LOOP_DELAY = 3      # 每次关闭指令完成到下一次开启之间的停止时间，秒，须为有限正数
MODULE_INDEX = 5    # 实训箱模块编号

# ==================== 03 驱动及通信参数 ====================
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000
HISTORY_SIZE = 5
SENSOR_NAME = "MotorModule"
# 沿用 MotorController.py：通道0/引脚12/定时器0，通道1/引脚13/定时器1。
PWM_CHANNELS = ((0, 12, 0), (1, 13, 1))
PWM_SPEED_MODE = 1
PWM_RESOLUTION = 10
PWM_FREQUENCY = 1000
PWM_ON_DUTY = 1023  # 固定单方向：通道0为0，通道1为1023；不提供反转
SCAN_WAIT_SECONDS = 2

# ==================== 04 保存路径与参数检查 ====================
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
    for name, value in (("MOTOR_ON_TIME", MOTOR_ON_TIME), ("LOOP_DELAY", LOOP_DELAY)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} 必须为数值")
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} 必须为有限正数")


# ==================== 05 CSV 与运行代码归档 ====================
class CsvExperimentLog:
    SYSTEM_FIELDS = [
        "记录时间", "实验累计毫秒", "模块编号", "轮号", "动作",
        "运行时间(秒)", "停止时间(秒)",
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
        # 记录动作发生的时刻，累计毫秒用于区分同一秒内的多次开关。
        return {
            "记录时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "实验累计毫秒": round((time.monotonic() - self.started) * 1000, 3),
            "模块编号": self.module_index,
            "轮号": group,
            "动作": action,
            "运行时间(秒)": MOTOR_ON_TIME,
            "停止时间(秒)": LOOP_DELAY,
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


# ==================== 06 原厂驱动加载与电机控制 ====================
def load_driver():
    driver = ctypes.CDLL(str(DRIVER_PATH))
    for name in ("SmartSensorLibInit", "SmartSensorLibUnInit", "startScanSensors"):
        getattr(driver, name).argtypes = []
    for name, count in (
        ("isModReady", 1), ("connectToMod", 1), ("disconnectToMod", 1),
        ("PWNMInit", 7), ("PwmSetDuty", 4), ("PwmStart", 3), ("PwmStop", 3),
    ):
        function = getattr(driver, name)
        function.argtypes = [ctypes.c_int] * count
        function.restype = ctypes.c_int
    driver.startScanSensors.restype = ctypes.c_int
    return driver


class MotorController:
    def __init__(self, driver, module_index):
        self.driver = driver
        self.module_index = module_index
        self.library_attempted = False
        self.connection_attempted = False
        self.pwm_attempted = False
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
        self.pwm_attempted = True
        for channel, pin, timer in PWM_CHANNELS:
            self.checked(self.driver.PWNMInit(
                self.module_index, channel, pin, PWM_SPEED_MODE,
                timer, PWM_RESOLUTION, PWM_FREQUENCY,
            ), f"PWM 通道{channel}初始化失败")

    def switch(self, enabled):
        self.state = "未知"
        for channel, duty in ((0, 0), (1, PWM_ON_DUTY if enabled else 0)):
            self.checked(self.driver.PwmSetDuty(
                self.module_index, channel, PWM_SPEED_MODE, duty,
            ), f"设置电机通道{channel}占空比失败")
        for channel, _, _ in PWM_CHANNELS:
            self.checked(self.driver.PwmStart(
                self.module_index, PWM_SPEED_MODE, channel,
            ), f"启动电机通道{channel}失败")
        self.state = "开启" if enabled else "关闭"

    def stop_channel(self, channel):
        self.checked(self.driver.PwmStop(
            self.module_index, PWM_SPEED_MODE, channel,
        ), f"停止 PWM 通道{channel}失败")

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
            "Answer": {"Motor_Status": controller.state if controller is not None else "未知"},
            "Target_Value": {"Motor_Status": "-"},
            "Output_Frequency": f"{MOTOR_ON_TIME + LOOP_DELAY} s/次",
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


# ==================== 08 动作执行与轮次调度 ====================
def execute_switch(controller, output, enabled, group=0, action=None):
    action = action or ("开启" if enabled else "关闭")
    try:
        controller.switch(enabled)
        completed_at = time.monotonic()
    except Exception as error:
        output.emit(action, "指令失败", controller, group, error)
        raise
    output.emit(action, "驱动指令成功", controller, group)
    return completed_at


def wait_until(deadline):
    time.sleep(max(0.0, deadline - time.monotonic()))


def run_groups(controller, output):
    group = 0
    while True:
        group += 1
        on_time = execute_switch(controller, output, True, group)
        wait_until(on_time + MOTOR_ON_TIME)
        off_time = execute_switch(controller, output, False, group)
        wait_until(off_time + LOOP_DELAY)
        output.emit("本轮完成", "轮次完成", controller, group)


# ==================== 09 失败停机与退出清理 ====================
def cleanup(controller, output):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    failed = False
    actions = []
    if controller is not None:
        if controller.pwm_attempted:
            actions.extend([
                ("退出关闭", lambda: controller.switch(False)),
                ("停止 PWM 通道0", lambda: controller.stop_channel(0)),
                ("停止 PWM 通道1", lambda: controller.stop_channel(1)),
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
def run_motor(metadata, module_index=MODULE_INDEX, output_root=None):
    log = CsvExperimentLog(metadata, module_index, output_root)
    output = EventOutput(log)
    controller = None
    exit_code = 0
    stage = "检查用户设置"
    try:
        validate_settings()
        stage = "加载驱动"
        driver = load_driver()
        controller = MotorController(driver, module_index)
        stage = "初始化模块与 PWM"
        controller.initialize()
        output.emit("初始化", "驱动指令成功", controller)
        execute_switch(controller, output, False, action="初始化关闭")
        stage = "电机控制"
        run_groups(controller, output)
    except KeyboardInterrupt:
        output.emit("用户停止", "未执行", controller)
    except Exception as error:
        exit_code = 1
        # 开关失败已记录对应轮号，此处补充停止原因。
        output.emit(f"{stage}异常，停止实验", "未执行", controller, error=error)
    finally:
        if cleanup(controller, output):
            exit_code = 1
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="电机教学实验：配置运行和停止时间并保存 CSV 和运行代码")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块编号，默认5")
    parser.add_argument("--output-dir", type=Path, help="保存根目录，默认当前用户桌面下的“成果输出”目录")
    args = parser.parse_args()
    def request_stop(signum, frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        return run_motor(experiment_info, args.module, args.output_dir)
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序无法启动或保存记录：{type(error).__name__}: {error}", file=sys.stderr, flush=True)
        return 1


# ==================== 11 程序启动 ====================
if __name__ == "__main__":
    sys.exit(main())
