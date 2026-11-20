#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==================== 教学任务 ====================
# 完成 AHT20 温湿度采集，填写实验信息，将 sleep_time 改为2秒。
# 温度和湿度目标值按教师任务填写，仅记录和上报，不参与报警控制。
# 观察至少10次有效采样，按 Ctrl+C 结束，提交同次 CSV、归档源码和现场观察记录。
# 运行：python3 TemperatureHumiditySensor_standard.py；--check 仅做静态检查。

# ==================== 01 标准库导入 ====================
# 提供命令行参数、驱动调用、JSON 处理、网络通信和计时功能。
import argparse
import csv
import os
import re
import signal
from datetime import datetime
import ctypes
import json
import math
import socket
import sys
import time
from pathlib import Path

# ==================== 02 用户设置 ====================
# 在此修改温度目标值、湿度目标值和监测间隔。
# 目标值仅用于保存和上报，不改变传感器实际读数。
experiment_info = {
    "考试编号": "考号",
    "项目名称": "温湿度采集",
    "项目位置": "物联实训箱09",
}
MODULE_INDEX = 9

degrees_sensor_target_value = 0  # 温度目标值，单位 °C
humidity_sensor_target_value = 0  # 湿度目标值，单位 %RH
sleep_time = 1  # 监测间隔，单位秒；1 表示目标为每秒采集一次

# ==================== 03 文件路径与通信常量 ====================
# 指定驱动和数据文件位置、UDP 接收地址、历史数量及等待时间。
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
DRIVER_PATH = SCRIPT_DIRECTORY / "libSmartSensorDriver.so"
DATA_PATH = SCRIPT_DIRECTORY / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000  # 每个 UDP 分包的数据长度，不含 16 字节包头
HISTORY_SIZE = 5
SENSOR_NAME = "TempHumitySensor"  # 保留原协议中的名称拼写
SCAN_WAIT_SECONDS = 2
MEASUREMENT_WAIT_SECONDS = 1

smartSensorlib = None

# ==================== 04 驱动加载 ====================
# 加载原厂动态库，声明 Python 调用底层驱动时使用的参数类型。
def load_driver():
    # 加载脚本同目录的驱动，并声明原厂函数的参数类型。
    global smartSensorlib
    smartSensorlib = ctypes.CDLL(str(DRIVER_PATH))

    smartSensorlib.SmartSensorLibInit.argtypes = []
    smartSensorlib.SmartSensorLibInit.restype = None
    smartSensorlib.SmartSensorLibUnInit.argtypes = []
    smartSensorlib.SmartSensorLibUnInit.restype = None
    smartSensorlib.startScanSensors.argtypes = []
    smartSensorlib.startScanSensors.restype = ctypes.c_int
    for name in ("connectToMod", "disconnectToMod", "isModReady"):
        function = getattr(smartSensorlib, name)
        function.argtypes = [ctypes.c_int]
        function.restype = ctypes.c_int

    smartSensorlib.I2CInit.argtypes = [ctypes.c_int] * 6
    smartSensorlib.I2CInit.restype = ctypes.c_int
    for name in ("I2CRead", "I2CWrite"):
        function = getattr(smartSensorlib, name)
        function.argtypes = [ctypes.c_int] * 5 + [ctypes.POINTER(ctypes.c_ubyte)]
        function.restype = ctypes.c_int
    smartSensorlib.I2CUninit.argtypes = [ctypes.c_int]
    smartSensorlib.I2CUninit.restype = ctypes.c_int


# ==================== 05 模块连接管理 ====================
# 负责初始化驱动、发现模块、检查在线状态、连接和断开模块。
class SensorModule:
    # 封装模块发现、连接和释放；方法名沿用原厂示例。

    def __init__(self):
        smartSensorlib.SmartSensorLibInit()

    def startScanSensors(self):
        return smartSensorlib.startScanSensors()

    def isModReady(self, modIndex):
        return smartSensorlib.isModReady(modIndex)

    def modConnect(self, modIndex):
        return smartSensorlib.connectToMod(modIndex)

    def modDisconnect(self, modIndex):
        return smartSensorlib.disconnectToMod(modIndex)

    def uninit(self):
        smartSensorlib.SmartSensorLibUnInit()


