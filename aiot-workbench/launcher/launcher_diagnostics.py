"""Read-only checks and shareable launcher error details."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from types import SimpleNamespace

from config_versions import current_version
from core import SyncError


from version import VERSION as LAUNCHER_VERSION


def diagnostic_text(publish, data, log_dir=None):
    question = current_version(SimpleNamespace(target=Path(publish))) if publish else '配置版本：未读取'
    returncode = data.get('returncode')
    return '\n'.join((
        'AIoT 启动器版本：' + LAUNCHER_VERSION,
        '{} {} / Python {}'.format(platform.system(), platform.machine(), platform.python_version()),
        'publish：' + (str(publish) if publish else '未读取'),
        question,
        '退出码：' + (str(returncode) if returncode is not None else '未取得'),
        '日志：' + str(data.get('logfile') or log_dir or '未生成'),
        '错误：' + str(data.get('error') or '无'),
    ))


def doctor(publish=None, settings_file=None):
    from launcher_runtime import check_installation, config_directory, load_settings

    settings_path = Path(settings_file or config_directory() / 'settings.json').expanduser().absolute()
    messages, failed = [], False

    def check(label, action):
        nonlocal failed
        try:
            detail = action()
        except Exception as exc:
            failed = True
            messages.append('[失败] {}：{}'.format(label, exc))
            return None
        messages.append('[通过] {}{}'.format(label, '：' + str(detail) if detail else ''))
        return detail

    def check_platform():
        if sys.platform != 'linux':
            raise SyncError('实际启动需要 Ubuntu 图形桌面')
        if sys.version_info < (3, 8):
            raise SyncError('需要 Python 3.8 或更新版本')
        return sys.executable

    def check_tk():
        import tkinter as tk
        root = tk.Tk()
        try:
            root.withdraw()
            return root.tk.call('info', 'patchlevel')
        finally:
            root.destroy()

    def check_images():
        from PIL import Image, ImageTk, _imagingtk  # Same imports as the installer.
        return Image.__version__

    def check_entry(target):
        script = target.parent / 'launcher.sh'
        if script.is_symlink() or not script.is_file() or not os.access(script, os.R_OK):
            raise SyncError('找不到可读的 {}，请重新运行安装脚本'.format(script))
        if not shutil.which('bash'):
            raise SyncError('找不到 bash')
        return script

    def check_permissions(target):
        for folder in (target, target.parent):
            if not os.access(folder, os.W_OK | os.X_OK):
                raise SyncError('当前用户无法写入 ' + str(folder))

    check('系统与 Python', check_platform)
    check('Tk 图形会话', check_tk)
    check('Pillow 图像组件', check_images)
    if publish is None:
        publish = check('读取部署设置', lambda: load_settings(settings_path, read_only=True)['publish_dir'])
    if publish:
        publish = Path(publish).expanduser().absolute()
        if check('AIoT 安装', lambda: check_installation(publish) or publish):
            check('目录权限', lambda: check_permissions(publish))
            check('启动脚本', lambda: check_entry(publish))

    log_dir = settings_path.parent / 'logs'
    try:
        logfile = max(log_dir.glob('gui-startup-*.log'), default=None)
    except OSError:
        logfile = None
    print(diagnostic_text(publish, {'logfile': logfile}, log_dir))
    print('设置文件：' + str(settings_path))
    print('DISPLAY={}  WAYLAND_DISPLAY={}'.format(os.environ.get('DISPLAY', ''), os.environ.get('WAYLAND_DISPLAY', '')))
    print('\n'.join(messages))
    return int(failed)


def _open_log(path):
    path = str(path.resolve(strict=True))
    if sys.platform == 'win32':
        os.startfile(path)
        return
    opener = shutil.which('open' if sys.platform == 'darwin' else 'xdg-open')
    if opener:
        command = [opener, path]
    elif shutil.which('gio'):
        command = [shutil.which('gio'), 'open', path]
    else:
        raise SyncError('找不到打开日志的桌面程序。')
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def show_diagnostic_error(parent, title, data, publish=None, log_dir=None):
    from tkinter import simpledialog, ttk

    logfile = Path(data['logfile']) if data.get('logfile') else None
    log_target = logfile if logfile and logfile.is_file() else Path(log_dir) if log_dir else None

    class ErrorDialog(simpledialog.Dialog):
        def body(self, master):
            message = str(data['error'])
            if len(message) > 1200:
                message = message[:1200] + '…'
            if logfile:
                message += '\n\n日志：' + str(logfile)
            ttk.Label(master, text=message, justify='left', wraplength=520).pack(fill='x', padx=12, pady=8)
            self.feedback = ttk.Label(master, wraplength=520)
            self.feedback.pack(fill='x', padx=12)

        def buttonbox(self):
            row = ttk.Frame(self, padding=(12, 4, 12, 12))
            row.pack(fill='x')
            ttk.Button(row, text='打开日志', command=self.open_log,
                       state='normal' if log_target and log_target.exists() else 'disabled').pack(side='left')
            ttk.Button(row, text='复制诊断', command=self.copy_diagnostic).pack(side='left', padx=8)
            ttk.Button(row, text='关闭', command=self.cancel).pack(side='right')
            self.bind('<Return>', self.cancel)
            self.bind('<Escape>', self.cancel)

        def open_log(self):
            try:
                _open_log(log_target)
            except (OSError, SyncError) as exc:
                self.feedback.configure(text=str(exc))

        def copy_diagnostic(self):
            report = diagnostic_text(publish, data, log_dir)
            parent.clipboard_clear()
            parent.clipboard_append(report)
            self.feedback.configure(text='已复制诊断')

    ErrorDialog(parent, title=title)
