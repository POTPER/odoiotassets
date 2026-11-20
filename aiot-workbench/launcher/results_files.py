"""Results listing and explicit, non-overwriting local file submission."""
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import threading

from compat import is_relative_to
from core import SyncError, fsync_dir


class SubmissionCancelled(SyncError):
    pass


def validate_submission_directories(source, destination, publish_dir=None):
    if not isinstance(destination, str) or not destination.strip() or "\x00" in destination:
        raise SyncError("请先选择提交目标文件夹。")
    target = Path(destination).expanduser()
    if not target.is_absolute():
        raise SyncError("提交目标必须为绝对路径。")
    if target.exists() and not target.is_dir():
        raise SyncError("提交目标指向文件，请选择文件夹。")
    root, target = Path(source).expanduser().resolve(), target.resolve()
    if is_relative_to(target, root) or is_relative_to(root, target):
        raise SyncError("成果目录与提交目标不能相同或互相包含，请选择独立的提交文件夹。")
    if publish_dir:
        publish = Path(publish_dir).expanduser().resolve()
        if is_relative_to(target, publish) or is_relative_to(publish, target):
            raise SyncError('提交目标必须位于 publish 目录之外，且不能包含 publish；请另选成果提交文件夹。')
    return target


def source_path(root, relative, directory=False):
    relative = str(relative)
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or ".." in parts or "\\" in relative:
        raise SyncError("成果文件路径无效。")
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise SyncError("不支持通过链接访问成果文件：" + relative)
    if not is_relative_to(path.resolve(), root):
        raise SyncError("成果文件超出了成果目录。")
    if not (path.is_dir() if directory else path.is_file()):
        raise SyncError("成果文件已移动或不可访问：" + relative)
    return path


def list_results(root, relative=""):
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    current = source_path(root, relative, directory=True) if relative else root
    rows = []
    with os.scandir(str(current)) as entries:
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue  # AIoT may rename a just-written result during refresh.
            kind = "link" if entry.is_symlink() else "directory" if stat.S_ISDIR(info.st_mode) else "file" if stat.S_ISREG(info.st_mode) else "other"
            rows.append({"name": entry.name, "relative": (current / entry.name).relative_to(root).as_posix(),
                         "kind": kind, "size": info.st_size, "modified": info.st_mtime})
    return sorted(rows, key=lambda row: (row["kind"] != "directory", row["name"].casefold(), row["name"]))


def _fingerprint(info):
    # Windows ctime describes creation time, and stat/fstat can disagree about it.
    # POSIX ctime is a useful change detector; retain it on deployment devices.
    changed = info.st_ctime_ns if os.name != "nt" else None
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, changed


def _cancelled(cancel):
    if cancel.is_set():
        raise SubmissionCancelled("成果提交已取消。")


def _stage_file(root, relative, staged, cancel):
    for attempt in range(2):
        _cancelled(cancel)
        path = source_path(root, relative)
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source, staged.open("wb") as target:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise SyncError("只能提交普通文件：" + relative)
            copied = 0
            while True:
                _cancelled(cancel)
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                copied += len(chunk)
            target.flush()
            os.fsync(target.fileno())
            after = os.fstat(source.fileno())
        current = source_path(root, relative).stat()
        if _fingerprint(before) == _fingerprint(after) == _fingerprint(current) and copied == before.st_size:
            return
        if attempt:
            raise SyncError("成果文件正在变化，请稍后再提交：" + relative)


def _parents(target, relative, created):
    parent = target
    for part in PurePosixPath(relative).parts[:-1]:
        parent = parent / part
        if parent.is_symlink():
            raise SyncError("提交目标的子目录不能是链接。")
        try:
            parent.mkdir()
            created.append(parent)
        except FileExistsError:
            if not parent.is_dir():
                raise SyncError("提交目标存在同名文件，无法创建子目录。")
    return parent


def copy_submission(source, destination, relatives, enabled=False, cancel=None, progress=lambda done, total: None, publish_dir=None):
    if enabled is not True:
        raise SyncError("成果提交未开启，请在设置中开启。")
    root = Path(source).expanduser().resolve()
    target = validate_submission_directories(root, str(destination), publish_dir=publish_dir)
    files = list(dict.fromkeys(str(value) for value in relatives))
    if not files:
        raise SyncError("请先勾选需要提交的文件。")
    for relative in files:
        source_path(root, relative)
    cancel = cancel if cancel is not None else threading.Event()
    _cancelled(cancel)
    target.mkdir(parents=True, exist_ok=True)
    committed, parents = [], []
    try:
        with tempfile.TemporaryDirectory(prefix=".aiot-submit-", dir=str(target)) as staging:
            stage = Path(staging)
            for index, relative in enumerate(files):
                _stage_file(root, relative, stage / str(index), cancel)
                progress(index + 1, len(files))
            for index, relative in enumerate(files):
                _cancelled(cancel)
                parent = _parents(target, relative, parents)
                original = PurePosixPath(relative).name
                name, counter = original, 1
                while True:
                    output = parent / name
                    try:
                        with output.open("xb"):
                            pass
                        break
                    except FileExistsError:
                        counter += 1
                        item = Path(original)
                        name = item.stem + "_" + str(counter) + item.suffix
                try:
                    os.replace(stage / str(index), output)
                except BaseException:
                    output.unlink(missing_ok=True)
                    raise
                committed.append((output, _fingerprint(output.stat())))
                fsync_dir(parent)
            _cancelled(cancel)
        return [path for path, _ in committed]
    except BaseException:
        for path, fingerprint in reversed(committed):
            try:
                if _fingerprint(path.stat()) == fingerprint:
                    path.unlink()
            except OSError:
                pass
        for parent in reversed(parents):
            try:
                parent.rmdir()
            except OSError:
                pass
        raise