# ==================== 06 AHT20 硬件参数 ====================
# 定义 I²C 设备地址、SDA/SCL 引脚及温湿度原始值的换算基数。
AHT20_ADDR = 0x38
AHT20_SDA_PIN = 23
AHT20_SCL_PIN = 22
AHT20_RESOLUTION = 0x100000


# ==================== 07 温湿度采集 ====================
# 初始化 I²C，发送测量指令，等待结果并换算出温度和相对湿度。
class AHT20:
    # 触发一次测量，并将原始数据换算为温度和相对湿度。

    def __init__(self, module_index):
        self.module_index = module_index
        self.reinit()

    def reinit(self):
        # 保留原厂示例的地址长度、引脚、速率和调用参数。
        result = smartSensorlib.I2CInit(
            self.module_index,
            AHT20_SCL_PIN,
            AHT20_SDA_PIN,
            7,  # 原厂驱动使用的地址长度参数
            100000,  # I²C 通信速率，Hz
            AHT20_ADDR,
        )
        if result < 0:
            raise RuntimeError("温湿度传感器初始化失败")

    def readTempAndHumi(self):
        command = (ctypes.c_ubyte * 2)(0x33, 0x00)
        result = smartSensorlib.I2CWrite(self.module_index, 0xAC, 1, 2, 0, command)
        if result < 0:
            raise RuntimeError("发送测量指令失败")

        # 保留原有的 1 秒测量等待，避免改变硬件时序。
        time.sleep(MEASUREMENT_WAIT_SECONDS)
        data = (ctypes.c_ubyte * 7)()
        result = smartSensorlib.I2CRead(self.module_index, 0x71, 1, 7, 0, data)
        if result < 0:
            raise RuntimeError("读取温湿度失败")

        if data[0] & 0x80:
            raise RuntimeError("传感器仍忙，本次读数无效")
        humidity_raw = (data[1] << 12) | (data[2] << 4) | (data[3] >> 4)
        temperature_raw = ((data[3] & 0x0F) << 16) | (data[4] << 8) | data[5]
        humidity = humidity_raw / AHT20_RESOLUTION * 100
        temperature = temperature_raw / AHT20_RESOLUTION * 200 - 50
        return 1, temperature, humidity

    def uninit(self):
        return smartSensorlib.I2CUninit(self.module_index)


