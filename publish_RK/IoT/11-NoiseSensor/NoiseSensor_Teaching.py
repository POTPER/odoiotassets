#!/usr/bin/env python3
# ==================== 01 程序依赖 ====================
# 标准库负责参数读取、串口驱动调用、定时采集、成果归档和状态上报。
import argparse
import csv
import ctypes
import json
import math
import os
import re
import signal
import socket
import struct
import sys
import tempfile
import time
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from threading import Event

# ==================== 02 用户设置 ====================

# ==================== 考试任务：施工通道噪声监测 ====================
# 某施工项目拟在施工通道设置噪声监测点，供现场巡查人员查看环境噪声变化。
# 项目部将本次工作定名为“施工通道噪声监测”，选取“施工通道01”开展模拟调试。
#
# 调试约定每2秒采集一次，共进行10次采样。读数高于60 dB时标记“超限”，
# 等于或低于60 dB时标记“正常”。60 dB为本次课堂调试设定的阈值。
#
# 现由你使用物联实训箱中的11号噪声传感器完成调试，观察两种声环境下的读数，
# 核对采样间隔和判定标记，提交本次CSV运行记录和同次程序源码。

# ====================================================
# TODO：根据题面填写实验信息，并修改噪声目标值和监测间隔。
# 当前示例可以运行。系统根据实际填写的目标值判断，采集与判断代码已提供。
# 完成10次采样后程序自动结束，也可按Ctrl+C提前停止并保留已写记录。

experiment_info = {
    "考试编号": "考号",
    "项目名称": "噪声传感器",
    "项目位置": "物联实训箱11",
}

# >>>>>>>>>>>>>>>>>>>> TODO：监测参数设置区 >>>>>>>>>>>>>>>>>>>>
NOISE_TARGET_VALUE = 50  # 噪声目标值，单位dB。
SLEEP_TIME = 1           # 监测间隔，秒/次。
# <<<<<<<<<<<<<<<<<<<< TODO：设置区结束 <<<<<<<<<<<<<<<<<<<<<<

# ==================== 03 系统配置 ====================
# 串口参数和请求帧沿用11号模块原示例。
MODULE_INDEX = 11
SERIAL_CHANNEL = 2
TX_PIN = 22
RX_PIN = 23
BAUD_RATE = 115200
SCAN_WAIT_SECONDS = 2
REQUEST_FRAME = bytes.fromhex("01 02 00 00 00 00 78 0A")
RESPONSE_SIZE = 8
DRIVER_TIMEOUT = 1  # 沿用原示例传给驱动的超时参数。
SAMPLE_COUNT = 10
SCRIPT_PATH = Path(__file__).resolve()
DRIVER_PATH = SCRIPT_PATH.with_name("libSmartSensorDriver.so")
DATA_PATH = SCRIPT_PATH.parent / "student_data" / "student_data.json"
UDP_DESTINATION = ("127.0.0.1", 8088)
UDP_CHUNK_SIZE = 1000
HISTORY_SIZE = 5
EXPERIMENT_FIELDS = ("考试编号", "项目名称", "项目位置")


# ==================== 04 保存路径与参数检查 ====================
def safe_path_component(text):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text).strip(" .")
    cleaned = cleaned[:80].rstrip(" .") or "未命名"
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10))
    return "_" + cleaned if cleaned.split(".")[0].upper() in reserved else cleaned


def find_desktop():
    home = Path.home()
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    try:
        config = (config_dir / "user-dirs.dirs").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        config = ""
    for line in config.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "XDG_DESKTOP_DIR":
            value = value.strip().strip('"').replace("${HOME}", str(home)).replace("$HOME", str(home))
            desktop = Path(value).expanduser()
            if desktop.is_absolute():
                return desktop
    return home / "桌面" if (home / "桌面").is_dir() else home / "Desktop"


def validate_experiment_info(metadata):
    for key in EXPERIMENT_FIELDS:
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"实验信息中的“{key}”须填写非空文字")


def check_driver_file():
    if not DRIVER_PATH.is_file() or DRIVER_PATH.stat().st_size == 0:
        raise OSError(f"缺少可用的驱动文件 {DRIVER_PATH}")


def validate_settings(metadata):
    validate_experiment_info(metadata)
    for name, value in (("NOISE_TARGET_VALUE", NOISE_TARGET_VALUE), ("SLEEP_TIME", SLEEP_TIME)):
        if type(value) not in (int, float) or not 0 < value < math.inf:
            raise ValueError(f"{name} 须为有限正数")
    check_driver_file()


