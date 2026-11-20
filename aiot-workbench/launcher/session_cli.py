"""Headless shared entry for launcher.sh, GUI event transport and terminal use."""
import argparse
import json
import os
from pathlib import Path
import queue
import signal
import sys
import threading
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import configure
configure()

from launcher_runtime import SessionController, load_settings
from launcher_process import set_process_role
from launcher_diagnostics import LAUNCHER_VERSION, doctor


def stop_existing_session(options):
    from core import SyncError
    from running_aiot import stop_existing_aiot
    from launcher_runtime import config_directory
    result = {'error': None, 'logfile': None, 'stopped_pids': [], 'remaining_pids': []}
    previous = {}
    try:
        for sig in {signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)}:
            previous[sig] = signal.signal(sig, lambda *_: None)
        logs = config_directory() / 'logs'
        from compat import is_relative_to
        if is_relative_to(logs.resolve(), Path(options.publish_dir).resolve()):
            raise ValueError('停止日志必须保存在 publish 之外。')
        logs.mkdir(parents=True, exist_ok=True)
        logfile = logs / ('stop-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
        result['logfile'] = str(logfile)
        with logfile.open('w', encoding='utf-8', buffering=1) as stream:
            try:
                target = Path(options.publish_dir).expanduser().absolute()
                if not target.is_dir() or target.is_symlink():
                    raise SyncError('未找到有效的 publish 目录。')
                # A managed session holds its operation lock while AIoT runs.
                # Stopping verified processes must work without waiting on that lock;
                # this command never changes configuration or recovery records.
                result.update(stop_existing_aiot(target.resolve(), log=lambda message: stream.write(message + '\n')))
            except Exception as exc:
                stream.write(str(exc) + '\n')
                raise
    except Exception as exc:
        result['error'] = str(exc)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if options.events_json:
        print(json.dumps({'event': 'finished', 'data': result}, ensure_ascii=False), flush=True)
    elif result['error']:
        print(result['error'], file=sys.stderr)
    else:
        print('AIoT 已停止。' if not result['remaining_pids'] else '已有进程已停止，检测到新的 AIoT 实例。')
    return 1 if result['error'] else 0


def config_session(options):
    """Signals request cancellation before a transaction, never interrupt its writes."""
    from config_operations import configure_questions
    from launcher_runtime import config_directory
    stop = threading.Event()
    previous = {}
    result = {'error': None, 'stopped': False, 'returncode': 0, 'logfile': None}
    try:
        for sig in {signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)}:
            previous[sig] = signal.signal(sig, lambda *_: stop.set())
        if options.events_json:
            def commands():
                for line in sys.stdin:
                    if line.strip() == 'stop':
                        stop.set()
                stop.set()
            threading.Thread(target=commands, daemon=True).start()
        logs = config_directory() / 'logs'
        from compat import is_relative_to
        if is_relative_to(logs.resolve(), Path(options.publish_dir).resolve()):
            raise ValueError('配置日志必须保存在 publish 之外。')
        logs.mkdir(parents=True, exist_ok=True)
        logfile = logs / ('config-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
        result['logfile'] = str(logfile)
        with logfile.open('w', encoding='utf-8', buffering=1) as stream:
            try:
                description = ('读取赛题列表' if options.list_configs else '清理任务文件' if options.clear_task_data
                               else '替换赛题：' + options.replace_config)
                stream.write(description + '\n')
                result.update(configure_questions(options.publish_dir, options.replace_config,
                                                   exclude_pids=verified_parent(), cancel=stop,
                                                   log=lambda message: stream.write(str(message) + '\n'),
                                                   clear_only=options.clear_task_data))
            except Exception as exc:
                stream.write(str(exc) + '\n')
                raise
    except Exception as exc:
        result.update(error=str(exc), stopped=stop.is_set(), returncode=1)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if options.events_json:
        print(json.dumps({'event': 'finished', 'data': result}, ensure_ascii=False), flush=True)
    elif result['error']:
        print(result['error'], file=sys.stderr)
    elif options.list_configs:
        print(result['current'])
        for item in result['versions']:
            print(item['version'] + ('：可用' if item['valid'] else '：' + '；'.join(item['issues'])))
    elif options.clear_task_data:
        counts = result['cleanup']
        print('已清除：target.py {} 个，student_data {} 个。'.format(counts['target_files'], counts['student_data_dirs']))
    else:
        print('已切换：' + result['version'])
    return result['returncode']


def verified_parent():
    if sys.platform != "linux":
        return ()
    pid = os.getppid()
    proc = Path('/proc') / str(pid)
    try:
        exe = os.readlink(proc / 'exe')
        args = (proc / 'cmdline').read_bytes().decode().split('\0')
        cwd = os.readlink(proc / 'cwd')
        gui_entries = {Path(__file__).with_name('aiot_launcher.py').resolve(),
                       Path(__file__).resolve().parents[1] / 'workbench.py'}
        if Path(exe).name in ('bash', 'sh', 'zsh') or any(
                Path(cwd, arg).resolve() in gui_entries for arg in args if arg and not arg.startswith('-')):
            return (pid,)
    except (OSError, UnicodeError):
        pass
    return ()


def main(argv=None):
    set_process_role("session")
    parser = argparse.ArgumentParser()
    parser.add_argument('--version', action='version', version=LAUNCHER_VERSION)
    parser.add_argument('--publish-dir', required=True)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--check', action='store_true')
    actions.add_argument('--doctor', action='store_true', help='检查安装与图形会话')
    actions.add_argument('--list-configs', action='store_true', help='查询 config 下的赛题')
    actions.add_argument('--replace-config', metavar='赛题名称', help='仅替换指定赛题，不启动 AIoT')
    actions.add_argument('--clear-task-data', action='store_true', help='仅清理任务中的 target.py 和 student_data')
    actions.add_argument('--stop-existing', action='store_true', help='停止同目录的已有 AIoT 及已核验任务进程')
    parser.add_argument('--events-json', action='store_true')
    parser.add_argument('--settings-file')
    parser.add_argument('--monitor-existing', action='store_true', help='只读监视其他入口已启动的 AIoT')
    config_options = parser.add_mutually_exclusive_group()
    config_options.add_argument('--apply-config', dest='apply_config_enabled', action='store_true',
                                help='本次启动前复制赛事配置（默认关闭）')
    config_options.add_argument('--no-apply-config', dest='apply_config_enabled', action='store_false',
                                help='本次启动不复制赛事配置')
    parser.set_defaults(apply_config_enabled=None)
    options = parser.parse_args(argv)
    if options.doctor:
        return doctor(options.publish_dir, options.settings_file)
    if options.stop_existing:
        return stop_existing_session(options)
    if options.list_configs or options.replace_config is not None or options.clear_task_data:
        return config_session(options)
    result = None
    try:
        settings = load_settings(options.settings_file)
        apply_config = settings.get('apply_config_enabled', False)
        if not isinstance(apply_config, bool):
            raise ValueError('apply_config_enabled 必须为布尔值')
        # Saved legacy switches must not overwrite a manually selected bundle.
        # Retain explicit --apply-config for compatibility with terminal workflows.
        apply_config = options.apply_config_enabled is True
        collection = settings.get('collection_enabled', False)
        if not isinstance(collection, bool):
            raise ValueError('collection_enabled 必须为布尔值')
        archive = settings.get('archive_dir', '/home/ubuntu/aiot-archive')
        if collection and (not isinstance(archive, str) or not Path(archive).is_absolute()):
            raise ValueError('archive_dir 必须为绝对路径')
        controller = SessionController(options.publish_dir, collection_enabled=collection,
                                       archive_dir=archive, exclude_pids=verified_parent(),
                                       apply_config_enabled=apply_config, monitor_existing=options.monitor_existing)
        previous = {}
        for sig in {signal.SIGINT, signal.SIGTERM, getattr(signal, 'SIGHUP', signal.SIGTERM)}:
            previous[sig] = signal.signal(sig, lambda *_: controller.request_stop())
        if options.events_json:
            def commands():
                try:
                    for line in sys.stdin:
                        if line.strip() == 'stop':
                            controller.request_stop()
                finally:
                    controller.close_input()
            threading.Thread(target=commands, daemon=True).start()
        controller.initialize() if options.check else controller.start()
        try:
            while True:
                event, data = controller.events.get()
                if options.events_json:
                    print(json.dumps({'event': event, 'data': data}, ensure_ascii=False), flush=True)
                elif event == 'status':
                    print(data, flush=True)
                elif event == 'started':
                    print('AIoT 已启动。Ctrl+C 停止本次程序。', flush=True)
                elif event == 'stop_failed':
                    print('停止失败，按 Ctrl+C 重试：' + data['error'], file=sys.stderr, flush=True)
                elif event == 'external_running':
                    print('AIoT 已在运行，进程：' + ', '.join(str(pid) for pid in data['pids']), flush=True)
                if event in ('finished', 'ready'):
                    result = data
                    break
            controller.thread.join()
        finally:
            controller.request_stop()
            controller.thread.join()
            for sig, handler in previous.items():
                signal.signal(sig, handler)
    except Exception as exc:
        result = {'error': str(exc), 'stopped': False, 'returncode': None, 'logfile': None}
        if options.events_json:
            print(json.dumps({'event': 'ready' if options.check else 'finished', 'data': result}, ensure_ascii=False), flush=True)
    if result.get('error'):
        if not options.events_json:
            print(result['error'], file=sys.stderr)
        return 1
    if result.get('stopped'):
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
