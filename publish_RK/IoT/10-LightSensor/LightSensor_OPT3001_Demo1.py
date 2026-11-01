# -*- coding: utf-8 -*-
"""
光照传感器模块演示程序（OPT3001）
实现光照强度数据采集、上报和CSV成果归档
"""
import json
import csv
import math
import os
import socket
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

from UdpPackage import UdpPackage
from SensorModule import *
from BH170Sensor import *
# --------------------------------------------------------------
# 系统核心功能模块

SLEEP_TIME = 1  # 采集间隔时间（秒）
LIGHT_TARGET_VALUE = 50  # 光照目标值
modIndex = 10  # 模块地址
RESULTS_DIR = None  # None使用当前用户桌面的成果输出目录。

# --------------------------------------------------------------



#模块状态，0：不在线，1：在线
modStatus = 0
SCL_PIN = 22
SDA_PIN = 23
#BH1750_ADDR_LO 是 0x23，BH1750_ADDR_HI 是 0x5C（取决于模块ADDR引脚电平）
BH170_ADDR_LOW = 0x23 
BH170_MASTER_FREQ_HZ = 100000  # I2C速率

# 低光照阈值（传感器底噪过滤，低于此值视为0 lux）
LOW_LIGHT_THRESHOLD: float = 10.0

# UDP 通信配置
UDP_DEST_ADDR: Tuple[str, int] = ('127.0.0.1', 8088)
UDP_MAX_PACKET_SIZE: int = 1000
_udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_global_packet_id: int = 0


_Sensor = None
_csv_log = None


def find_desktop() -> Path:
    home = Path.home()
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders') as key:
                return Path(os.path.expandvars(winreg.QueryValueEx(key, 'Desktop')[0]))
        except OSError:
            pass
    else:
        path = Path(os.environ.get('XDG_CONFIG_HOME', str(home / '.config'))) / 'user-dirs.dirs'
        try:
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('XDG_DESKTOP_DIR='):
                    value = line.split('=', 1)[1].strip().strip('"').replace('${HOME}', str(home)).replace('$HOME', str(home))
                    if Path(value).is_absolute():
                        return Path(value)
        except OSError:
            pass
    return home / '桌面' if (home / '桌面').is_dir() else home / 'Desktop'