# ==================== 08 数据保存与 UDP 上报 ====================
# 生成包含读数、状态、目标值及频率的记录，保留最近五条并分包发送。
class SensorDataOutput:
    # 保存最近五条记录，并按照原协议分包发送到本机服务。

    def __init__(self):
        self.file_path = DATA_PATH
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.group_id = 0

    @staticmethod
    def build_record(temperature, humidity, online):
        # 生成一条记录：读数、状态、目标值和监测间隔。
        status = int(online)
        return {
            "Name": SENSOR_NAME,
            "Status": {
                "Connection_Status": status,
                "Communication_Status": status,
                "Output_Status": status,
            },
            "Answer": {
                "degrees_value": round(temperature, 2),
                "humidity_value": round(humidity, 2),
            },
            "Target_Value": {
                "degrees value": degrees_sensor_target_value,
                "humidity value": humidity_sensor_target_value,
            },
            "Output_Frequency": f"{sleep_time} s/次",
        }

    def load_history(self):
        # 文件不存在、内容损坏或格式不符时，从空列表开始。
        if not self.file_path.exists():
            return []
        try:
            history = json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return history if isinstance(history, list) else []

    @staticmethod
    def clean_history(history):
        # 检查最近四条记录，保留有效温湿度字段，为新记录留位。
        cleaned = []
        for record in history[-(HISTORY_SIZE - 1):]:
            if not isinstance(record, dict):
                continue
            readings = record.get("Answer")
            if not isinstance(readings, dict):
                continue

            cleaned_record = {
                "Name": record.get("Name", SENSOR_NAME),
                "Status": record.get("Status", {}),
                "Answer": {
                    key: value
                    for key, value in readings.items()
                    if key in ("degrees_value", "humidity_value")
                },
            }
            # 保留旧记录自身的设置，不用当前设置覆盖历史数据。
            targets = record.get("Target_Value")
            if isinstance(targets, dict):
                cleaned_record["Target_Value"] = {
                    key: value
                    for key, value in targets.items()
                    if key in ("degrees value", "humidity value")
                }
            if "Output_Frequency" in record:
                cleaned_record["Output_Frequency"] = record["Output_Frequency"]
            cleaned.append(cleaned_record)
        return cleaned

    def send_history(self, history):
        # 发送 JSON 列表；包头为四个小端、无符号 32 位整数。
        payload = json.dumps(history).encode("utf-8")
        self.group_id = (self.group_id + 1) % (1 << 32)
        packet_count = (len(payload) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE

        for packet_index in range(packet_count):
            start = packet_index * UDP_CHUNK_SIZE
            chunk = payload[start:start + UDP_CHUNK_SIZE]
            # 包头顺序：消息组编号、分包总数、分包序号、数据长度。
            header_fields = (self.group_id, packet_count, packet_index, len(chunk))
            header = b"".join(value.to_bytes(4, "little") for value in header_fields)
            self.udp_socket.sendto(header + chunk, UDP_DESTINATION)

    def save(self, temperature, humidity, online):
        # 先更新本地 JSON，再发送同一份历史记录。
        record = self.build_record(temperature, humidity, online)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        history = self.clean_history(self.load_history())
        history.append(record)

        self.file_path.write_text(
            json.dumps(history, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        self.send_history(history)

    def close(self):
        self.udp_socket.close()



# ==================== 09 配置检查与成果路径 ====================
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
    for name, value in (("sleep_time", sleep_time),
                        ("degrees_sensor_target_value", degrees_sensor_target_value),
                        ("humidity_sensor_target_value", humidity_sensor_target_value)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} 必须为有限数值")
    if sleep_time <= 0:
        raise ValueError("sleep_time 必须大于0")
    if not 0 <= humidity_sensor_target_value <= 100:
        raise ValueError("湿度目标值必须在0～100 %RH之间")
    if not isinstance(experiment_info, dict) or not experiment_info:
        raise ValueError("experiment_info 必须为非空字典")
    for key, value in experiment_info.items():
        if not isinstance(key, str) or not key.strip() or key.strip() in Recorder.FIELDS:
            raise ValueError(f"实验字段为空或与系统列重名：{key}")
        if not isinstance(value, str):
            raise ValueError(f"实验信息必须为字符串：{key}")
    if not DRIVER_PATH.is_file():
        raise ValueError(f"缺少驱动：{DRIVER_PATH}")


# ==================== 10 完整CSV与同次源码归档 ====================
class Recorder:
    FIELDS = ("记录时间", "实验累计毫秒", "采样序号", "模块编号", "温度(°C)", "湿度(%RH)",
              "温度目标(°C)", "湿度目标(%RH)", "采集间隔(秒)", "记录类型", "结果", "错误信息")

    def __init__(self, module_index, root=None):
        self.module_index = module_index
        self.metadata = dict(experiment_info)
        self.started = time.monotonic()
        self.fields = [*self.metadata, *self.FIELDS]
        person = safe_path_component(self.metadata.get("考试编号", "未填写"))
        project = safe_path_component(self.metadata.get("项目名称", "温湿度采集"))
        folder = (Path(root).expanduser() if root else find_desktop() / "成果输出") / person / project
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.path = folder / f"{project}_{person}_{stamp}.csv"
        with self.path.open("x", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerow(self.fields)
        with self.path.with_suffix(".py").open("xb") as handle:
            handle.write(Path(__file__).resolve().read_bytes())
        print(f"成果位置：{self.path}", flush=True)

    def record(self, kind, result, sequence=0, values=("", ""), error=""):
        values = [datetime.now().isoformat(timespec="milliseconds"),
                  round((time.monotonic() - self.started) * 1000, 3), sequence, self.module_index,
                  *values, degrees_sensor_target_value, humidity_sensor_target_value,
                  sleep_time, kind, result, str(error)]
        row = [*self.metadata.values(), *values]
        row = ["'" + v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row]
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            csv.writer(handle).writerow(row)


# ==================== 11 采集与退出清理 ====================
def run_sensor(recorder, mod_index):
    output = None
    library_attempted = connection_attempted = i2c_attempted = False
    sequence = 0
    failed = False

    def record(*args, **kwargs):
        # 记录失败也不能阻止硬件清理。
        nonlocal failed
        try:
            recorder.record(*args, **kwargs)
        except OSError as error:
            failed = True
            print(f"CSV写入失败：{error}", file=sys.stderr, flush=True)

    def report(temperature, humidity, online):
        nonlocal failed
        if output is not None:
            try:
                output.save(temperature, humidity, online)
            except Exception as error:
                failed = True
                record("JSON/UDP上报", "失败", sequence, error=error)
                print(f"JSON/UDP上报失败：{error}", file=sys.stderr, flush=True)

    try:
        output = SensorDataOutput()
        load_driver()
        library_attempted = True
        smartSensorlib.SmartSensorLibInit()
        if smartSensorlib.startScanSensors() < 0:
            raise RuntimeError("扫描模块失败")
        time.sleep(SCAN_WAIT_SECONDS)
        if smartSensorlib.isModReady(mod_index) != 1:
            raise RuntimeError(f"模块{mod_index}未在线")
        connection_attempted = True
        if smartSensorlib.connectToMod(mod_index) <= 0:
            raise RuntimeError("连接模块失败")
        i2c_attempted = True
        sensor = AHT20(mod_index)
        record("初始化", "成功")
        while True:
            started = time.monotonic()
            sequence += 1
            result, temperature, humidity = sensor.readTempAndHumi()
            if result != 1 or not all(math.isfinite(v) for v in (temperature, humidity)):
                raise RuntimeError("温湿度读取无效")
            record("采样", "成功", sequence, (round(temperature, 2), round(humidity, 2)))
            print(f"第{sequence}次：温度{temperature:.2f} °C，湿度{humidity:.2f} %RH", flush=True)
            report(temperature, humidity, True)
            time.sleep(max(0.0, sleep_time - (time.monotonic() - started)))
    except KeyboardInterrupt:
        record("停止", "用户中断", sequence)
    except Exception as error:
        failed = True
        record("运行", "失败", sequence, error=error)
        print(f"运行失败：{error}", file=sys.stderr, flush=True)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        report(0, 0, False)
        actions = []
        if i2c_attempted:
            actions.append(("释放I2C", lambda: smartSensorlib.I2CUninit(mod_index)))
        if connection_attempted:
            actions.append(("断开模块", lambda: smartSensorlib.disconnectToMod(mod_index)))
        if library_attempted:
            actions.append(("注销驱动", smartSensorlib.SmartSensorLibUnInit))
        if output is not None:
            actions.append(("关闭UDP", output.close))
        for label, operation in actions:
            try:
                result = operation()
                if isinstance(result, int) and result < 0:
                    raise RuntimeError(f"驱动返回{result}")
            except Exception as error:
                failed = True
                record(label, "失败", sequence, error=error)
                print(f"{label}失败：{error}", file=sys.stderr, flush=True)
            else:
                record(label, "成功", sequence)
    return int(failed)


# ==================== 12 命令行入口 ====================
def main():
    parser = argparse.ArgumentParser(description="温湿度标准实训：采集AHT20并归档CSV和运行源码")
    parser.add_argument("--module", type=int, default=MODULE_INDEX, help="模块地址，默认9")
    parser.add_argument("--check", action="store_true", help="仅检查配置、驱动文件存在和Python语法，不加载硬件")
    parser.add_argument("--output-root", "--output-dir", dest="output_root", type=Path,
                        help="成果根目录，默认当前用户桌面/成果输出")
    args = parser.parse_args()
    try:
        validate_settings()
        if args.check:
            compile(Path(__file__).read_text(encoding="utf-8-sig"), str(__file__), "exec")
            print("静态检查通过；未加载驱动，硬件、测量精度与UDP接收需板端验证。")
            return 0

        def request_stop(signum, frame):
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, request_stop)
        signal.signal(signal.SIGINT, request_stop)
        return run_sensor(Recorder(args.module, args.output_root), args.module)
    except KeyboardInterrupt:
        print("已取消实验。")
        return 0
    except Exception as error:
        print(f"程序失败：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
