"""Teaching records and lazy buzzer control. Importing never opens hardware."""

import csv
import ctypes
import logging
import math
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread

LOG = logging.getLogger(__name__)


def safe_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:80] or '未命名'
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM'+str(i) for i in range(1,10)), *('LPT'+str(i) for i in range(1,10))}:
        value = '_' + value
    return value


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
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(home/'.config'))) / 'user-dirs.dirs'
        try:
            for line in config.read_text(encoding='utf-8').splitlines():
                if line.strip().startswith('XDG_DESKTOP_DIR='):
                    value = line.split('=',1)[1].strip().strip('"').replace('${HOME}', str(home)).replace('$HOME', str(home))
                    if Path(value).is_absolute():
                        return Path(value)
        except OSError:
            pass
    return home/'桌面' if (home/'桌面').is_dir() else home/'Desktop'


class ExperimentLog:
    def __init__(self, metadata, config, entry_path, output_root=None):
        self.metadata, self.config = dict(metadata), dict(config)
        if any(not isinstance(k,str) or not k.strip() or k in self.COLUMNS for k in self.metadata):
            raise ValueError('实验信息字段名为空或与结果列重名。')
        base=Path(output_root) if output_root else find_desktop()/'成果输出'
        identity=safe_name(str(self.metadata.get('考试编号') or '未命名'))
        project=safe_name(str(self.metadata.get('项目名称') or '未命名实验'))
        self.folder=base/identity/project
        self.folder.mkdir(parents=True,exist_ok=True)
        stem='{}_{}_{}'.format(project,identity,datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
        self.path=self.folder/(stem+'.csv')
        self.error_path=self.folder/(stem+'_异常.csv')
        self.code_path=self.folder/(stem+'.py')
        shutil.copyfile(entry_path,self.code_path)
        self.device='初始化中' if config['ENABLE_BUZZER'] else '未启用'
        self.rows={scene:self._empty_row(scene) for scene in self.SCENES}
        self._candidate=self._since=self._last=None
        self._queue,self._stop,self._lock=Queue(maxsize=512),Event(),Lock()
        self.dropped=0
        self._save()
        self._thread=Thread(target=self._worker,name='fire-teaching-csv',daemon=True)
        self._thread.start()
        LOG.info('成果CSV：%s；提交源码：%s',self.path,self.code_path)

    @staticmethod
    def _safe_cell(value):
        return "'"+value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value

    def _append_error(self, action, error):
        exists = self.error_path.exists()
        with self.error_path.open('a', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            if not exists:
                writer.writerow(['记录时间', *self.metadata, '动作', '错误信息'])
            writer.writerow([datetime.now().isoformat(timespec='seconds'), *[self._safe_cell(v) for v in self.metadata.values()], action, self._safe_cell(str(error))])

    def submit(self, kind, **data):
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait((kind, data))
        except Full:
            with self._lock:
                self.dropped += 1
            LOG.error('成果记录队列已满，记录不完整；识别继续运行')

    def _worker(self):
        while not self._stop.is_set() or not self._queue.empty():
            try:
                kind, data = self._queue.get(timeout=.1)
            except Empty:
                continue
            try:
                if kind == 'sample':
                    self._sample(data)
                elif kind == 'device':
                    self.device = data['status']
                elif kind == 'error':
                    self._append_error(data['action'], data['error'])
                self._save()
            except Exception:
                LOG.exception('成果写入失败，内存结果保留，下次重试；识别继续运行')
        try:
            if self.dropped:
                self._append_error('记录完整性', '队列已满，丢失{}条记录'.format(self.dropped))
            self._save()
        except Exception:
            LOG.exception('最终成果写入失败')

    def close(self):
        self._stop.set()
        self._thread.join()


class BuzzerLink:
    """Owns driver initialization and PWM cleanup in one worker thread."""
    def __init__(self, config, recorder, driver_factory=None):
        self.config, self.log = dict(config), recorder
        self._factory = driver_factory or (lambda: ctypes.CDLL(str(config['SENSOR_LIB'])))
        self._stop, self._wake, self._lock = Event(), Event(), Lock()
        self._condition, self._since, self._last = False, None, None
        self._absent_since = None
        self._thread = None

    def start(self):
        self._thread = Thread(target=self._worker, name='fire-teaching-buzzer', daemon=True)
        self._thread.start()

    def update(self, condition, now):
        with self._lock:
            if self._last is None or now-self._last > self.config['RESULT_TIMEOUT'] or now < self._last:
                self._since = None
            if condition:
                if not self._condition or self._since is None:
                    self._since = now
                self._absent_since = None
            else:
                self._since = None
                if self._absent_since is None:
                    self._absent_since = now
            self._condition, self._last = bool(condition), now
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()

    def close(self):
        self.stop()
        if self._thread is not None:
            self._thread.join()

    @staticmethod
    def _checked(code, operation):
        if code < 0:
            raise RuntimeError('{}失败，驱动返回{}'.format(operation, code))

    def _switch(self, driver, enabled):
        c = self.config
        self._checked(driver.PwmSetDuty(c['BUZZER_MODULE_INDEX'], 0, 0, 1000 if enabled else 0), '设置占空比')
        self._checked(driver.PwmStart(c['BUZZER_MODULE_INDEX'], 0, 0), '应用蜂鸣器开关')

    def _pattern(self):
        c = self.config
        return c['BEEP_COUNT'], c['BEEP_DURATION'], c['BEEP_INTERVAL'], c['BEEP_REPEAT_INTERVAL']

    def _worker(self):
        driver = None
        initialized = connection_attempted = pwm_attempted = failed = False
        c = self.config
        try:
            driver = self._factory()
            for name, count in (('SmartSensorLibInit',0), ('SmartSensorLibUnInit',0), ('startScanSensors',0),
                                ('isModReady',1), ('connectToMod',1), ('disconnectToMod',1),
                                ('PWNMInit',7), ('PwmSetDuty',4), ('PwmStart',3), ('PwmStop',3)):
                function = getattr(driver, name)
                function.argtypes = [ctypes.c_int]*count
                function.restype = None if name in ('SmartSensorLibInit','SmartSensorLibUnInit') else ctypes.c_int
            initialized = True
            driver.SmartSensorLibInit()
            self._checked(driver.startScanSensors(), '搜索模块')
            if self._stop.wait(c['SCAN_WAIT']):
                return
            if driver.isModReady(c['BUZZER_MODULE_INDEX']) != 1:
                raise RuntimeError('蜂鸣器模块{}未在线'.format(c['BUZZER_MODULE_INDEX']))
            connection_attempted = True
            if driver.connectToMod(c['BUZZER_MODULE_INDEX']) <= 0:
                raise RuntimeError('蜂鸣器连接失败')
            pwm_attempted = True
            self._checked(driver.PWNMInit(c['BUZZER_MODULE_INDEX'],0,12,0,0,10,1000), 'PWM初始化')
            self._switch(driver, False)
            self.log.submit('device', status='就绪（实际发声需现场核对）')
            next_group, latched = 0.0, False
            while not self._stop.is_set():
                now = time.monotonic()
                with self._lock:
                    condition, since, last, absent = self._condition, self._since, self._last, self._absent_since
                    count, duration, interval, repeat_interval = self._pattern()
                if absent is not None and now-absent >= c['RESET_TIME']:
                    latched = False
                valid = condition and last is not None and now-last <= c['RESULT_TIMEOUT']
                if (valid and since is not None and now-since >= c['CONFIRM_TIME'] and now >= next_group
                        and (c['BUZZER_REPEAT'] or not latched)):
                    # Once a group starts, absence suppresses subsequent groups;
                    # shutdown interrupts the current group and turns PWM off.
                    for index in range(count):
                        self._switch(driver, True)
                        interrupted = self._stop.wait(duration)
                        self._switch(driver, False)
                        if interrupted or (index+1 < count and self._stop.wait(interval)):
                            break
                    self.log.submit('device', status='鸣叫指令成功（实际发声需现场核对）')
                    latched, next_group = True, time.monotonic()+repeat_interval
                else:
                    self._wake.wait(.05)
                    self._wake.clear()
        except Exception as exc:
            failed = True
            self.log.submit('device', status='故障：{}'.format(exc))
            self.log.submit('error', action='蜂鸣器联动', error=str(exc))
            LOG.exception('蜂鸣器已停用，识别继续运行')
        finally:
            self._stop.set()
            actions = []
            if pwm_attempted:
                actions += [('关闭蜂鸣器', lambda: self._switch(driver,False)),
                            ('停止PWM', lambda: self._checked(driver.PwmStop(c['BUZZER_MODULE_INDEX'],0,0),'停止PWM'))]
            if connection_attempted:
                actions.append(('断开模块', lambda: self._checked(driver.disconnectToMod(c['BUZZER_MODULE_INDEX']),'断开模块')))
            if initialized:
                actions.append(('注销驱动', driver.SmartSensorLibUnInit))
            for action, function in actions:
                try:
                    function()
                except Exception as exc:
                    failed = True
                    self.log.submit('error', action=action, error=str(exc))
                    self.log.submit('device', status='清理故障：{}：{}'.format(action, exc))
            if not failed:
                self.log.submit('device', status='已关闭（实际发声需现场核对）')


class TeachingSession:
    LOG_CLASS = ExperimentLog
    BUZZER_CLASS = BuzzerLink

    def __init__(self, metadata, config, entry_path, rule, commands, output_root=None, driver_factory=None):
        for name in ('CONFIRM_TIME','RESULT_TIMEOUT','RESET_TIME','BEEP_DURATION','BEEP_REPEAT_INTERVAL'):
            if not math.isfinite(config[name]) or config[name] <= 0:
                raise ValueError('{} 必须为有限正数。'.format(name))
        for name in ('SCAN_WAIT','BEEP_INTERVAL'):
            if not math.isfinite(config[name]) or config[name] < 0:
                raise ValueError('{} 必须为有限非负数。'.format(name))
        if type(config['BEEP_COUNT']) is not int or config['BEEP_COUNT'] <= 0:
            raise ValueError('BEEP_COUNT 必须为正整数。')
        if type(config['BUZZER_MODULE_INDEX']) is not int or config['BUZZER_MODULE_INDEX'] < 0:
            raise ValueError('BUZZER_MODULE_INDEX 必须为非负整数。')
        if any(type(config[name]) is not bool for name in ('ENABLE_BUZZER','BUZZER_REPEAT')):
            raise ValueError('ENABLE_BUZZER/BUZZER_REPEAT 必须为布尔值。')
        self.config, self.rule, self.commands = dict(config), rule, commands
        self.log = self.LOG_CLASS(metadata, config, entry_path, output_root)
        self.buzzer = self.BUZZER_CLASS(config, self.log, driver_factory) if config['ENABLE_BUZZER'] else None
        self._disabled, self._started, self._failed = False, False, False
        self._last_state = self._last_record = None

    def start(self):
        if not self._started:
            self._started = True
            if self.buzzer is not None:
                self.buzzer.start()

    def fail(self, action, error):
        if self._failed:
            return
        self._failed = True
        if self.buzzer is not None:
            self.buzzer.stop()
        self.log.submit('sample', high=0, low=0, condition=None, now=time.monotonic())
        self.log.submit('error', action=action, error=str(error))

    def stop(self):
        if self.buzzer is not None:
            self.buzzer.stop()

    def close(self):
        try:
            if self.buzzer is not None:
                self.buzzer.close()
        finally:
            self.log.close()