class CsvResultLog:
    FIELDS = ('采集时间', '采集序号', '模块编号', '光照强度(lx)', '光照目标值(lx)', '采集间隔(秒/次)')

    def __init__(self, output_root=None):
        base = Path(output_root).expanduser() if output_root is not None else find_desktop() / '成果输出'
        self.folder = base / '演示' / '光照采集'
        self.folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now()
        sequence = 1
        while True:
            suffix = '' if sequence == 1 else '_{}'.format(sequence)
            stem = '光照采集_演示_{}{}_{}'.format(stamp.strftime('%Y%m%d'), suffix, stamp.strftime('%H%M%S'))
            self.path = self.folder / (stem + '.csv')
            self.code_path = self.folder / (stem + '.py')
            self.error_path = self.folder / (stem.rsplit('_', 1)[0] + '_异常_' + stamp.strftime('%H%M%S') + '.csv')
            if self.code_path.exists() or self.error_path.exists():
                sequence += 1
                continue
            try:
                stream = self.path.open('x', encoding='utf-8-sig', newline='')
                break
            except FileExistsError:
                sequence += 1
        with stream:
            csv.writer(stream).writerow(self.FIELDS)
        with self.code_path.open('xb') as target, Path(__file__).resolve().open('rb') as source:
            shutil.copyfileobj(source, target)
        self.count = 0
        print('CSV成果：{}'.format(self.path), flush=True)
        print('本次源码：{}'.format(self.code_path), flush=True)

    def sample(self, lux):
        with self.path.open('a', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerow([datetime.now().isoformat(timespec='seconds'), self.count + 1,
                                        modIndex, round(lux, 2), LIGHT_TARGET_VALUE, SLEEP_TIME])
        self.count += 1

    def error(self, action, error):
        exists = self.error_path.exists()
        text = str(error)
        if text.lstrip().startswith(('=', '+', '-', '@')):
            text = "'" + text
        with self.error_path.open('a', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            if not exists:
                writer.writerow(['记录时间', '动作', '错误信息'])
            writer.writerow([datetime.now().isoformat(timespec='seconds'), action, text])

def _send_udp(data_bytes: bytes) -> None:
    """通过 UDP 发送数据"""
    global _global_packet_id
    _global_packet_id += 1
    
    length = len(data_bytes)
    num_packets = math.ceil(length / UDP_MAX_PACKET_SIZE)
    
    for i in range(num_packets):
        start = i * UDP_MAX_PACKET_SIZE
        end = min(start + UDP_MAX_PACKET_SIZE, length)
        packet = UdpPackage(
            _global_packet_id, num_packets, i,
            end - start, data_bytes[start:end]
        )
        _udp_socket.sendto(packet.toNetBytes(), UDP_DEST_ADDR)


def _save_data(sensor_values: Dict[str, float], frequencies: str, target_values: Dict[str, float]) -> None:
    """保存传感器数据到文件并通过 UDP 发送"""
    if _csv_log is not None:
        # 先保存完整采集记录，JSON/UDP异常不丢失本次已读取的数据。
        _csv_log.sample(sensor_values['light_lux'])
    current_dir = os.path.dirname(__file__)
    data_dir = os.path.join(current_dir, 'student_data')
    file_path = os.path.join(data_dir, 'student_data.json')
    
    os.makedirs(data_dir, exist_ok=True)
    
    data: Dict[str, Any] = {
        "Name": "LightSensor",
        "Answer": sensor_values,
        "Target_Value": target_values,
        "Output_Frequency": frequencies,
        "Status": {
            "Connection_Status": 1,
            "Communication_Status": 1,
            "Output_Status": 1
        }
    }
    
    existing_data: List[Dict[str, Any]] = []
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                existing_data = json.load(f)
        except json.JSONDecodeError:
            pass
    
    existing_data = existing_data[1:] if len(existing_data) >= 5 else existing_data
    existing_data.append(data)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(existing_data, f, indent=4, ensure_ascii=False)
    
    _send_udp(json.dumps(existing_data).encode('utf-8'))
    print("传感器数据保存成功")

def sensor_init() -> bool:
    """初始化光照传感器"""
    global _Sensor
    try:
        _Sensor = BH170Sensor(modIndex,SCL_PIN,SDA_PIN,BH170_ADDR_LOW,BH170_MASTER_FREQ_HZ)
        if _Sensor.init() is False:
            raise RuntimeError('光照传感器I2C初始化失败')
        #power on
        _Sensor.writebyte(0x01)
        #
        time.sleep(0.2)
        #H- resolution mode
        _Sensor.writebyte(0x10)
        print("光照传感器初始化完成")
        return True
    except Exception as e:
        print(f"光照传感器初始化失败: {e}")
        return False


def sensor_read() -> float:
    """
    读取光照传感器数据，返回光照强度（lux）
    
    说明：
    - 返回值保留两位小数
    - 低于 LOW_LIGHT_THRESHOLD 的值视为 0 lux（底噪过滤）
    """
    if _Sensor is None:
        raise RuntimeError('光照传感器未初始化')
    
    
    lux = _Sensor.readData(0)
    if not math.isfinite(lux) or lux < 0:
        raise ValueError('光照读数无效')
    
    # 底噪过滤：低于阈值视为 0
    if lux < LOW_LIGHT_THRESHOLD:
        return 0.0
    
    # 保留两位小数
    return round(lux, 2)


def sensor_cleanup() -> None:
    """清理 I2C 资源"""
    global _Sensor
    if _Sensor is not None:
        _Sensor.uninit()
        _Sensor = None
        print("I2C 已关闭")


def main():
    global _csv_log, modStatus
    modules = None
    connection_attempted = False
    exit_code = 0
    try:
        _csv_log = CsvResultLog(RESULTS_DIR)
    except Exception as error:
        print('成果文件创建失败：{}'.format(error), file=sys.stderr, flush=True)
        _udp_socket.close()
        return 1

    archive = _csv_log

    def record_error(action, error):
        print('{}：{}'.format(action, error), file=sys.stderr, flush=True)
        try:
            archive.error(action, error)
        except OSError as write_error:
            print('异常记录保存失败：{}'.format(write_error), file=sys.stderr, flush=True)

    try:
        modules = SensorModule()
        modules.startScanSensors()
        connection_attempted = True
        ret = modules.modConnect(modIndex)
        if ret <= 0 and modules.isModReady(modIndex) == 1:
            ret = modules.modConnect(modIndex)
        if ret <= 0:
            modStatus = 0
            raise RuntimeError('光照模块未连接')
        modStatus = 1
        if not sensor_init():
            raise RuntimeError('光照传感器初始化失败')

        # 启动时上报一次，之后继续原有循环采集。
        lux = sensor_read()
        sensor_values = {'light_lux': round(lux, 2)}
        target_values = {'LightSensor': LIGHT_TARGET_VALUE}
        frequencies = f'{SLEEP_TIME} s/次'
        _save_data(sensor_values, frequencies, target_values)
        print('程序正在运行，按Ctrl+C停止。', flush=True)

        while True:
            lux = sensor_read()
            print(f'光照强度: {lux:.2f} lux')
            sensor_values = {'light_lux': round(lux, 2)}
            target_values = {'LightSensor': LIGHT_TARGET_VALUE}
            frequencies = f'{SLEEP_TIME} s/次'
            _save_data(sensor_values, frequencies, target_values)
            time.sleep(SLEEP_TIME)
    except KeyboardInterrupt:
        print('\n程序已停止', flush=True)
    except Exception as error:
        exit_code = 1
        record_error('采集运行', error)
    finally:
        actions = [('关闭光照I2C', sensor_cleanup)]
        if modules is not None:
            if connection_attempted:
                actions.append(('断开光照模块', lambda: modules.modDisconnect(modIndex)))
            actions.append(('注销设备驱动', modules.uninit))
        actions.append(('关闭UDP', _udp_socket.close))
        for action, operation in actions:
            try:
                result = operation()
                if isinstance(result, int) and result < 0:
                    raise RuntimeError('驱动返回{}'.format(result))
            except Exception as error:
                exit_code = 1
                record_error(action, error)
        _csv_log = None
        print('本次已保存{}条采集记录。'.format(archive.count), flush=True)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
