"""Recoverable, session-only PythonExePath overlay. Caller owns Engine.lock()."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys

from core import SyncError, atomic_json, fsync_dir, read_json


def _replace_bytes(path, raw):
    temp = path.with_name("." + path.name + ".collector.tmp")
    try:
        mode = path.stat().st_mode & 0o777
        with temp.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(mode)
        os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def recover_overlay(engine):
    record = engine.state / "collection-session.json"
    if not record.exists():
        return False
    engine.preflight()
    data = read_json(record)
    path = engine.target / "TrainTaskInfo.json"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() == data["patched_sha256"]:
        _replace_bytes(path, base64.b64decode(data["original"]))
    else:
        tasks = json.loads(raw.decode("utf-8-sig"))
        changed = False
        for task in tasks:
            if task.get("PythonExePath") in data["interpreters"]:
                task["PythonExePath"] = data["interpreters"][task["PythonExePath"]]
                changed = True
        if changed:
            _replace_bytes(path, json.dumps(tasks, ensure_ascii=False, indent=2).encode("utf-8"))
    record.unlink()
    fsync_dir(record.parent)
    return True


def prepare_overlay(engine, archive):
    path = engine.target / "TrainTaskInfo.json"
    original = path.read_bytes()
    tasks = json.loads(original.decode("utf-8-sig"))
    mapping = {}
    folder = engine.state / "python-wrappers"
    if folder.is_symlink():
        raise SyncError("收录入口目录不能是符号链接")
    folder.mkdir(exist_ok=True)
    for task in tasks:
        # Fixtures and non-Python tasks may omit the interpreter field.
        value = task.get("PythonExePath")
        if not value:
            continue
        real = shutil.which(value)
        if real is None:
            raise SyncError("找不到任务的 Python 解释器：" + str(value))
        # Do not resolve symlinks: venv/bin/python must retain its venv identity.
        real = os.path.abspath(real)
        wrapper = folder / ("python-" + hashlib.sha256(real.encode()).hexdigest()[:20])
        command = [sys.executable, str(Path(__file__).with_name("collector.py")),
                   "--publish-dir", str(engine.target), "--archive-dir", str(archive), "--python", real, "--"]
        content = "#!/usr/bin/env bash\nexec " + " ".join(shlex.quote(arg) for arg in command) + ' "$@"\n'
        if wrapper.is_symlink():
            raise SyncError("收录入口不能是符号链接")
        with wrapper.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        wrapper.chmod(0o755)
        mapping[str(wrapper)] = value
        task["PythonExePath"] = str(wrapper)
    if not mapping:
        return
    patched = json.dumps(tasks, ensure_ascii=False, indent=2).encode("utf-8")
    atomic_json(engine.state / "collection-session.json", {
        "original": base64.b64encode(original).decode("ascii"), "interpreters": mapping,
        "patched_sha256": hashlib.sha256(patched).hexdigest()})
    _replace_bytes(path, patched)
