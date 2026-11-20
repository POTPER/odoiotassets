"""Linux detection and identity-checked stopping for one AIoT deployment."""
import os
from pathlib import Path
import sys
import signal
import time

from compat import remove_suffix
from core import SyncError


def find_running_aiot(publish, exclude_pids=(), proc_root=None):
    if proc_root is None and sys.platform != "linux":
        return []
    target = Path(publish).expanduser().resolve()
    processes = Path(proc_root) if proc_root is not None else Path('/proc')
    ignored = {os.getpid(), *exclude_pids}
    found = []
    for proc in processes.iterdir():
        if not proc.name.isascii() or not proc.name.isdigit() or int(proc.name) in ignored:
            continue
        try:
            state = (proc / 'stat').read_text(errors='replace').rpartition(') ')[2].split()
            if not state or state[0] in ('Z', 'X'):
                continue
            executable = Path(remove_suffix(os.readlink(proc / 'exe'), ' (deleted)')).resolve()
            matches = executable == target / 'AIotApp'
            if not matches and executable.name == 'dotnet':
                args = (proc / 'cmdline').read_bytes().decode('utf-8', errors='replace').split('\0')
                cwd = Path(os.readlink(proc / 'cwd'))
                matches = any(arg and not arg.startswith('-') and (cwd / arg).resolve() == target / 'AIotApp.dll'
                              for arg in args[1:])
            if matches:
                found.append(int(proc.name))
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            try:
                name = (proc / 'comm').read_text().strip()
            except OSError:
                name = ''
            if name == 'AIotApp':
                raise SyncError('无法检查 AIoT 进程 {}，请确认该程序的运行用户。'.format(proc.name))
    return sorted(found)


def _record(proc):
    try:
        fields = (proc / 'stat').read_text(errors='replace').rpartition(') ')[2].split()
        if len(fields) < 20 or fields[0] in ('Z', 'X'):
            return None
        return {'pid': int(proc.name), 'parent': int(fields[1]), 'group': int(fields[2]),
                'session': int(fields[3]), 'started': int(fields[19])}
    except (FileNotFoundError, ProcessLookupError):
        return None


def _alive(record, processes):
    current = _record(processes / str(record['pid']))
    return current is not None and current['started'] == record['started']


def owned_group_alive(process):
    """Ignore zombies when checking a group created with start_new_session."""
    processes = Path('/proc')
    if process.returncode is not None:
        # A live leader with a reaped child's PID belongs to a later process.
        try:
            if _record(processes / str(process.pid)) is not None:
                return False
        except PermissionError:
            return False
    for proc in processes.iterdir():
        if not proc.name.isascii() or not proc.name.isdigit():
            continue
        try:
            record = _record(proc)
        except PermissionError:
            continue
        if record and record['group'] == record['session'] == process.pid:
            return True
    return False


def stop_existing_aiot(publish, timeout=5.0, proc_root=None, log=lambda message: None):
    if proc_root is None and sys.platform != 'linux':
        raise SyncError('停止已有 AIoT 需要 Ubuntu 环境。')
    processes = Path(proc_root) if proc_root is not None else Path('/proc')
    roots = find_running_aiot(publish, proc_root=processes)
    records = {}
    for proc in processes.iterdir():
        if not proc.name.isascii() or not proc.name.isdigit():
            continue
        try:
            record = _record(proc)
        except PermissionError:
            if int(proc.name) in roots:
                raise SyncError('无法核验 AIoT 进程身份，停止操作已取消。')
            continue
        if record is not None:
            records[record['pid']] = record
    # Check the root executable again after taking the PID/start-time snapshot.
    verified = set(find_running_aiot(publish, proc_root=processes))
    selected = {pid for pid in roots if pid in verified and pid in records and _alive(records[pid], processes)}
    roots = set(selected)
    while True:
        children = {pid for pid, record in records.items() if record['parent'] in selected}
        expanded = selected | children
        if expanded == selected:
            break
        selected = expanded
    selected.discard(os.getpid())
    owned = [records[pid] for pid in sorted(selected)]

    def send(record, sig):
        if not _alive(record, processes):
            return
        if record['pid'] in roots and record['pid'] not in find_running_aiot(publish, proc_root=processes):
            return
        if not _alive(record, processes):
            return
        try:
            os.kill(record['pid'], sig)
            log('已发送 {}：进程 {}'.format(signal.Signals(sig).name, record['pid']))
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise SyncError('没有权限停止 AIoT 或其任务进程：' + str(record['pid'])) from exc

    for record in owned:
        send(record, signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while any(_alive(record, processes) for record in owned) and time.monotonic() < deadline:
        time.sleep(0.05)
    remaining = [record for record in owned if _alive(record, processes)]
    for record in remaining:
        send(record, signal.SIGKILL)
    deadline = time.monotonic() + 2.0
    while any(_alive(record, processes) for record in remaining) and time.monotonic() < deadline:
        time.sleep(0.05)
    if any(_alive(record, processes) for record in remaining):
        raise SyncError('AIoT 或任务进程未能结束，请检查运行日志。')
    return {'stopped_pids': sorted(selected), 'remaining_pids': find_running_aiot(publish, proc_root=processes)}
