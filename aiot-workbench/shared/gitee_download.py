"""Verified public Gitee blob downloads when the raw endpoint returns HTTP 403."""
import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from core import SyncError, check_cancel, fsync_dir, relative_path


# The complete workbench includes offline dependencies (~34 MiB). Allow that
# package with bounded memory; larger installers must use a Releases source.
MAX_BLOB_FILE_BYTES = 64 * 1024 * 1024


def blob_sha(source, location, size, expected, cancel):
    relative_path(location)
    if expected.startswith("git:"):
        sha = expected[4:]
    else:
        # SHA-256 catalogs do not necessarily supply a Git blob hash. Resolve the
        # path from the exact pinned commit; never fall back to a moving branch.
        tree = json.loads(source.fetch_bytes(source.tree_url(), cancel=cancel))
        if not isinstance(tree, dict) or tree.get("truncated") or not isinstance(tree.get("tree"), list):
            raise SyncError("Gitee 固定提交目录树不完整，不能确定下载对象：" + location)
        entries = [n for n in tree["tree"] if n.get("path") == location and n.get("type") == "blob"
                   and n.get("mode") in ("100644", "100755") and n.get("size") == size]
        if len(entries) != 1:
            raise SyncError("Gitee 固定提交中找不到大小一致的普通文件：" + location)
        sha = entries[0].get("sha", "")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SyncError("Gitee 返回无效的文件 Blob SHA：" + location)
    return sha


def download_blob(source, location, dest, size, expected, cancel, progress):
    check_cancel(cancel)
    if size > MAX_BLOB_FILE_BYTES:
        raise SyncError("Gitee raw 拒绝下载，文件超过本工具 Blob API 的 64 MiB 安全范围：{}。"
                        "请登录 Gitee 下载后手动复制，或配置 Releases HTTPS 来源。".format(location))
    sha = blob_sha(source, location, size, expected, cancel)
    url = source.api_base + "/git/blobs/" + sha
    # Base64 plus line wrapping and JSON metadata, with a firm response bound.
    limit = ((size + 2) // 3 * 4) * 110 // 100 + 1024 * 1024
    raw = source.fetch_bytes(url, limit=limit, cancel=cancel)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise SyncError("Gitee Blob API 返回无效 JSON：" + location) from exc
    del raw
    if (not isinstance(data, dict) or data.get("encoding") != "base64" or data.get("sha") != sha
            or type(data.get("size")) is not int or data["size"] != size or not isinstance(data.get("content"), str)):
        raise SyncError("Gitee Blob API 的大小、哈希或编码与清单不一致：" + location)
    content = "".join(data.pop("content").split())
    if len(content) % 4 or "=" in content[:-2]:
        raise SyncError("Gitee Blob API 的 Base64 内容不完整：" + location)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".part-" + uuid.uuid4().hex)
    sha256 = hashlib.sha256()
    git = hashlib.sha1("blob {}\0".format(size).encode())
    count = 0
    try:
        with temporary.open("wb") as stream:
            for offset in range(0, len(content), 1024 * 1024):
                check_cancel(cancel)
                try:
                    chunk = base64.b64decode(content[offset:offset + 1024 * 1024], validate=True)
                except (ValueError, binascii.Error) as exc:
                    raise SyncError("Gitee Blob API 的 Base64 内容无效：" + location) from exc
                count += len(chunk)
                if count > size:
                    raise SyncError("Gitee Blob API 的文件大于清单大小：" + location)
                stream.write(chunk)
                sha256.update(chunk)
                git.update(chunk)
                progress(len(chunk))
            stream.flush()
            os.fsync(stream.fileno())
        check_cancel(cancel)
        actual = "git:" + git.hexdigest() if expected.startswith("git:") else sha256.hexdigest()
        if count != size or git.hexdigest() != sha or actual != expected:
            raise SyncError("Gitee Blob API 下载不完整或校验失败：{}（实际 {} / 清单 {} 字节）".format(location, count, size))
        os.replace(temporary, dest)
        fsync_dir(dest.parent)
    finally:
        temporary.unlink(missing_ok=True)
