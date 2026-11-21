"""方案清单与目录树校验。

校验 catalog / manifest 结构，判断路径是否属于同步范围，并检查更新阻断条件。
"""
from __future__ import annotations

import os
import posixpath
import re
import urllib.request
from publish_switcher.sync.formats import DEFAULT_EXTENSIONS, file_extension
from pathlib import PurePosixPath
from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import relative_path


def managed(path):
    return file_extension(path) in DEFAULT_EXTENSIONS


def asset_file(path):
    parts = PurePosixPath(path).parts
    return len(parts) > 1 and parts[0].casefold() == "assets"


def sync_blockers(manifest, paths=None, manages=managed):
    empty = [e["path"] for e in manifest["entries"] if e["type"] == "file" and manages(e["path"])
             and (paths is None or e["path"] in paths)
             and e["size"] == 0 and e["path"] not in manifest.get("allowed_empty", [])]
    unavailable = [e["path"] for e in manifest["entries"] if e["type"] == "file" and manages(e["path"])
                   and (paths is None or e["path"] in paths) and e.get("payload_available") is False]
    reasons = []
    if empty:
        reasons.append("待同步的文件为空，请补齐或显式允许：\n" + "\n".join(empty))
    if unavailable:
        reasons.append("清单仅记录了元数据，发布包没有这些文件内容。请使用 generate.py --extensions 重新发布：\n" + "\n".join(unavailable))
    return "\n".join(reasons)


def sha_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise SyncError("SHA-256 必须是 64 位小写十六进制字符串。")
    return value


def validate_source(source):
    if not isinstance(source, str):
        raise SyncError("下载来源必须是字符串。")
    if source.startswith("https://"):
        url = urllib.parse.urlsplit(source)
        if not url.hostname or url.username or url.password or url.fragment:
            raise SyncError("无效 HTTPS 下载地址。")
    else:
        relative_path(source)
    return source


def validate_manifest(data, allow_empty_entries=False):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SyncError("不支持的资源清单格式。")
    if not isinstance(data.get("id"), str) or not data["id"]:
        raise SyncError("清单缺少方案 ID。")
    if not isinstance(data.get("version"), str) or not data["version"]:
        raise SyncError("清单缺少版本。")
    if not isinstance(data.get("root_mode", "0755"), str) or not re.fullmatch(r"0[0-7]{3}", data.get("root_mode", "0755")):
        raise SyncError("无效根目录权限。")
    entries = data.get("entries")
    allowed_empty = data.get("allowed_empty", [])
    if not isinstance(allowed_empty, list):
        raise SyncError("allowed_empty 必须是相对路径数组。")
    for path in allowed_empty:
        relative_path(path)
    if not isinstance(entries, list) or (not entries and not allow_empty_entries):
        raise SyncError("清单必须包含非空 entries，禁止意外清空整个目录。")
    by_path = {}
    folded = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SyncError("清单条目必须是对象。")
        path = relative_path(entry.get("path"))
        if path in by_path or (os.name == "nt" and path.casefold() in folded):
            raise SyncError(f"重复或本机无法区分的路径：{path}")
        folded.add(path.casefold())
        kind = entry.get("type")
        if kind not in ("file", "directory", "symlink"):
            raise SyncError(f"不支持的文件类型：{path}")
        if kind != "symlink":
            mode = entry.get("mode")
            if not isinstance(mode, str) or not re.fullmatch(r"0[0-7]{3}", mode):
                raise SyncError(f"无效权限（只允许普通 rwx 权限）：{path}")
        if kind == "file":
            if type(entry.get("size")) is not int or entry["size"] < 0:
                raise SyncError(f"无效文件大小：{path}")
            if "sha256" in entry:
                sha_value(entry["sha256"])
            elif not isinstance(entry.get("git_sha1"), str) or not re.fullmatch(r"[0-9a-f]{40}", entry["git_sha1"]):
                raise SyncError(f"文件缺少 SHA-256 或 Git blob SHA-1：{path}")
            validate_source(entry.get("source"))
        elif kind == "symlink":
            target = entry.get("target")
            if (not isinstance(target, str) or not target or target.startswith("/")
                    or "\\" in target or ":" in target or "\x00" in target):
                raise SyncError(f"无效符号链接：{path}")
        by_path[path] = entry
    for path in by_path:
        parent = posixpath.dirname(path)
        while parent:
            if parent not in by_path or by_path[parent]["type"] != "directory":
                raise SyncError(f"父目录必须显式列出且不能是符号链接：{path}")
            parent = posixpath.dirname(parent)

    def resolve_link(path, seen):
        if path in seen:
            raise SyncError(f"符号链接形成循环：{path}")
        entry = by_path[path]
        dest = posixpath.normpath(posixpath.join(posixpath.dirname(path), entry["target"]))
        if dest == ".." or dest.startswith("../") or dest.startswith("/"):
            raise SyncError(f"符号链接越出 publish：{path}")
        # Resolve links in any component without following host filesystem links.
        parts = dest.split("/") if dest != "." else []
        for i in range(len(parts)):
            prefix = "/".join(parts[:i + 1])
            if prefix in by_path and by_path[prefix]["type"] == "symlink":
                resolved = resolve_link(prefix, seen | {path})
                rest = "/".join(parts[i + 1:])
                dest = posixpath.normpath(posixpath.join(resolved, rest))
                break
        if dest != "." and dest not in by_path:
            raise SyncError(f"符号链接目标不存在：{path} -> {dest}")
        return dest

    for path, entry in by_path.items():
        if entry["type"] == "symlink":
            resolve_link(path, set())
    return data


def validate_catalog(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise SyncError("不支持的方案目录格式。")
    if not isinstance(data.get("profiles"), list):
        raise SyncError("目录缺少 profiles 列表。")
    ids = set()
    for p in data["profiles"]:
        if not isinstance(p, dict):
            raise SyncError("无效方案条目。")
        for key in ("id", "name", "version"):
            if not isinstance(p.get(key), str) or not p[key]:
                raise SyncError(f"方案缺少 {key}。")
        if p["id"] in ids:
            raise SyncError("方案 ID 重复。")
        ids.add(p["id"])
        relative_path(p.get("manifest"))
        sha_value(p.get("sha256"))
    return data
