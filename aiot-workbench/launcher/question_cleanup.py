"""Reversible removal of generated task files. Caller owns the publish lock."""
import os
from pathlib import PurePosixPath
import stat

from compat import is_relative_to
from core import SyncError, fsync_dir, relative_path


TASK_ROOTS = ("app", "IoT", "iot")


def _link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _identity(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns]


def _safe_path(root, relative):
    relative_path(relative)
    parts = PurePosixPath(relative).parts
    path = root
    if _link(root.lstat()) or not root.is_dir():
        raise SyncError("清理目录不是普通目录：" + str(root))
    for part in parts:
        path = path / part
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if _link(info):
            raise SyncError("清理路径不能经过链接：" + relative)
    resolved = path.resolve()
    if resolved == root.resolve() or not is_relative_to(resolved, root.resolve()):
        raise SyncError("清理路径超出目录：" + relative)
    return path


def plan_cleanup(target):
    entries, visited = [], set()
    def visit(directory):
        with os.scandir(directory) as scan:
            children = sorted(scan, key=lambda item: item.name)
        for child in children:
            path = directory / child.name
            # DirEntry metadata omits file identity on older Windows/Python.
            info = path.lstat()
            if _link(info):
                continue
            relative = path.relative_to(target).as_posix()
            if child.name == "target.py" and stat.S_ISREG(info.st_mode):
                entries.append({"path": relative, "kind": "file", "identity": _identity(info)})
            elif child.name == "student_data" and stat.S_ISDIR(info.st_mode):
                entries.append({"path": relative, "kind": "directory", "identity": _identity(info)})
            elif stat.S_ISDIR(info.st_mode):
                visit(_safe_path(target, relative))
    for name in TASK_ROOTS:
        root = target / name
        try:
            info = root.lstat()
        except FileNotFoundError:
            continue
        if _link(info) or not stat.S_ISDIR(info.st_mode) or root.resolve() in visited:
            continue
        visited.add(root.resolve())
        # Only task subdirectories, never publish itself or its config templates.
        with os.scandir(root) as scan:
            tasks = sorted(scan, key=lambda item: item.name)
        for task in tasks:
            info = task.stat(follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode) and not _link(info):
                visit(_safe_path(target, (root / task.name).relative_to(target).as_posix()))
    return entries


def _paths(engine, backup, entries):
    if not isinstance(entries, list):
        raise SyncError("清理恢复记录无效。")
    root = backup / "task-files"
    if not root.exists():
        root.mkdir()
        fsync_dir(backup)
    seen, rows = set(), []
    for item in entries:
        relative = item["path"]
        relative_path(relative)
        parts = PurePosixPath(relative).parts
        valid = (len(parts) >= 3 and parts[0] in TASK_ROOTS and
                 ((item["kind"] == "file" and parts[-1] == "target.py") or
                  (item["kind"] == "directory" and parts[-1] == "student_data")))
        if not valid or relative in seen or any(relative.startswith(old + "/") or old.startswith(relative + "/") for old in seen):
            raise SyncError("清理恢复路径无效：" + relative)
        seen.add(relative)
        rows.append((item, _safe_path(engine.target, relative), _safe_path(root, relative)))
    return rows


def _make_parents(root, parent):
    relative = parent.relative_to(root).as_posix()
    if relative == ".":
        return
    _safe_path(root, relative)
    current = root
    for part in PurePosixPath(relative).parts:
        child = current / part
        if not child.exists():
            child.mkdir()
            fsync_dir(current)
        current = child


def move_cleanup(engine, backup, entries, log):
    for item, source, saved in _paths(engine, backup, entries):
        if _identity(source.lstat()) != item["identity"] or saved.exists():
            raise SyncError("清理期间任务文件发生变化：" + item["path"])
        _make_parents(backup, saved.parent)
        # Both absolute paths have been checked to stay in their designated roots.
        os.replace(source, saved)
        fsync_dir(source.parent)
        fsync_dir(saved.parent)
        log("已清理并备份：" + item["path"])


def restore_cleanup(engine, backup, entries):
    rows = _paths(engine, backup, entries)
    for item, source, saved in rows:
        if saved.exists():
            if source.exists() or _identity(saved.lstat()) != item["identity"]:
                raise SyncError("清理恢复遇到冲突，已保留备份：" + item["path"])
        elif not source.exists() or _identity(source.lstat()) != item["identity"]:
            raise SyncError("缺少清理恢复文件，已保留事务记录：" + item["path"])
    for item, source, saved in reversed(rows):
        if saved.exists():
            _make_parents(engine.target, source.parent)
            os.replace(saved, source)
            fsync_dir(source.parent)
            fsync_dir(saved.parent)


def cleanup_summary(entries):
    return {"target_files": sum(item["kind"] == "file" for item in entries),
            "student_data_dirs": sum(item["kind"] == "directory" for item in entries)}
