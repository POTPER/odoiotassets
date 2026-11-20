"""Per-user GUI lock and atomic activation requests, without network services."""
import errno
import hmac
import json
import os
from pathlib import Path
import secrets
import time

from core import SyncError, atomic_json


class SingleInstance:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.endpoint = self.directory / "window.json"
        self.request = self.directory / "activate.json"
        self.stream = None
        self.token = None
        self.last_request = None
        self.existing_display = ""
        self.activation_succeeded = False

    def _try_lock(self):
        path = self.directory / "window.lock"
        if path.is_symlink():
            raise SyncError("启动器实例锁不能是符号链接。")
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.set_inheritable(fd, False)
        stream = os.fdopen(fd, "r+b", buffering=0)
        try:
            if os.name == "nt":
                import msvcrt
                # Windows permits locking a byte beyond EOF. Writing before
                # locking races another process that already owns this byte.
                stream.seek(0)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            if exc.errno in (errno.EACCES, errno.EAGAIN) or getattr(exc, "winerror", None) == 33:
                return False
            raise
        self.stream = stream
        return True

    def start_or_activate(self, timeout=5.0):
        if self.directory.is_symlink():
            raise SyncError("启动器实例目录不能是符号链接。")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            self.directory.chmod(0o700)
        deadline = time.monotonic() + timeout
        while True:
            if self._try_lock():
                try:
                    self._publish()
                except BaseException:
                    self.close()
                    raise
                return True
            if self._activate_existing():
                self.activation_succeeded = True
                return False
            if time.monotonic() >= deadline:
                # Even if metadata is temporarily unavailable, never start a second GUI.
                return False
            time.sleep(0.05)

    def _publish(self):
        if self.endpoint.is_symlink() or self.request.is_symlink():
            raise SyncError("启动器窗口记录不能是符号链接。")
        self.token = secrets.token_hex(32)
        atomic_json(self.endpoint, {"schema": 1, "pid": os.getpid(), "token": self.token,
                                    "display": os.environ.get("DISPLAY", "")})
        self.endpoint.chmod(0o600)

    def _activate_existing(self):
        try:
            if self.endpoint.is_symlink() or self.request.is_symlink():
                return False
            with self.endpoint.open("r", encoding="utf-8") as stream:
                data = json.loads(stream.read(4096))
            if not isinstance(data, dict) or data.get("schema") != 1:
                return False
            token = data.get("token")
            if not isinstance(token, str) or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
                return False
            atomic_json(self.request, {"token": token, "request_id": secrets.token_hex(16)})
            self.request.chmod(0o600)
            self.existing_display = data.get("display", "")
            return True
        except (OSError, ValueError, UnicodeError):
            return False

    def activation_requested(self):
        if self.stream is None or self.request.is_symlink():
            return False
        try:
            with self.request.open("r", encoding="utf-8") as stream:
                data = json.loads(stream.read(4096))
            token, request_id = data.get("token"), data.get("request_id")
            if (not isinstance(token, str) or not isinstance(request_id, str) or len(request_id) != 32 or
                    not hmac.compare_digest(token.encode("utf-8"), self.token.encode("ascii")) or request_id == self.last_request):
                return False
            self.last_request = request_id
            return True
        except (OSError, ValueError, UnicodeError, AttributeError):
            return False

    def close(self):
        if self.stream is not None:
            try:
                # Remove metadata while still owning the lock. Keep the lock file:
                # unlinking it could let later callers lock different file inodes.
                self.endpoint.unlink(missing_ok=True)
            finally:
                try:
                    if os.name == "nt":
                        import msvcrt
                        self.stream.seek(0)
                        msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
                finally:
                    self.stream.close()
                    self.stream = None
