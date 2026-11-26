"""Assemble a complete tool installation from verified local and remote files."""
import hashlib
import logging
import os
from pathlib import Path
import shutil
import uuid

from publish_switcher.common.errors import check_cancel
from publish_switcher.repositories.source import transient_network_error
from publish_switcher.updates import release as updater


def matches(path, entry, cancel):
    if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            check_cancel(cancel)
            digest.update(block)
    return digest.hexdigest() == entry["sha256"]


def retryable(exc):
    while exc is not None:
        if transient_network_error(exc) or getattr(exc, "code", None) in (401, 403, 404):
            return True
        exc = exc.__cause__
    return False


def prepare(install, release, current, cancel, progress, *, on_attempt=None, on_plan=None):
    install = Path(install).absolute()
    state = updater.preparation_state(install, release, current)
    cache = state / "file-objects"
    if cache.is_symlink():
        raise updater.UpdateError("程序文件缓存不能是符号链接。")
    cache.mkdir(exist_ok=True)
    stage = state / ("stage-" + uuid.uuid4().hex)
    stage.mkdir()
    logger = logging.getLogger("publish-switcher")
    try:
        needed = {}
        sources = {}
        required_space = sum(((entry["size"] + 4095) // 4096 + 1) * 4096 for entry in release["files"])
        if shutil.disk_usage(install.parent).free < required_space * 2 + 16 * 1024 ** 2:
            raise updater.UpdateError("程序更新磁盘空间不足。")
        for entry in release["files"]:
            check_cancel(cancel)
            original = install / entry["path"]
            safe = not any(parent.is_symlink() for parent in original.parents if parent != install.parent)
            if safe and matches(original, entry, cancel):
                destination = stage / entry["path"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                if matches(destination, entry, cancel):
                    continue
                destination.unlink()
            cached = cache / entry["sha256"]
            if not matches(cached, entry, cancel):
                needed[entry["sha256"]] = entry
        total = sum(entry["size"] for entry in needed.values())
        logger.info("程序文件对比完成，需下载 %s 个对象，共 %s 字节", len(needed), total)
        if on_plan is not None:
            on_plan(total)
        completed = 0

        def reset():
            if on_attempt is not None:
                on_attempt()
                progress(completed)

        addresses = [address.rstrip("/") + "/" for address in
                     updater.mirror_locations(release["files_url"], release.get("mirror_repositories"))]
        for digest, entry in needed.items():
            check_cancel(cancel)
            for index, address in enumerate(addresses):
                try:
                    if address not in sources:
                        source, location = updater.remote_file(address + digest)
                        sources[address] = source, location[:-len(digest)]
                    source, prefix = sources[address]
                    source.download(prefix + digest, cache / digest, entry["size"], digest,
                                    cancel, progress, on_attempt=reset)
                    break
                except Exception as exc:
                    if index + 1 == len(addresses) or not retryable(exc):
                        raise
                    logger.warning("程序文件下载失败，尝试备用通道：%s", exc)
            completed += entry["size"]
        for entry in release["files"]:
            check_cancel(cancel)
            destination = stage / entry["path"]
            if not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(cache / entry["sha256"], destination)
            if not matches(destination, entry, cancel):
                raise updater.UpdateError("程序文件 SHA-256 校验失败：" + entry["path"])
            with destination.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            destination.chmod(entry["mode"])
        check_cancel(cancel)
        record = updater.finish_preparation(state, stage, release)
        record.update(download_bytes=total, downloaded_files=len(needed))
        return record
    except BaseException:
        shutil.rmtree(stage)
        raise
