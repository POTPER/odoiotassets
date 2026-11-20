"""Archive a target.py snapshot, then replace this process with the real Python."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
import os
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import configure
configure()

from core import operation_lock, fsync_dir, SyncError


@contextmanager
def archive_lock(path):
    deadline = time.monotonic() + 30
    while True:
        lock = operation_lock(path)
        try:
            lock.__enter__()
            break
        except SyncError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def script_argument(args):
    i = 0
    while i < len(args):
        value = args[i]
        if value == "-":
            return None
        if value == "--":
            return args[i + 1] if i + 1 < len(args) else None
        if value == "--check-hash-based-pycs":
            i += 2
        elif value.startswith("-"):
            if not value.startswith("--"):
                for index, flag in enumerate(value[1:]):
                    if flag in "cm":
                        return None
                    if flag in "WX":
                        if index == len(value) - 2:
                            i += 1
                        break
            i += 1
        else:
            return value
    return None


def archive_script(publish, archive, args):
    candidate = script_argument(args)
    if not candidate or Path(candidate).name != "target.py":
        return None
    source = Path(candidate).absolute()
    real = source.resolve()
    roots = [Path(publish).resolve() / name for name in ("app", "IoT", "iot")]
    if not any(root in real.parents for root in roots):
        return None
    destination = Path(archive).expanduser().absolute()
    if destination.resolve() == Path(publish).resolve() or Path(publish).resolve() in destination.resolve().parents:
        raise ValueError("收录目录必须位于 publish 外")
    destination.mkdir(parents=True, exist_ok=True)
    with archive_lock(destination / ".collection.lock"):
        for attempt in range(2):
            with source.open("rb") as stream:
                before = os.fstat(stream.fileno())
                raw = stream.read()
                after = os.fstat(stream.fileno())
            current = source.stat()
            fingerprint = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
            if fingerprint(before) == fingerprint(after) == fingerprint(current):
                break
        else:
            raise OSError("源码在读取过程中持续变化")
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d_%H%M%S_%f")
        stem = source.parent.name + "_" + stamp
        fd, temp = tempfile.mkstemp(prefix=".collect-", dir=str(destination))
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(raw)
                out.flush()
                os.fsync(out.fileno())
            suffix = 0
            while True:
                result = destination / (stem + ("_" + str(suffix) if suffix else "") + ".py")
                try:
                    # Exclusive reservation prevents replacing any existing history.
                    with result.open("xb"):
                        pass
                    break
                except FileExistsError:
                    suffix += 1
            try:
                os.replace(temp, result)
                fsync_dir(destination)
            except BaseException:
                result.unlink(missing_ok=True)
                raise
            return result
        finally:
            Path(temp).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-dir", required=True)
    parser.add_argument("--archive-dir", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("args", nargs=argparse.REMAINDER)
    options = parser.parse_args(argv)
    args = options.args[1:] if options.args[:1] == ["--"] else options.args
    try:
        archive_script(options.publish_dir, options.archive_dir, args)
    except Exception as exc:
        message = "收录失败，本次脚本未运行：" + str(exc)
        print(message, file=sys.stderr)
        try:
            from launcher_runtime import config_directory
            folder = config_directory() / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / "collector.log").open("a", encoding="utf-8") as log:
                log.write(datetime.now().isoformat() + " " + message + "\n")
        except OSError:
            pass
        return 125
    os.execv(options.python, [options.python] + args)


if __name__ == "__main__":
    raise SystemExit(main())
