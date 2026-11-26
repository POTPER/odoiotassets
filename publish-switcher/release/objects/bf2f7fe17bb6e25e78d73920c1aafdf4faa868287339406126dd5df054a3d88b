"""部署设置读写。

读写 ~/.config/publish-switcher/settings.json；保存时保留未知字段，避免丢工程师自定义项。
"""
from pathlib import Path

from publish_switcher.common.files import atomic_json, read_json


def read_settings(path):
    try:
        data = read_json(Path(path))
    except FileNotFoundError:
        return {}
    if not isinstance(data, dict):
        raise ValueError("设置文件格式无效。")
    return data


def save_settings(path, changes):
    data = read_settings(path)
    data.update(changes)
    atomic_json(path, data)
    return data
