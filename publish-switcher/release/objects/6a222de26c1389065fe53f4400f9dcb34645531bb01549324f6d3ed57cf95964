"""文件内容指纹。

计算 SHA-256 / Git blob SHA，用于比较本地文件与仓库清单是否一致。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from publish_switcher.common.errors import check_cancel


def digest(path, cancel=None, git=False):
    """返回路径内容的摘要；git=True 时按 Git blob 规则计算。"""
    hashes = fingerprints(path, cancel)
    return hashes[1] if git else hashes[0]


def fingerprints(path, cancel=None):
    h = hashlib.sha256()
    g = hashlib.sha1(f"blob {Path(path).stat().st_size}\0".encode())
    with open(path, "rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancel(cancel)
            h.update(chunk)
            g.update(chunk)
    return h.hexdigest(), g.hexdigest()


def hash_field(entry):
    return "sha256" if "sha256" in entry else "git_sha1"


def content_matches(actual, entry):
    key = hash_field(entry)
    return actual and actual["type"] == "file" and actual["size"] == entry["size"] and actual.get(key) == entry[key]


def equivalent(actual, desired):
    keys = ["type"]
    if desired["type"] == "file":
        keys += ["size", hash_field(desired)]
    elif desired["type"] == "symlink":
        keys += ["target"]
    if os.name == "posix" and desired["type"] != "symlink":
        keys += ["mode"]
    return all(actual.get(k) == desired.get(k) for k in keys)
