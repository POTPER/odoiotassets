"""V5 共用运行模块：导入时不加载驱动、不连接设备、不创建成果。"""

import argparse
import csv
import ctypes
import json
import logging
import math
import os
import re
import shutil
import signal
import socket
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Event

from UdpPackage import UdpPackage

LOG = logging.getLogger(__name__)


def light_status(lux, target):
    # 与温度监测同样由系统完成比较，学生只设置目标值。
    # 低于目标值为照度不足，达到或超过目标值为正常；未知读数不参加判断。
    if lux is None:
        return '离线或读取失败'
    return '照度不足' if lux < target else '正常'


def validate_config(metadata, config):
    for key in ('考试编号', '项目名称', '监测点位'):
        if not isinstance(metadata.get(key), str) or not metadata[key].strip():
            raise ValueError('{}必须填写非空文字'.format(key))
    if any(not isinstance(k, str) or not k.strip() or k in ResultLog.COLUMNS for k in metadata):
        raise ValueError('实验信息字段名为空或与结果列重名')
    for key in ('SLEEP_TIME', 'LIGHT_TARGET_VALUE'):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('{}必须为有限正数'.format(key))
    for key in ('SCAN_WAIT', 'SENSOR_SETTLE_TIME'):
        value = config[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('{}必须为有限非负数'.format(key))
    for key in ('SAMPLE_COUNT', 'LIGHT_MODULE_INDEX', 'I2C_FREQUENCY'):
        if type(config[key]) is not int or config[key] <= 0:
            raise ValueError('{}必须为正整数'.format(key))
    for key in ('SCL_PIN', 'SDA_PIN', 'I2C_ADDRESS'):
        if type(config[key]) is not int or config[key] < 0:
            raise ValueError('{}必须为非负整数'.format(key))
    if config['SCL_PIN'] == config['SDA_PIN'] or config['I2C_ADDRESS'] > 127:
        raise ValueError('I2C引脚或7位地址不合法')


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:80] or '未命名'
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {'COM' + str(i) for i in range(1, 10)} | {'LPT' + str(i) for i in range(1, 10)}
    return '_' + value if value.split('.')[0].upper() in reserved else value


def find_desktop():
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


