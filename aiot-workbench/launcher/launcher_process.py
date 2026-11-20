"""Give launcher services identities distinct from Python task processes."""
import ctypes
import os
from pathlib import Path
import sys
import uuid


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import configure
configure()

ROLE_NAMES = {"desktop": "aiot-desktop", "gui": "aiot-launcher", "session": "aiot-session", "engineer": "aiot-engineer"}


def set_process_role(role):
    if sys.platform != "linux":
        return
    name = ROLE_NAMES[role].encode("ascii")
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    if prctl(15, name, 0, 0, 0) != 0:  # PR_SET_NAME, main thread before creating workers
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def install_interpreters(config_dir):
    result = {role: str(sys.executable) for role in ROLE_NAMES}
    # Preserve virtualenv prefix detection; role naming still protects those processes.
    if sys.platform != "linux" or sys.prefix != sys.base_prefix:
        return result
    from core import SyncError, fsync_dir
    root = Path(config_dir) / "runtime"
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise SyncError("启动器运行目录必须是普通目录：" + str(root))
    root.mkdir(parents=True, exist_ok=True)
    interpreter = Path(sys.executable).resolve()
    for role, name in ROLE_NAMES.items():
        alias = root / name
        if alias.exists() and not alias.is_symlink():
            raise SyncError("解释器入口已被其他文件占用：" + str(alias))
        temporary = root / (".interpreter-" + uuid.uuid4().hex)
        try:
            temporary.symlink_to(interpreter)
            os.replace(temporary, alias)
        finally:
            temporary.unlink(missing_ok=True)
        result[role] = str(alias.absolute())
    fsync_dir(root)
    return result


def interpreter_for(role):
    current = Path(sys.executable)
    if current.name in ROLE_NAMES.values():
        candidate = current.with_name(ROLE_NAMES[role])
        try:
            if candidate.is_file() and os.path.samefile(candidate, current):
                return str(candidate)
        except OSError:
            pass
    return str(sys.executable)
