"""保存识别结果与按许可证编号去重的本地录入记录。"""

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile


HISTORY_FILENAME = "records.json"
HISTORY_LOCK_FILENAME = ".records.lock"


def write_output(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    # 同目录替换，读取方只会看到写入完成的文件。
    stream = NamedTemporaryFile(dir=path.parent, delete=False)
    temp_path = Path(stream.name)
    try:
        with stream:
            stream.write(data)
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_json(path, data):
    write_output(path, (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _lock_history(stream):
    # 锁单独的文件，records.json 自身可以继续原子替换。
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)


def _read_history(path):
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RuntimeError(f"无法读取录入历史 {path}") from exc
    if not isinstance(records, dict):
        raise RuntimeError(f"录入历史格式错误 {path}")
    return records


def lookup_or_register(path, number, report, ready):
    """返回是否本次新增及首次录入时间。关闭锁文件即释放锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(HISTORY_LOCK_FILENAME).open("a+b") as lock:
        _lock_history(lock)
        records = _read_history(path)
        key = number.upper()
        if key in records:
            record = records[key]
            if not isinstance(record, dict) or not isinstance(record.get("录入时间"), str):
                raise RuntimeError(f"编号 {number} 的录入记录缺少有效时间")
            return False, record["录入时间"]
        if not ready:
            return False, None

        entered_at = datetime.now().astimezone().isoformat(timespec="seconds")
        records[key] = {"许可证编号": number, "录入时间": entered_at, "字段": report}
        write_json(path, records)
        return True, entered_at
