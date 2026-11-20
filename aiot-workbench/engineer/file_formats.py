"""File-format selection and manifest inventory; shared by GUI, CLI and engine."""
import re
from pathlib import PurePosixPath


DEFAULT_EXTENSIONS = (".json", ".py", ".ttf")
LEGACY_EXTENSIONS = (".json", ".py")
NO_EXTENSION = "<none>"


def normalize_extensions(values=None):
    if values is None:
        return DEFAULT_EXTENSIONS
    if isinstance(values, str):
        values = values.split(",")
    if not isinstance(values, (list, tuple, set)):
        raise ValueError("文件格式必须是扩展名列表，例如 .py,.json,.ttf。")
    result = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("文件格式必须是字符串。")
        value = value.strip().lower()
        if value != NO_EXTENSION and not re.fullmatch(r"\.[^./\\\s\x00-\x1f,]+", value):
            raise ValueError("无效文件格式：{}；请填写 .ttf 等扩展名，无扩展名用 <none>。".format(value))
        result.add(value)
    return tuple(sorted(result))


def file_extension(path):
    return PurePosixPath(path).suffix.lower() or NO_EXTENSION


def label(extension):
    return "无扩展名" if extension == NO_EXTENSION else extension


def describe(extensions):
    return "、".join(label(ext) for ext in extensions) or "未选择格式"


def inventory(manifest):
    result = {}
    for entry in manifest["entries"]:
        if entry["type"] != "file":
            continue
        ext = file_extension(entry["path"])
        item = result.setdefault(ext, {"extension": ext, "count": 0, "bytes": 0, "unavailable": 0})
        item["count"] += 1
        item["bytes"] += entry["size"]
        item["unavailable"] += entry.get("payload_available") is False
    return [result[ext] for ext in sorted(result)]
