"""光照与RGB联动；导入时不加载驱动或连接设备。"""

import argparse
import ctypes
import logging
import math
import signal
import time
from datetime import datetime
from pathlib import Path
from threading import Event
import csv

from light_teaching_support import (
    LightHardware, ResultLog, StatusPublisher, StopRequested, safe_cell,
    validate_config as validate_light_config,
)

LOG = logging.getLogger('light_rgb')
COLOR_LEVELS = {'蓝色': (0, 0, 1), '绿色': (0, 1, 0), '红色': (1, 0, 0)}


def light_band(lux, config):
    if lux < config['LOW_LIGHT_LUX']:
        return '弱光', '蓝色'
    if lux < config['HIGH_LIGHT_LUX']:
        return '中等光照', '绿色'
    return '强光', '红色'


def validate_config(metadata, config):
    count = config['SAMPLE_COUNT']
    if type(count) is not int or count < 0:
        raise ValueError('SAMPLE_COUNT必须为非负整数')
    validate_light_config(metadata, dict(config, SAMPLE_COUNT=count or 1))
    for name in ('LOW_LIGHT_LUX', 'HIGH_LIGHT_LUX'):
        value = config[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError('{}必须为有限正数'.format(name))
    if config['LOW_LIGHT_LUX'] >= config['HIGH_LIGHT_LUX']:
        raise ValueError('弱光分界必须小于强光分界')
    if type(config['LED_MODULE_INDEX']) is not int or config['LED_MODULE_INDEX'] <= 0:
        raise ValueError('LED_MODULE_INDEX必须为正整数')
    if config['LED_MODULE_INDEX'] == config['LIGHT_MODULE_INDEX']:
        raise ValueError('RGB模块与光照模块编号不能相同')
    pins = config['LED_PINS']
    if not isinstance(pins, (list, tuple)) or len(pins) != 3 or any(type(p) is not int or p < 0 for p in pins) or len(set(pins)) != 3:
        raise ValueError('LED_PINS必须为三个不同的引脚编号')
    if type(config['LED_ON_LEVEL']) is not int or config['LED_ON_LEVEL'] not in (0, 1):
        raise ValueError('LED_ON_LEVEL必须为0或1')


class LightRgbHardware(LightHardware):
    def __init__(self, config, stop, driver_factory=None):
        super().__init__(config, stop, driver_factory)
        self.gpio_attempted = []

    def start(self):
        # 两个模块共用同一次驱动初始化、扫描与退出清理。
        super().start()
        c, d = self.config, self.driver
        for name, count in (('GpioOutInit', 2), ('GpioSetLevel', 3)):
            function = getattr(d, name)
            function.argtypes = [ctypes.c_int] * count
            function.restype = ctypes.c_int
        module = c['LED_MODULE_INDEX']
        if d.isModReady(module) != 1:
            raise RuntimeError('RGB模块{}未在线'.format(module))
        self.connections.append(module)
        if d.connectToMod(module) <= 0:
            raise RuntimeError('RGB模块连接失败')
        for pin in c['LED_PINS']:
            self.gpio_attempted.append(pin)
            self.checked(d.GpioOutInit(module, pin), '初始化RGB引脚{}'.format(pin))
            self.checked(d.GpioSetLevel(module, pin, 1 - c['LED_ON_LEVEL']), '初始熄灯')

    def set_color(self, color):
        levels = COLOR_LEVELS[color]
        c = self.config
        # 先关闭不使用的通道，再点亮目标通道，避免上次颜色残留。
        for enabled in (0, 1):
            for pin, state in zip(c['LED_PINS'], levels):
                if state == enabled:
                    level = c['LED_ON_LEVEL'] if state else 1 - c['LED_ON_LEVEL']
                    self.checked(self.driver.GpioSetLevel(c['LED_MODULE_INDEX'], pin, level), '设置灯色')

    def close(self):
        errors = []
        if self.driver is not None:
            for pin in self.gpio_attempted:
                try:
                    self.checked(self.driver.GpioSetLevel(self.config['LED_MODULE_INDEX'], pin,
                                                         1 - self.config['LED_ON_LEVEL']), '退出熄灯')
                except Exception as exc:
                    errors.append(('关闭RGB引脚{}'.format(pin), str(exc)))
        errors.extend(super().close())
        return errors


class RgbLog(ResultLog):
    COLUMNS = ('采集时间', '采集序号', '光照强度(lx)', '弱光分界(lx)', '强光分界(lx)',
               '光照档位', '灯色请求', '指令执行结果', '错误信息')

    def sample(self, number, lux, color='', result='未执行', error=''):
        band = light_band(lux, self.config)[0] if lux is not None else '读取失败'
        row = [datetime.now().isoformat(timespec='milliseconds'), number,
               '' if lux is None else round(lux, 2), self.config['LOW_LIGHT_LUX'],
               self.config['HIGH_LIGHT_LUX'], band, color, result, safe_cell(str(error))]
        with self.path.open('a', encoding='utf-8', newline='') as stream:
            csv.writer(stream).writerow([*[safe_cell(v) for v in self.metadata.values()], *row])


def run_session(metadata, config, entry_path, output_root=None, *, hardware_factory=LightRgbHardware,
                publisher_factory=StatusPublisher, stop=None, clock=time.monotonic, install_signals=True):
    validate_config(metadata, config)
    stop = stop if stop is not None else Event()
    recorder = RgbLog(metadata, config, entry_path, output_root)
    hardware = publisher = None
    handlers = {}
    count, exit_code = 0, 0

    def report(action, error):
        LOG.error('%s：%s', action, error)
        try:
            recorder.error(action, error)
        except OSError:
            LOG.exception('异常记录无法写入')

    def publish(lux, valid=True, connection=True):
        if publisher is not None:
            for action, error in publisher.publish(lux, valid, connection):
                report(action, error)

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
        while not stop.is_set() and (config['SAMPLE_COUNT'] == 0 or count < config['SAMPLE_COUNT']):
            if stop.wait(max(0, next_sample - clock())):
                break
            lux, color, result = None, '', '未执行'
            try:
                lux = hardware.read_lux()
                if isinstance(lux, bool) or not isinstance(lux, (int, float)) or not math.isfinite(lux) or lux < 0:
                    lux = None
                    raise ValueError('光照读数无效')
                if stop.is_set():
                    break
                band, color = light_band(lux, config)
                result = '指令失败'
                hardware.set_color(color)
                result = '驱动指令成功'
            except StopRequested:
                break
            except Exception as exc:
                recorder.sample(count + 1, lux, color, result, str(exc))
                publish(lux, valid=lux is not None)
                report('光照灯色联动', exc)
                exit_code = 1
                break
            recorder.sample(count + 1, lux, color, result)
            count += 1
            publish(lux)
            LOG.info('光照 %.2f lx；%s；灯色请求=%s；%s', lux, band, color, result)
            next_sample += config['SLEEP_TIME']
            now = clock()
            if next_sample < now:
                next_sample += (math.floor((now - next_sample) / config['SLEEP_TIME']) + 1) * config['SLEEP_TIME']
    except (StopRequested, KeyboardInterrupt):
        pass
    except Exception as exc:
        exit_code = 1
        report('采集运行', exc)
    finally:
        stop.set()
        if hardware is not None:
            try:
                for action, error in hardware.close():
                    exit_code = 1
                    report(action, error)
            except Exception as exc:
                exit_code = 1
                report('设备清理', exc)
        if publisher is not None:
            try:
                publish(None, valid=False, connection=False)
            except Exception as exc:
                report('停止状态回传', exc)
            try:
                publisher.close()
            except Exception as exc:
                report('回传清理', exc)
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
    LOG.info('演示已结束，保存%d次采集，已逐项尝试熄灯和释放设备。', count)
    return exit_code


def check_environment(metadata, config, entry_path):
    validate_config(metadata, config)
    root = Path(entry_path).resolve().parent
    for path in (Path(entry_path), root / 'light_rgb_support.py', root / 'light_teaching_support.py',
                 root / 'UdpPackage.py', Path(config['SENSOR_LIB'])):
        if not path.is_file() or path.stat().st_size == 0:
            raise FileNotFoundError('配套文件缺失或为空：{}'.format(path))
        if path.suffix == '.py':
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
    LOG.info('文件及参数检查通过；实物光照和RGB灯色需在实训箱验证。')
    return 0


def launch(metadata, config, entry_path, argv=None):
    parser = argparse.ArgumentParser(description='光照与RGB灯色联动演示')
    parser.add_argument('--check', action='store_true', help='检查配套文件，不连接硬件')
    parser.add_argument('--output-dir', type=Path, help='成果保存根目录')
    parser.add_argument('--no-udp', action='store_true', help='关闭UDP回传，仍保存运行状态及成果')
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
        LOG.error('启动或归档失败：%s', exc)
        return 1
