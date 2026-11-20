"""Recoverable deployment preferences; preserve corrupt input for diagnosis."""
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import uuid

from core import SyncError, atomic_json, fsync_dir


def backup_path(path):
    path = Path(path)
    return path.with_name(path.name + '.bak')


def _decode(raw):
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data, dict) or not isinstance(data.get('publish_dir'), str) or not data['publish_dir'].strip() or '\x00' in data['publish_dir']:
        raise ValueError('缺少有效的 publish_dir')
    return data


def _backup_data(path):
    try:
        return _decode(backup_path(path).read_bytes())
    except (OSError, ValueError, UnicodeError):
        return None


def _refresh_backup(path, data):
    if _backup_data(path) == data:
        return
    try:
        atomic_json(backup_path(path), data)
    except OSError as exc:
        # The main settings have already succeeded; do not report them as unsaved.
        logging.getLogger(__name__).warning('设置有效，但备份未更新：%s', exc)


def _preserve_corrupt(path, raw):
    name = path.name + '.corrupt-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '-' + uuid.uuid4().hex[:8]
    saved = path.with_name(name)
    with saved.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    fsync_dir(path.parent)
    return saved


def read_settings(path, default=None, *, read_only=False):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        recovered = _backup_data(path)
        if recovered is not None:
            if not read_only:
                atomic_json(path, recovered)
                logging.getLogger(__name__).warning('设置文件缺失，已从有效备份恢复：%s', path)
            return recovered
        return dict(default) if default is not None else None
    try:
        data = _decode(raw)
    except (ValueError, UnicodeError) as exc:
        recovered = _backup_data(path)
        if recovered is not None:
            if not read_only:
                saved = _preserve_corrupt(path, raw)
                atomic_json(path, recovered)
                logging.getLogger(__name__).warning('设置损坏，已从有效备份恢复；原文件保留在：%s', saved)
            return recovered
        if default is not None:
            if not read_only:
                saved = _preserve_corrupt(path, raw)
                logging.getLogger(__name__).warning('设置及备份无效，将按指定安装目录重建设置；原文件保留在：%s', saved)
            return dict(default)
        raise SyncError('启动器设置损坏且没有有效备份：{}。请运行 bash install-launcher.sh /实际publish路径 重建设置，原文件将保留。'.format(path)) from exc
    if not read_only:
        _refresh_backup(path, data)
    return data


def write_settings(path, data):
    _decode(json.dumps(data, ensure_ascii=False).encode('utf-8'))
    atomic_json(Path(path), data)
    _refresh_backup(path, data)