# ==================== 05 CSV 与运行代码归档 ====================
# 桌面/成果输出/考试编号/项目名称。每次运行生成同名CSV与Python源码。
class CsvExperimentLog:
    FIELDS = ("记录时间", *EXPERIMENT_FIELDS, "实验累计毫秒", "模块编号", "采样序号",
              "噪声读数(dB)", "噪声目标值(dB)", "监测间隔(秒/次)", "判定", "错误信息")

    def __init__(self, metadata, output_root, *, entry_path=SCRIPT_PATH, fields=None):
        self.metadata = tuple(self.spreadsheet_text(metadata[key]) for key in EXPERIMENT_FIELDS)
        root = output_root.expanduser() if output_root is not None else find_desktop() / "成果输出"
        person = safe_path_component(metadata["考试编号"])
        project = safe_path_component(metadata["项目名称"])
        folder = root / person / project
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{project}_{person}_{datetime.now():%Y%m%d_%H%M%S_%f}"
        self.csv_path = folder / f"{stem}.csv"
        code_path = folder / f"{stem}.py"
        source = entry_path.read_bytes()
        with code_path.open("xb") as stream:
            stream.write(source)
        with self.csv_path.open("x", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerow(self.FIELDS if fields is None else fields)
        print(f"CSV 保存位置：{self.csv_path}", flush=True)
        print(f"运行代码保存位置：{code_path}", flush=True)

    @staticmethod
    def spreadsheet_text(text):
        return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

    def write_row(self, timestamp, *values):
        with self.csv_path.open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow((timestamp, *self.metadata, *values))

    def record(self, timestamp, elapsed_ms, number, decibel, status, error):
        self.write_row(timestamp, elapsed_ms, MODULE_INDEX, number, decibel, NOISE_TARGET_VALUE,
                       SLEEP_TIME, status, self.spreadsheet_text(error))


# ==================== 06 原厂驱动加载与噪声读取 ====================
def load_driver():
    driver = ctypes.CDLL(str(DRIVER_PATH))
    for name in ("SmartSensorLibInit", "SmartSensorLibUnInit"):
        function = getattr(driver, name)
        function.argtypes = []
        function.restype = None
    integer = ctypes.c_int
    buffer = ctypes.POINTER(ctypes.c_ubyte)
    for name, arguments in (
        ("startScanSensors", []), ("connectToMod", [integer]), ("disconnectToMod", [integer]),
        ("RS232Init", [integer] * 8), ("RS232Uninit", [integer] * 2),
        ("RS232ModWriteReadHexData", [integer, integer, integer, buffer, integer, buffer, integer]),
    ):
        function = getattr(driver, name)
        function.argtypes = arguments
        function.restype = integer
    return driver


def check_driver_result(result, action):
    if result < 0:
        raise OSError(f"{action}失败，驱动返回 {result}")


def connect_sensor(driver, cleanup, stop):
    if stop.is_set():
        raise KeyboardInterrupt
    driver.SmartSensorLibInit()
    cleanup.callback(driver.SmartSensorLibUnInit)
    check_driver_result(driver.startScanSensors(), "扫描模块")
    if stop.wait(SCAN_WAIT_SECONDS):
        raise KeyboardInterrupt
    result = driver.connectToMod(MODULE_INDEX)
    if result <= 0:
        raise OSError(f"连接模块 {MODULE_INDEX} 失败，驱动返回 {result}")
    cleanup.callback(lambda: check_driver_result(driver.disconnectToMod(MODULE_INDEX), "断开模块"))
    if stop.is_set():
        raise KeyboardInterrupt
    check_driver_result(driver.RS232Init(MODULE_INDEX, SERIAL_CHANNEL, TX_PIN, RX_PIN,
                                         BAUD_RATE, 0, 8, 1), "初始化串口")
    cleanup.callback(lambda: check_driver_result(driver.RS232Uninit(MODULE_INDEX, SERIAL_CHANNEL), "关闭串口"))


def read_noise(driver):
    request = (ctypes.c_ubyte * len(REQUEST_FRAME)).from_buffer_copy(REQUEST_FRAME)
    response = (ctypes.c_ubyte * RESPONSE_SIZE)()
    result = driver.RS232ModWriteReadHexData(MODULE_INDEX, SERIAL_CHANNEL, len(response), response,
                                            len(request), request, DRIVER_TIMEOUT)
    # 与原示例一致，返回正值时读取回包第4个字节。
    if result <= 0:
        raise OSError(f"串口读取失败，驱动返回 {result}")
    return response[3]


# ==================== 07 JSON 保存与 UDP 状态上报 ====================
# 成功读数沿用原平台字段和分包协议，读取失败在CSV中记录。
class SensorDataOutput:
    def __init__(self):
        self.udp_socket = None
        self.group_id = 0

    def publish(self, decibel, *, target=None, interval=None):
        target = NOISE_TARGET_VALUE if target is None else target
        interval = SLEEP_TIME if interval is None else interval
        try:
            history = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, UnicodeError):
            history = []
        if not isinstance(history, list):
            history = []
        history = [record for record in history if isinstance(record, dict)][-(HISTORY_SIZE - 1):]
        history.append({
            "Name": "NoiseSensor",
            "Answer": {"noise_decibel": decibel},
            "Target_Value": {"NoiseSensor": target},
            "Output_Frequency": f"{interval} s/次",
            "Status": {"Connection_Status": 1, "Communication_Status": 1, "Output_Status": 1},
        })
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=DATA_PATH.parent) as folder:
            temporary = Path(folder) / DATA_PATH.name
            temporary.write_text(json.dumps(history, ensure_ascii=False, indent=4), encoding="utf-8")
            temporary.replace(DATA_PATH)

        if self.udp_socket is None:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        payload = json.dumps(history).encode("utf-8")
        self.group_id = (self.group_id + 1) % (1 << 32)
        packet_count = (len(payload) + UDP_CHUNK_SIZE - 1) // UDP_CHUNK_SIZE
        for index in range(packet_count):
            start = index * UDP_CHUNK_SIZE
            chunk = payload[start:start + UDP_CHUNK_SIZE]
            header = struct.pack("<4I", self.group_id, packet_count, index, len(chunk))
            self.udp_socket.sendto(header + chunk, UDP_DESTINATION)

    def close(self):
        if self.udp_socket is not None:
            self.udp_socket.close()