def safe_cell(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


class ResultLog:
    COLUMNS = ('采集时间', '采集序号', '模块编号', '光照强度(lx)', '光照目标值(lx)',
               '监测间隔(秒/次)', '数据状态', '照度不足', '错误信息')

    def __init__(self, metadata, config, entry_path, output_root=None):
        self.metadata = dict(metadata)
        self.config = dict(config)
        identity, project = (safe_name(metadata[k]) for k in ('考试编号', '项目名称'))
        base = Path(output_root) if output_root is not None else find_desktop() / '成果输出'
        self.folder = base / identity / project
        self.folder.mkdir(parents=True, exist_ok=True)
        stem = '{}_{}_{}'.format(project, identity, datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.path = self.folder / (stem + '.csv')
        self.code_path = self.folder / (stem + '.py')
        self.error_path = self.folder / (stem + '_异常.csv')
        # 启动前固定本次实际入口源码；复制失败则不启动硬件实验。
        with self.code_path.open('xb') as target, Path(entry_path).open('rb') as source:
            shutil.copyfileobj(source, target)
        with self.path.open('x', encoding='utf-8-sig', newline='') as stream:
            csv.writer(stream).writerow([*self.metadata, *self.COLUMNS])
        LOG.info('成果CSV：%s；本次入口源码：%s', self.path, self.code_path)

    def sample(self, number, lux, error=''):
        c = self.config
        status = light_status(lux, c['LIGHT_TARGET_VALUE'])
        below = '' if lux is None else ('是' if status == '照度不足' else '否')
        row = [datetime.now().isoformat(timespec='seconds'), number, c['LIGHT_MODULE_INDEX'],
               '' if lux is None else round(lux, 2), c['LIGHT_TARGET_VALUE'], c['SLEEP_TIME'],
               status, below, safe_cell(str(error))]
        with self.path.open('a', encoding='utf-8-sig', newline='') as stream:
            csv.writer(stream).writerow([*[safe_cell(v) for v in self.metadata.values()], *row])

    def error(self, action, error):
        exists = self.error_path.exists()
        with self.error_path.open('a', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            if not exists:
                writer.writerow(['记录时间', *self.metadata, '动作', '错误信息'])
            writer.writerow([datetime.now().isoformat(timespec='milliseconds'),
                             *[safe_cell(v) for v in self.metadata.values()], action, safe_cell(str(error))])


class StopRequested(Exception):
    pass


class LightHardware:
    """仅连接光照传感器，沿用Demo1的I2C字节协议。"""

    def __init__(self, config, stop, driver_factory=None):
        self.config, self.stop = config, stop
        self.factory = driver_factory or ctypes.CDLL
        self.driver = None
        self.initialized = False
        self.connections = []
        self.i2c_attempted = False

    @staticmethod
    def checked(code, action):
        if code < 0:
            raise RuntimeError('{}失败，驱动返回{}'.format(action, code))

    def start(self):
        c = self.config
        self.driver = d = self.factory(str(c['SENSOR_LIB']))
        signatures = {'SmartSensorLibInit': 0, 'SmartSensorLibUnInit': 0, 'startScanSensors': 0,
                      'isModReady': 1, 'connectToMod': 1, 'disconnectToMod': 1,
                      'I2CInit': 6, 'I2CUninit': 1}
        for name, count in signatures.items():
            function = getattr(d, name)
            function.argtypes = [ctypes.c_int] * count
            function.restype = None if name in ('SmartSensorLibInit', 'SmartSensorLibUnInit') else ctypes.c_int
        for name in ('I2CRead', 'I2CWrite'):
            function = getattr(d, name)
            function.argtypes = [ctypes.c_int] * 5 + [ctypes.POINTER(ctypes.c_ubyte)]
            function.restype = ctypes.c_int
        self.initialized = True
        d.SmartSensorLibInit()
        self.checked(d.startScanSensors(), '搜索模块')
        if self.stop.wait(c['SCAN_WAIT']):
            raise StopRequested()
        for module in (c['LIGHT_MODULE_INDEX'],):
            if d.isModReady(module) != 1:
                raise RuntimeError('模块{}未在线'.format(module))
            self.connections.append(module)
            if d.connectToMod(module) <= 0:
                raise RuntimeError('模块{}连接失败'.format(module))
        self.i2c_attempted = True
        self.checked(d.I2CInit(c['LIGHT_MODULE_INDEX'], c['SCL_PIN'], c['SDA_PIN'], 8,
                               c['I2C_FREQUENCY'], c['I2C_ADDRESS']), '初始化光照I2C')
        self._write(0x01)  # 沿用BH170Sensor：上电。
        if self.stop.wait(c['SENSOR_SETTLE_TIME']):
            raise StopRequested()
        self._write(0x10)  # 连续高分辨率模式。
        if self.stop.wait(c['SENSOR_SETTLE_TIME']):
            raise StopRequested()

    def _write(self, command):
        data = (ctypes.c_ubyte * 2)()
        data[0] = command
        self.checked(self.driver.I2CWrite(self.config['LIGHT_MODULE_INDEX'], command, 1, 0, 0, data), '光照模式设置')

    def read_lux(self):
        data = (ctypes.c_ubyte * 3)()
        self.checked(self.driver.I2CRead(self.config['LIGHT_MODULE_INDEX'], 0, 0, 2, 0, data), '读取光照')
        # 保留原始数值用于判断；失败不能转换成0 lx，避免被误判为黑暗。
        return ((data[0] << 8) | data[1]) / 1.2

    def close(self):
        errors = []
        if self.driver is None:
            return errors
        c, d = self.config, self.driver
        actions = []
        if self.i2c_attempted:
            actions.append(('关闭I2C', lambda: self.checked(d.I2CUninit(c['LIGHT_MODULE_INDEX']), '关闭I2C')))
        actions.extend(('断开模块{}'.format(module), lambda m=module: self.checked(d.disconnectToMod(m), '断开模块'))
                       for module in reversed(self.connections))
        if self.initialized:
            actions.append(('注销驱动', d.SmartSensorLibUnInit))
        for action, function in actions:
            try:
                function()
            except Exception as exc:
                errors.append((action, str(exc)))
        self.driver = None
        return errors


class StatusPublisher:
    """保留LightSensor的五条JSON及UDP分片协议，并上报照度不足标记。"""

    def __init__(self, config):
        self.config = config
        self.history = []  # 每次运行独立，不混入上一次的状态。
        self.packet_id = 0
        self.socket = None

    def publish(self, lux, valid=True, connection=True):
        c = self.config
        data = {'Name': 'LightSensor',
                'Answer': {'light_lux': round(lux, 2) if valid else None},
                'Target_Value': {'LightSensor': c['LIGHT_TARGET_VALUE']},
                'Output_Frequency': '{} s/次'.format(c['SLEEP_TIME']),
                'Below_Target': lux < c['LIGHT_TARGET_VALUE'] if valid else None,
                'Status': {'Connection_Status': int(connection), 'Communication_Status': int(valid),
                           'Output_Status': int(valid)}}
        self.history = (self.history + [data])[-5:]
        payload = json.dumps(self.history, ensure_ascii=False, allow_nan=False).encode('utf-8')
        errors = []
        path = Path(c['DATA_PATH'])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.json.tmp')
            temporary.write_bytes(payload)
            temporary.replace(path)
        except OSError as exc:
            errors.append(('JSON状态保存', str(exc)))
        if c['ENABLE_UDP']:
            try:
                if self.socket is None:
                    self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self.socket.settimeout(0.2)
                self.packet_id = (self.packet_id + 1) & 0xffffffff
                count = math.ceil(len(payload) / 1000)
                for index in range(count):
                    chunk = payload[index * 1000:(index + 1) * 1000]
                    packet = UdpPackage(self.packet_id, count, index, len(chunk), chunk)
                    self.socket.sendto(packet.toNetBytes(), c['UDP_DEST_ADDR'])
            except OSError as exc:
                errors.append(('UDP状态上报', str(exc)))
        return errors

    def close(self):
        if self.socket is not None:
            self.socket.close()


def check_environment(metadata, config, entry_path):
    """静态检查，不加载.so、不创建成果、不扫描模块。"""
    validate_config(metadata, config)
    root = Path(entry_path).resolve().parent
    for path in (Path(entry_path), root / 'light_teaching_support.py', root / 'UdpPackage.py', Path(config['SENSOR_LIB'])):
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('配套文件缺失或为空：{}'.format(path))
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
    if sys.version_info < (3, 8):
        raise ValueError('需要Python 3.8或以上')
    LOG.info('静态检查通过；当前Python：%s；尚未验证驱动加载、模块连接或实际读数', sys.version.split()[0])
    LOG.info('I2C沿用原Demo1：地址0x%02X，命令0x01/0x10，读数除以1.2；不要依据OPT3001文件名改协议', config['I2C_ADDRESS'])
    return 0


def run_session(metadata, config, entry_path, output_root=None, *,
                hardware_factory=LightHardware, publisher_factory=StatusPublisher, stop=None,
                clock=time.monotonic, install_signals=True):
    validate_config(metadata, config)
    stop = stop if stop is not None else Event()
    recorder = ResultLog(metadata, config, entry_path, output_root)
    hardware, publisher = None, None
    handlers = {}
    exit_code = 0
    count = 0

    def record_error(action, error):
        LOG.error('%s：%s', action, error)
        try:
            recorder.error(action, error)
        except OSError:
            LOG.exception('异常记录无法写入')

    def publish(lux, valid=True, connection=True):
        for action, error in publisher.publish(lux, valid, connection):
            record_error(action, error)

    try:
        if install_signals:
            for name in ('SIGINT', 'SIGTERM', 'SIGHUP'):
                signum = getattr(signal, name, None)
                if signum is not None:
                    handlers[signum] = signal.signal(signum, lambda *_: stop.set())
        hardware = hardware_factory(config, stop)
        publisher = publisher_factory(config)
        hardware.start()
        next_sample = clock()
        while count < config['SAMPLE_COUNT'] and not stop.is_set():
            if stop.wait(max(0, next_sample - clock())):
                break
            number = count + 1
            lux = None
            try:
                lux = hardware.read_lux()
                if isinstance(lux, bool) or not isinstance(lux, (int, float)) or not math.isfinite(lux) or lux < 0:
                    lux = None
                    raise ValueError('光照读数无效')
                if stop.is_set():
                    raise StopRequested()
            except StopRequested:
                break
            except Exception as exc:
                recorder.sample(number, None, error=str(exc))
                publish(None, valid=False)
                record_error('光照采集', exc)
                exit_code = 1
                break
            recorder.sample(number, lux)
            count += 1
            publish(lux)
            LOG.info('采集 %d/%d：%.2f lx；%s', count, config['SAMPLE_COUNT'], lux, light_status(lux, config['LIGHT_TARGET_VALUE']))
            next_sample += config['SLEEP_TIME']
            now = clock()
            if count < config['SAMPLE_COUNT'] and next_sample < now:
                skipped = math.floor((now - next_sample) / config['SLEEP_TIME']) + 1
                record_error('采样周期超时', '跳过{}个计划时刻，不突发补采；请检查处理耗时'.format(skipped))
                next_sample += skipped * config['SLEEP_TIME']
    except (StopRequested, KeyboardInterrupt):
        stop.set()
    except Exception as exc:
        exit_code = 1
        record_error('实验运行', exc)
    finally:
        stop.set()
        if hardware is not None:
            try:
                for action, error in hardware.close():
                    exit_code = 1
                    record_error(action, error)
            except Exception as exc:
                exit_code = 1
                record_error('硬件清理', exc)
        if publisher is not None:
            try:
                # 清除上一条有效采样的状态，退出不增加采集成果行。
                publish(None, valid=False, connection=False)
            except Exception as exc:
                record_error('停止状态上报', exc)
            try:
                publisher.close()
            except Exception as exc:
                record_error('关闭UDP', exc)
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
    if count < config['SAMPLE_COUNT']:
        record_error('采集未完成', '本次成功采集{}/{}次，请核对主CSV和异常记录'.format(count, config['SAMPLE_COUNT']))
        if exit_code == 0:
            exit_code = 130
    LOG.info('本次成功采集%d/%d次；已尝试关闭I2C、断开模块并释放驱动', count, config['SAMPLE_COUNT'])
    return exit_code


def launch(metadata, config, entry_path, argv=None):
    parser = argparse.ArgumentParser(description='V5 施工通道照明监测；运行前保存代码，一次只启动一个入口')
    parser.add_argument('--check', action='store_true', help='仅检查配置、语法和配套文件，不连接硬件')
    parser.add_argument('--output-dir', type=Path, help='成果根目录；其下仍按考试编号/项目名称分目录')
    parser.add_argument('--no-udp', action='store_true', help='停用UDP；仍写本地JSON和CSV')
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', datefmt='%H:%M:%S')
    config = dict(config)
    if args.no_udp:
        config['ENABLE_UDP'] = False
    try:
        if args.check:
            return check_environment(metadata, config, entry_path)
        return run_session(metadata, config, entry_path, args.output_dir)
    except Exception as exc:
        LOG.error('启动失败：%s', exc)
        return 1