# ==================== 08 采样调度与超限判断 ====================
def run_sampling(driver, output, log, stop):
    started = next_sample = time.monotonic()
    read_failures = report_failures = 0
    for number in range(1, SAMPLE_COUNT + 1):
        if stop.wait(max(0, next_sample - time.monotonic())):
            raise KeyboardInterrupt
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        timestamp = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        error = ""
        try:
            decibel = read_noise(driver)
        except OSError as exc:
            decibel = None
            status = "读取失败"
            error = str(exc)
            read_failures += 1
        else:
            status = "超限" if decibel > NOISE_TARGET_VALUE else "正常"
            try:
                output.publish(decibel)
            except OSError as exc:
                error = f"JSON 保存或 UDP 上报失败，{exc}"
                report_failures += 1
        log.record(timestamp, elapsed_ms, number, decibel, status, error)
        reading = "" if decibel is None else f"{decibel} dB，"
        detail = f"，{error}" if error else ""
        print(f"{timestamp} 第 {number}/{SAMPLE_COUNT} 次采样，{reading}{status}{detail}", flush=True)

        next_sample += SLEEP_TIME
        now = time.monotonic()
        if now > next_sample:
            # 跳过已经错过的采样时刻，避免连续补采。
            next_sample += (math.floor((now - next_sample) / SLEEP_TIME) + 1) * SLEEP_TIME
    if stop.is_set():
        raise KeyboardInterrupt
    print(f"采样结束，有效 {SAMPLE_COUNT - read_failures} 次，读取失败 {read_failures} 次，"
          f"上报失败 {report_failures} 次。")
    return int(bool(read_failures or report_failures))


# ==================== 09 程序主流程与命令行入口 ====================
def run_experiment(metadata, output_root, stop):
    log = CsvExperimentLog(metadata, output_root)
    driver = load_driver()
    output = SensorDataOutput()
    with ExitStack() as cleanup:
        cleanup.callback(output.close)
        connect_sensor(driver, cleanup, stop)
        return run_sampling(driver, output, log, stop)


def main():
    parser = argparse.ArgumentParser(description="噪声传感器教学实验，采集数据并保存CSV和运行代码")
    parser.add_argument("--check", action="store_true", help="检查用户设置与驱动文件")
    parser.add_argument("--output-dir", type=Path, help="成果根目录，默认为桌面/成果输出")
    args = parser.parse_args()
    try:
        validate_settings(experiment_info)
        if args.check:
            print(f"静态检查通过，目标值 {NOISE_TARGET_VALUE} dB，监测间隔 {SLEEP_TIME} 秒。")
            return 0
        stop = Event()
        previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
        try:
            return run_experiment(experiment_info, args.output_dir, stop)
        finally:
            signal.signal(signal.SIGINT, previous)
    except KeyboardInterrupt:
        print("采集已停止，已写入的记录保留。")
        return 130
    except (OSError, ValueError, AttributeError) as error:
        print(f"运行失败，{error}", file=sys.stderr, flush=True)
        return 1


# ==================== 10 程序启动 ====================
# 在本目录运行：python3 NoiseSensor_Teaching.py
if __name__ == "__main__":
    sys.exit(main())
