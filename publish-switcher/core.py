"""Deployment scoped by selected file formats; preserve other resources."""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import logging
import os
import posixpath
import re
import shutil
import stat
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path, PurePosixPath
from compat import is_relative_to, remove_suffix
from file_formats import DEFAULT_EXTENSIONS, LEGACY_EXTENSIONS, normalize_extensions, file_extension, describe


class SyncError(Exception):
    pass


class AccessDenied(urllib.error.HTTPError):
    """Keep HTTP status handling while exposing the refused endpoint to users."""
    def __str__(self):
        parsed = urllib.parse.urlsplit(self.url)
        address = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if parsed.hostname == "gitee.com" and parsed.path.startswith("/api/"):
            return ("Gitee API 拒绝访问（HTTP 403）：" + address +
                    "。无法获取对应仓库数据，可能涉及平台访问策略或接口限额。"
                    "请稍后重试，或在设置中选择可访问的仓库／使用已完整缓存的离线方案。")
        return "服务器拒绝访问（HTTP 403）：" + address


class Cancelled(SyncError):
    pass


NETWORK_ATTEMPTS = 3


def transient_network_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in (408, 429, 500, 502, 503, 504)
    if isinstance(exc, urllib.error.URLError):
        return not isinstance(exc.reason, ssl.SSLCertVerificationError)
    return isinstance(exc, (http.client.IncompleteRead, http.client.RemoteDisconnected,
                            TimeoutError, ConnectionError, ssl.SSLEOFError))


def retry_pause(exc, attempt, url, cancel=None):
    delay = attempt
    logging.getLogger("publish-switcher").warning(
        "网络读取中断，%s 秒后重试（第 %s/%s 次）：%s；%s", delay, attempt + 1, NETWORK_ATTEMPTS, url, exc)
    if cancel:
        if cancel.wait(delay):
            raise Cancelled("操作已取消，当前 publish 未修改。")
    else:
        time.sleep(delay)


def check_cancel(cancel):
    if cancel and cancel.is_set():
        raise Cancelled("操作已取消，当前 publish 未修改。")


def digest(path, cancel=None, git=False):
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


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def fsync_dir(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SyncError(f"无效相对路径：{value!r}")
    parts = value.split("/")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise SyncError(f"路径必须是目录内部的标准相对路径：{value}")
    return value


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


def scan(root, cancel=None, scoped=False, hash_filter=None):
    result = {}

    def visit(directory):
        with os.scandir(directory) as children:
            for child in children:
                check_cancel(cancel)
                path = Path(child.path)
                rel = path.relative_to(root).as_posix()
                s = child.stat(follow_symlinks=False)
                if stat.S_ISLNK(s.st_mode):
                    result[rel] = {"type": "symlink", "target": os.readlink(path)}
                elif stat.S_ISDIR(s.st_mode):
                    if os.path.ismount(path):
                        raise SyncError(f"目录中存在嵌套挂载点，不能整体替换：{rel}")
                    result[rel] = {"type": "directory", "mode": f"0{stat.S_IMODE(s.st_mode) & 0o777:03o}"}
                    visit(path)
                elif stat.S_ISREG(s.st_mode):
                    sha256, git_sha1 = fingerprints(path, cancel) if not scoped or (hash_filter or managed)(rel) else (None, None)
                    result[rel] = {"type": "file", "mode": f"0{stat.S_IMODE(s.st_mode) & 0o777:03o}",
                                   "size": s.st_size, "sha256": sha256, "git_sha1": git_sha1}
                else:
                    raise SyncError(f"目录中存在不支持的特殊文件：{rel}")
    visit(root)
    return result


def equivalent(actual, desired):
    keys = ["type"]
    if desired["type"] == "file":
        keys += ["size", hash_field(desired)]
    elif desired["type"] == "symlink":
        keys += ["target"]
    if os.name == "posix" and desired["type"] != "symlink":
        keys += ["mode"]
    return all(actual.get(k) == desired.get(k) for k in keys)


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise SyncError("拒绝跳转到非 HTTPS 下载地址。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Source:
    def __init__(self, local=None, owner=None, repo=None, commit=None, provider="github", base_url=None):
        if provider not in ("github", "gitee", "gitlab"):
            raise SyncError("不支持的资源托管平台。")
        self.local = Path(local).resolve() if local else None
        self.owner, self.repo, self.commit = owner, repo, commit
        self.provider = provider
        self.base_url = base_url or "https://gitlab.com"
        if provider == "gitlab":
            parsed = urllib.parse.urlsplit(self.base_url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
                raise SyncError("GitLab 服务地址必须是无账号、无路径的 HTTPS 地址。")
            self.base_url = self.base_url.rstrip("/")

    def descriptor(self):
        result = {"local": str(self.local) if self.local else None, "owner": self.owner,
                "repo": self.repo, "commit": self.commit, "provider": self.provider}
        if self.provider == "gitlab":
            result["base_url"] = self.base_url
        return result

    @property
    def api_base(self):
        if self.provider == "gitlab":
            return self.base_url + "/api/v4/projects/" + urllib.parse.quote(self.owner + "/" + self.repo, safe="")
        host = "https://gitee.com/api/v5" if self.provider == "gitee" else "https://api.github.com"
        return f"{host}/repos/{self.owner}/{self.repo}"

    def tree_url(self):
        if self.provider == "gitlab":
            return self.api_base + "/repository/tree?" + urllib.parse.urlencode({"ref": self.commit, "recursive": "true", "per_page": 100})
        return self.api_base + f"/git/trees/{self.commit}?recursive=1"

    def tree(self):
        if self.provider == "gitlab":
            from gitlab_download import tree
            return tree(self, getattr(self, "cancel_event", None))
        return json.loads(self.fetch_bytes(self.tree_url()))

    @staticmethod
    def remote(address, branch=""):
        if address.strip().startswith("https://gitee.com/"):
            return Source.gitee(address, branch)
        if address.strip().startswith("https://github.com/"):
            return Source.github(address, branch)
        from gitlab_download import connect
        return connect(address, branch)

    @staticmethod
    def head(url):
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            try:
                request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "publish-switcher/1.0"})
                with urllib.request.build_opener(HTTPSOnly()).open(request, timeout=30) as response:
                    return {key.lower(): value for key, value in response.headers.items()}
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
                    refused = AccessDenied(exc.geturl(), exc.code, exc.msg, exc.headers, None)
                    exc.close()
                    raise refused from exc
                if attempt == NETWORK_ATTEMPTS or not transient_network_error(exc):
                    raise
                retry_pause(exc, attempt, url, None)

    @staticmethod
    def gitee(address, branch=""):
        match = re.fullmatch(r"https://gitee\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", address.strip())
        if not match:
            raise SyncError("仓库地址格式应为 https://gitee.com/所有者/仓库")
        owner, repo = match.groups()
        base = f"https://gitee.com/api/v5/repos/{owner}/{repo}"
        if not branch.strip():
            branch = json.loads(Source.fetch_bytes(base))["default_branch"]
        data = json.loads(Source.fetch_bytes(base + "/branches/" + urllib.parse.quote(branch.strip(), safe="")))
        if not isinstance(data, dict) or data.get("name") != branch.strip():
            raise SyncError("Gitee 返回的分支不匹配，请检查分支名称。")
        commit = data.get("commit", {}).get("sha", "")
        if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SyncError("Gitee 返回无效提交。")
        return Source(owner=owner, repo=repo, commit=commit, provider="gitee")

    @staticmethod
    def github(address, branch=""):
        match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?", address.strip())
        if not match:
            raise SyncError("仓库地址格式应为 https://github.com/所有者/仓库")
        owner, repo = match.groups()
        base = f"https://api.github.com/repos/{owner}/{repo}"
        if not branch.strip():
            branch = json.loads(Source.fetch_bytes(base))["default_branch"]
        # The commits endpoint includes file diffs and can return megabytes.
        # A single branch reference provides the same commit in a tiny response.
        data = json.loads(Source.fetch_bytes(base + "/git/ref/heads/" + urllib.parse.quote(branch.strip(), safe="")))
        if not isinstance(data, dict) or data.get("ref") != "refs/heads/" + branch.strip():
            raise SyncError("GitHub 返回的分支不匹配，请检查分支名称。")
        obj = data.get("object", {})
        if obj.get("type") != "commit":
            raise SyncError("GitHub 分支没有指向有效提交。")
        commit = obj.get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise SyncError("GitHub 返回无效提交。")
        return Source(owner=owner, repo=repo, commit=commit)

    @staticmethod
    def fetch_bytes(url, limit=16 * 1024 * 1024, cancel=None):
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "publish-switcher/1.0", "Accept-Encoding": "identity"})
                with urllib.request.build_opener(HTTPSOnly()).open(req, timeout=30) as response:
                    length = response.headers.get("Content-Length")
                    if length is not None and length.isdigit() and int(length) > limit:
                        raise SyncError("配置、清单或 API 响应超过读取大小限制。")
                    chunks, count = [], 0
                    while count <= limit:
                        check_cancel(cancel)
                        chunk = response.read(min(1024 * 1024, limit + 1 - count))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        count += len(chunk)
                    data = b"".join(chunks)
                    if count <= limit and length is not None and length.isdigit() and len(data) < int(length):
                        raise http.client.IncompleteRead(data, int(length) - len(data))
                if len(data) > limit:
                    raise SyncError("配置或清单文件过大。")
                return data
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
                    refused = AccessDenied(exc.geturl(), exc.code, exc.msg, exc.headers, None)
                    exc.close()
                    raise refused from exc
                if attempt == NETWORK_ATTEMPTS or not transient_network_error(exc):
                    raise
                retry_pause(exc, attempt, url, cancel)

    def url(self, location):
        validate_source(location)
        if location.startswith("https://"):
            return location
        if self.local:
            path = (self.local / location).resolve()
            if not is_relative_to(path, self.local):
                raise SyncError("本地下载来源越出导入目录。")
            return path
        if not self.commit or not re.fullmatch(r"[0-9a-f]{40}", self.commit):
            raise SyncError("远端来源必须固定到提交。")
        if self.provider == "gitlab":
            return self.api_base + "/repository/files/" + urllib.parse.quote(location, safe="") + "/raw?ref=" + self.commit + "&lfs=false"
        if self.provider == "gitee":
            return f"https://gitee.com/{self.owner}/{self.repo}/raw/{self.commit}/" + urllib.parse.quote(location, safe="/")
        return f"https://raw.githubusercontent.com/{self.owner}/{self.repo}/{self.commit}/" + urllib.parse.quote(location, safe="/")

    def metadata(self, location):
        origin = self.url(location)
        if isinstance(origin, Path):
            if origin.stat().st_size > 16 * 1024 * 1024:
                raise SyncError("配置或清单文件过大。")
            return origin.read_bytes()
        return self.fetch_bytes(origin)

    def download(self, location, dest, size, expected, cancel, progress):
        for attempt in range(1, NETWORK_ATTEMPTS + 1):
            check_cancel(cancel)
            try:
                return self._download_once(location, dest, size, expected, cancel, progress)
            except Exception as exc:
                if isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
                    if not self.local and self.provider == "gitee" and not location.startswith("https://"):
                        exc.close()
                        logging.getLogger("publish-switcher").info(
                            "Gitee raw 返回 403，尝试官方公开 Blob API（同一文件哈希）：%s；%s 字节", location, size)
                        from gitee_download import download_blob
                        try:
                            return download_blob(self, location, dest, size, expected, cancel, progress)
                        except urllib.error.HTTPError as api_error:
                            api_error.close()
                            raise SyncError("Gitee raw 返回 403，官方 Blob API 也拒绝或无法提供文件（HTTP {}）：{}。"
                                            "请检查仓库访问权限／API 限额，或登录下载后手动复制／配置 Releases 来源。"
                                            "本次没有应用部分文件。".format(api_error.code, location)) from api_error
                    origin = urllib.parse.urlsplit(str(self.url(location)))
                    safe_url = urllib.parse.urlunsplit((origin.scheme, origin.netloc, origin.path, "", ""))
                    display_location = urllib.parse.urlsplit(location).path if location.startswith("https://") else location
                    raise SyncError("下载服务器拒绝请求（HTTP 403）：{}；文件：{}。"
                                    "请检查来源访问权限或下载限制，这与 Ubuntu 文件权限无关。".format(safe_url, display_location)) from exc
                if isinstance(self.url(location), Path) or attempt == NETWORK_ATTEMPTS or not transient_network_error(exc):
                    raise
                retry_pause(exc, attempt, location, cancel)

    def _download_once(self, location, dest, size, expected, cancel, progress):
        origin = self.url(location)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + ".part-" + uuid.uuid4().hex)
        git = expected.startswith("git:")
        h = hashlib.sha1(f"blob {size}\0".encode()) if git else hashlib.sha256()
        expected = expected[4:] if git else expected
        count = 0
        try:
            if isinstance(origin, Path):
                stream = origin.open("rb")
            else:
                req = urllib.request.Request(origin, headers={"User-Agent": "publish-switcher/1.0", "Accept-Encoding": "identity"})
                stream = urllib.request.build_opener(HTTPSOnly()).open(req, timeout=30)
            with stream, temp.open("wb") as out:
                while chunk := stream.read(1024 * 1024):
                    check_cancel(cancel)
                    count += len(chunk)
                    if count > size:
                        raise SyncError("下载文件大于清单标注大小。")
                    out.write(chunk)
                    h.update(chunk)
                    progress(len(chunk))
                out.flush()
                os.fsync(out.fileno())
            check_cancel(cancel)
            if count < size and not isinstance(origin, Path):
                raise http.client.IncompleteRead(b"", size - count)
            if count != size or h.hexdigest() != expected:
                raise SyncError(f"下载校验失败：{location}")
            os.replace(temp, dest)
            fsync_dir(dest.parent)
        finally:
            temp.unlink(missing_ok=True)


def load_profile(source, profile):
    raw = source.metadata(profile["manifest"])
    if hashlib.sha256(raw).hexdigest() != profile["sha256"]:
        raise SyncError("方案清单 SHA-256 不匹配。")
    manifest = validate_manifest(json.loads(raw.decode("utf-8-sig")))
    if manifest["id"] != profile["id"] or manifest["version"] != profile["version"]:
        raise SyncError("目录与清单的方案 ID 或版本不一致。")
    return manifest


@contextlib.contextmanager
def operation_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                if path.stat().st_size == 0:
                    stream.write(b"0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SyncError("另一个同步操作正在运行。") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def assert_stopped(target, exclude_pids=()):
    if sys.platform != "linux":
        return
    root = str(target)
    found = []
    ignored = {os.getpid(), *exclude_pids}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) in ignored:
            continue
        try:
            exe = os.readlink(proc / "exe")
            cwd = os.readlink(proc / "cwd")
            args = (proc / "cmdline").read_bytes().decode(errors="replace").split("\0")
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            # Cannot establish that an inaccessible process is unrelated.
            try:
                comm = (proc / "comm").read_text().strip()
            except (OSError, UnicodeError):
                comm = ""
            if comm == "AIotApp" or comm.startswith("python"):
                raise SyncError(f"无法检查进程 {proc.name}（{comm}），请退出相关程序后重试。")
            continue
        def inside(s):
            s = os.path.normpath(remove_suffix(s, " (deleted)"))
            return s == root or s.startswith(root + "/")
        script_paths = [os.path.normpath(os.path.join(cwd, arg)) for arg in args if arg and not arg.startswith("-")]
        if inside(exe) or inside(cwd) or any(inside(arg) for arg in script_paths):
            found.append(proc.name)
    if found:
        raise SyncError("publish 仍被程序使用，请先退出主程序和相关任务。进程：" + ", ".join(found))


class Engine:
    scope = "py-json"
    scope_label = "所选格式"
    retain_links = False

    def manages(self, path):
        return file_extension(path) in self.extensions

    def scope_scan(self, root, cancel=None):
        return scan(root, cancel, scoped=True, hash_filter=self.manages)

    def blockers(self, manifest, paths):
        return sync_blockers(manifest, paths, self.manages)

    def validate_object(self, entry, path):
        with Path(path).open("rb") as stream:
            prefix = stream.read(1024)
        if prefix.startswith(b"version https://git-lfs.github.com/spec/v1") and b"\noid sha256:" in prefix:
            raise SyncError("下载结果是 Git LFS 指针而非实际资源：" + entry["path"])

    def __init__(self, target, extensions=None):
        self.extensions = normalize_extensions(extensions)
        raw = Path(target).expanduser().absolute()
        if raw.is_symlink():
            raise SyncError("publish 不能是符号链接。")
        self.target = raw.resolve()
        if self.target == Path(self.target.anchor) or self.target == Path.home().resolve():
            raise SyncError("目标不能是文件系统根目录或用户主目录。")
        if is_relative_to(Path(__file__).resolve(), self.target):
            raise SyncError("工具自身必须放在 publish 外。")
        if not self.target.parent.is_dir():
            raise SyncError("目标父目录不存在。")
        if os.path.ismount(self.target):
            raise SyncError("publish 是挂载点，无法通过目录切换同步。")
        self.state = self.target.parent / (".publish-switcher-" + self.target.name)
        if self.state.is_symlink():
            raise SyncError("工具状态目录不能是符号链接。")
        self.state.mkdir(exist_ok=True)
        for name in ("objects", "profiles", "backups", "history"):
            path = self.state / name
            if path.is_symlink():
                raise SyncError("工具缓存和备份目录不能是符号链接。")
            path.mkdir(exist_ok=True)
        self.journal = self.state / "transaction.json"
        self.current = self.state / "current.json"

    def lock(self):
        return operation_lock(self.state / "operation.lock")

    def activate_competition(self):
        raise SyncError("旧赛事命令已停用，请使用 config list 和 config apply --version 版本名称。")

    def activate_config(self, source_name, active_name):
        raise SyncError("单文件切换已停用，请选择 config 子文件夹并应用整套配置。")

    def list_config_versions(self, user_only=False):
        from config_versions import list_versions
        with self.lock():
            return list_versions(self, user_only=user_only)

    def preview_config_version(self, version, user_only=False):
        from config_versions import preview_version
        with self.lock():
            return preview_version(self, version, user_only=user_only)

    def activate_config_version(self, version, expected_snapshot=None, log=lambda message: None, user_only=False):
        from config_versions import activate_version
        return activate_version(self, version, expected_snapshot, log, user_only=user_only)

    def compare_config_file(self, version, name, expected_snapshot=None, cancel=None):
        from config_versions import compare_file
        return compare_file(self, version, name, expected_snapshot, cancel)

    def task_config_status(self, user_only=False):
        from config_versions import current_version
        return current_version(self, user_only=user_only)

    def preflight(self):
        if self.target.is_symlink() or (self.target.exists() and not self.target.is_dir()):
            raise SyncError("目标必须是普通目录。")
        if os.path.ismount(self.target):
            raise SyncError("目标是挂载点。")
        if not os.access(self.target.parent, os.W_OK | os.X_OK):
            raise SyncError("没有目标父目录的写入权限。")
        if self.target.exists() and self.target.stat().st_dev != self.state.stat().st_dev:
            raise SyncError("目标与暂存目录不在同一文件系统。")
        assert_stopped(self.target)

    def _object(self, entry):
        key = hash_field(entry)
        return self.state / "objects" / (("git-" if key == "git_sha1" else "") + entry[key])

    def cached(self, entry, cancel=None):
        p = self._object(entry)
        return (p.is_file() and not p.is_symlink() and p.stat().st_size == entry["size"]
                and digest(p, cancel, git=hash_field(entry) == "git_sha1") == entry[hash_field(entry)])

    def save_profile(self, manifest, source):
        validate_manifest(manifest)
        key = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        atomic_json(self.state / "profiles" / (key + ".json"),
                    {"manifest": manifest, "source": source.descriptor()})
        return key

    def profiles(self):
        result = []
        for path in sorted((self.state / "profiles").glob("*.json")):
            try:
                data = read_json(path)
                validate_manifest(data["manifest"])
                result.append(data)
            except (OSError, ValueError, KeyError, SyncError):
                continue
        return result

    def preview(self, manifest, cancel=None, mode="strict", actual=None, sync_permissions=False, _restore=False):
        validate_manifest(manifest, allow_empty_entries=_restore)
        if mode not in ("incremental", "strict"):
            raise SyncError("更新模式应为 incremental 或 strict。")
        if self.target.is_symlink():
            raise SyncError("目标不能是符号链接。")
        if actual is None:
            actual = self.scope_scan(self.target, cancel) if self.target.exists() else {}
        desired = {e["path"]: e for e in manifest["entries"] if e["type"] == "file" and self.manages(e["path"])}
        changes, downloads, notices, comparison = [], 0, [], []
        for path, entry in desired.items():
            old = actual.get(path)
            same_content = content_matches(old, entry)
            same = same_content and (not sync_permissions or equivalent(old, entry))
            if old is None:
                status = "新增"
            elif old["type"] != "file":
                status = "路径冲突"
            elif not same_content:
                status = "内容不同"
            elif not equivalent(old, entry):
                status = "权限不同" if sync_permissions else "内容相同"
            else:
                status = "相同"
            permission_note = "{} / {}（{}）".format(old.get("mode", "—") if old else "—", entry["mode"],
                                                      "Windows 不比较" if os.name != "posix" else "新文件用仓库" if old is None else "按仓库同步" if sync_permissions and mode == "strict" else "保留本地")
            comparison.append({"path": path, "status": status, "incremental": "新增" if old is None else "跳过", "strict": "新增" if old is None else "不变" if same else "替换", "permissions": permission_note})
            if mode == "incremental" and old is not None:
                continue
            if old is None:
                changes.append(("新增", path))
            elif not same:
                changes.append(("替换", path))
            if entry["type"] == "file":
                reusable = content_matches(old, entry)
                if not reusable and not self.cached(entry, cancel):
                    downloads += entry["size"]
        local_only = [path for path, old in actual.items() if old["type"] == "file" and self.manages(path) and path not in desired]
        comparison += [{"path": p, "status": "仅本地", "incremental": "保留", "strict": "删除"} for p in local_only]
        if mode == "strict":
            changes += [("删除", path) for path in local_only]
        for e in manifest["entries"]:
            if e["type"] == "directory" or e["path"] in desired:
                continue
            old = actual.get(e["path"])
            if old is None:
                notices.append(("仅提示：本机缺失，不下载", e["path"]))
            elif e["type"] != old["type"] or (e["type"] == "file" and e["size"] != old["size"]):
                notices.append(("仅提示：类型或大小不同，保留本机", e["path"]))
            elif e["type"] == "file" and e["size"] == 0:
                notices.append(("仅提示：远端为空，保留本机", e["path"]))
        remote_paths = {e["path"] for e in manifest["entries"]}
        notices += [("仅提示：本地额外文件，保留", p) for p, old in actual.items()
                    if old["type"] != "directory" and not self.manages(p) and p not in remote_paths]
        included = set(desired) if mode == "strict" else set(desired) - set(actual)
        return {"changes": sorted(changes, key=lambda x: x[1]), "download_bytes": downloads, "mode": mode, "sync_permissions": bool(sync_permissions),
                "extensions": list(self.extensions),
                "actual": actual, "comparison": sorted(comparison, key=lambda row: row["path"]),
                "notices": sorted(notices, key=lambda x: x[1]),
                "blocker": ("请至少勾选一种同步文件格式。" if not self.extensions else self.blockers(manifest, included))}

    def recover(self):
        """Recover pending config bundles and directory swaps before any operation."""
        assets_recovered = False
        if self.scope != "assets" and (self.state / "assets-transaction.json").exists():
            from assets_sync import AssetsEngine
            assets_recovered = AssetsEngine(self.target).recover()
        from config_versions import recover_transaction
        config_recovered = recover_transaction(self)
        if not self.journal.exists():
            return config_recovered or assets_recovered
        data = read_json(self.journal)
        backup = self.state / "backups" / relative_path(data["backup"])
        stage = self.state / relative_path(data["stage"])
        # Transaction paths must be immediate children of their designated directories.
        if backup.parent != self.state / "backups" or stage.parent != self.state:
            raise SyncError("事务记录中的路径无效。")
        self.preflight()
        if data.get("phase") == "committed":
            atomic_json(self.current, data["new_state"])
            atomic_json(self.state / "history" / (backup.name + ".json"), data)
        else:
            if backup.exists():
                if self.target.exists():
                    if stage.exists():
                        self._release_stage(stage)
                    os.rename(self.target, stage)
                os.rename(backup, self.target)
                fsync_dir(self.target.parent)
                fsync_dir(backup.parent)
            elif not data["had_target"] and self.target.exists():
                if stage.exists():
                    self._release_stage(stage)
                os.rename(self.target, stage)
                fsync_dir(self.target.parent)
            elif data["had_target"] and not self.target.exists():
                raise SyncError("恢复失败：原目录和备份均不存在，请人工检查事务记录。")
            if data["old_state"] is None:
                self.current.unlink(missing_ok=True)
            else:
                atomic_json(self.current, data["old_state"])
        if stage.exists():
            self._release_stage(stage)
        self.journal.unlink()
        fsync_dir(self.state)
        return True

    def _release_stage(self, stage):
        """A restore's staged tree is a real backup, never discard it on rollback."""
        record = self.state / "restore-source.json"
        if record.exists():
            data = read_json(record)
            backup = self.state / "backups" / relative_path(data["backup"])
            if backup.parent != self.state / "backups":
                raise SyncError("恢复来源记录无效。")
            if data["stage"] == stage.name and not backup.exists():
                os.rename(stage, backup)
                fsync_dir(backup.parent)
                fsync_dir(self.state)
                return
        self._remove_stage(stage)

    @staticmethod
    def _remove_stage(path):
        # Generated trees may contain read-only directories; never follow symlinks.
        for root, dirs, files in os.walk(path, followlinks=False):
            os.chmod(root, 0o700)
        shutil.rmtree(path)

    def _commit(self, stage, info):
        self.preflight()
        token = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        backup = self.state / "backups" / token
        old = read_json(self.current) if self.current.exists() else None
        new = dict(info, backup=token)
        data = {"phase": "prepared", "backup": token, "stage": stage.name,
                "had_target": self.target.exists(), "old_state": old, "new_state": new}
        atomic_json(self.journal, data)
        try:
            if self.target.exists():
                os.rename(self.target, backup)
                fsync_dir(self.target.parent)
                fsync_dir(backup.parent)
            os.rename(stage, self.target)
            fsync_dir(self.target.parent)
            fsync_dir(self.state)
            data["phase"] = "committed"
            atomic_json(self.journal, data)
            atomic_json(self.current, new)
            atomic_json(self.state / "history" / (token + ".json"), data)
            self.journal.unlink()
            fsync_dir(self.state)
        except BaseException:
            # A committed deployment is finalized by recover; an uncommitted one rolls back.
            self.recover()
            raise
        return new

    def apply(self, manifest, source, cancel=None, log=lambda msg: None, mode="strict", expected_actual=None, sync_permissions=False, _restore=False, on_commit=None):
        validate_manifest(manifest, allow_empty_entries=_restore)
        self.startup_recover()
        with self.lock():
            self.recover()
            self.preflight()
            if not _restore:
                self.save_profile(manifest, source)
            preview = self.preview(manifest, cancel, mode=mode, sync_permissions=sync_permissions, _restore=_restore)
            if expected_actual is not None and preview["actual"] != expected_actual:
                raise SyncError("检查后本地文件发生变化，请重新检查并确认更新。")
            if preview["blocker"]:
                raise SyncError(preview["blocker"])
            all_desired = {e["path"]: e for e in manifest["entries"] if e["type"] == "file" and self.manages(e["path"])}
            if not preview["changes"]:
                log("没有需要更新的文件，未修改 publish。")
                return {"id": manifest["id"], "version": manifest["version"], "backup": None, "unchanged": True, "mode": mode}
            desired = all_desired if mode == "strict" else {p: e for p, e in all_desired.items() if p not in preview["actual"]}
            if not sync_permissions:
                desired = {p: dict(e, mode=preview["actual"][p]["mode"]) if p in preview["actual"] and preview["actual"][p]["type"] == "file" else e
                           for p, e in desired.items()}
            for path in desired:
                p = self.target / path
                if p.is_symlink() or (p.exists() and not p.is_file()):
                    raise SyncError("同步路径与本机目录或符号链接冲突，不会覆盖：" + path)
                for parent in p.parents:
                    if parent == self.target:
                        break
                    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                        raise SyncError("同步父目录与本机文件或符号链接冲突：" + str(parent))
            retained = {p: e for p, e in preview["actual"].items() if mode == "incremental" and e["type"] == "file" and self.manages(p)}
            file_bytes = sum(e["size"] for e in desired.values()) + (0 if self.retain_links else sum(e["size"] for e in retained.values()))
            needed = file_bytes + preview["download_bytes"] + 16 * 1024 * 1024
            if shutil.disk_usage(self.state).free < needed:
                raise SyncError(f"磁盘空间不足，需要约 {needed / 1024**2:.1f} MiB 可用空间。")
            stage = self.state / ("stage-" + uuid.uuid4().hex)
            stage.mkdir()
            try:
                # Preserve all non-managed resources by hard-linking within this filesystem.
                # Never chmod or write to these links: the original resource bytes stay intact.
                for path, old in sorted(preview["actual"].items(), key=lambda x: (x[0].count("/"), x[0])):
                    check_cancel(cancel)
                    dest = stage / path
                    if old["type"] == "directory":
                        dest.mkdir()
                    elif old["type"] == "symlink":
                        os.symlink(old["target"], dest)
                    elif not self.manages(path):
                        os.link(self.target / path, dest)
                    elif mode == "incremental":
                        if self.retain_links:
                            os.link(self.target / path, dest)
                        else:
                            shutil.copyfile(self.target / path, dest)
                            with dest.open("r+b") as stream:
                                os.fsync(stream.fileno())
                            shutil.copystat(self.target / path, dest)
                for e in sorted(desired.values(), key=lambda e: (e["path"].count("/"), e["path"])):
                    check_cancel(cancel)
                    dest = stage / e["path"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if e["type"] == "directory":
                        dest.mkdir()
                    elif e["type"] == "file":
                        original = preview["actual"].get(e["path"])
                        reusable = content_matches(original, e)
                        if reusable:
                            log("复用：" + e["path"])
                            shutil.copyfile(self.target / e["path"], dest)
                        else:
                            if not self.cached(e, cancel):
                                log("下载：" + e["path"])
                                count = 0
                                last_report = 0.0
                                def progress(n):
                                    nonlocal count, last_report
                                    count += n
                                    now = time.monotonic()
                                    if now - last_report >= 0.25 or count == e["size"]:
                                        log(f"下载进度：{e['path']} {count}/{e['size']} 字节")
                                        last_report = now
                                key = hash_field(e)
                                expected = ("git:" if key == "git_sha1" else "") + e[key]
                                source.download(e["source"], self._object(e), e["size"], expected, cancel, progress)
                            self.validate_object(e, self._object(e))
                            shutil.copyfile(self._object(e), dest)
                        with dest.open("r+b") as stream:
                            os.fsync(stream.fileno())
                        os.chmod(dest, int(e["mode"], 8))
                    else:
                        os.symlink(e["target"], dest)
                # Apply directory modes only after all children have been created.
                for path, old in sorted(preview["actual"].items(), key=lambda x: x[0].count("/"), reverse=True):
                    if old["type"] == "directory":
                        fsync_dir(stage / path)
                        os.chmod(stage / path, int(old["mode"], 8))
                fsync_dir(stage)
                actual = self.scope_scan(stage, cancel)
                actual_managed = {p for p, e in actual.items() if e["type"] == "file" and self.manages(p)}
                expected_files = dict(retained)
                expected_files.update(desired)
                if actual_managed != expected_files.keys() or any(not equivalent(actual[p], e) for p, e in expected_files.items()):
                    raise SyncError("暂存目录最终校验失败。")
                root_mode = stat.S_IMODE(self.target.stat().st_mode) if self.target.exists() else 0o755
                os.chmod(stage, root_mode)
                check_cancel(cancel)
                latest = self.scope_scan(self.target, cancel) if self.target.exists() else {}
                if latest != preview["actual"]:
                    raise SyncError("准备更新期间本地文件发生变化，请重新检查并确认。")
                log(self.scope_label + " 已校验，其他资源已保留，开始切换（此阶段不能取消）。")
                info = {"id": manifest["id"], "version": manifest["version"],
                        "name": manifest.get("name", manifest["id"]), "applied_at": time.time(), "scope": self.scope, "mode": mode,
                        "sync_permissions": bool(sync_permissions), "extensions": list(self.extensions)}
                if on_commit:
                    on_commit()
                return self._commit(stage, info)
            finally:
                if stage.exists() and not self.journal.exists():
                    self._remove_stage(stage)

    def restore(self, log=lambda msg: None):
        self.startup_recover()
        with self.lock():
            self.recover()
            self.preflight()
            if not self.current.exists():
                raise SyncError("没有上次同步的备份记录。")
            current = read_json(self.current)
            # Restore the scope recorded by the deployment, even if preferences changed.
            extensions = normalize_extensions(current.get("extensions", LEGACY_EXTENSIONS))
            restoring = Engine(self.target, extensions=extensions)
            token = relative_path(current["backup"])
            backup = self.state / "backups" / token
            if backup.parent != self.state / "backups" or not backup.is_dir() or backup.is_symlink():
                raise SyncError("备份目录不存在或无效。")
            snapshot = restoring.scope_scan(backup)
            entries = [dict(e, path=p, source=p) if e["type"] == "file" else dict(e, path=p)
                       for p, e in snapshot.items() if e["type"] == "directory" or (e["type"] == "file" and restoring.manages(p))]
            manifest = {"schema_version": 1, "id": "restored", "version": "backup", "name": "恢复的 " + describe(extensions),
                        "entries": entries, "allowed_empty": [e["path"] for e in entries if e["type"] == "file" and e["size"] == 0]}
        # Restore the saved permissions as well as bytes, independent of update preferences.
        return restoring.apply(manifest, Source(local=backup), log=log, sync_permissions=True, _restore=True)

    def startup_recover(self):
        with self.lock():
            recovered = self.recover()
            record = self.state / "restore-source.json"
            if record.exists():
                data = read_json(record)
                stage = self.state / relative_path(data["stage"])
                backup = self.state / "backups" / relative_path(data["backup"])
                if stage.parent != self.state or backup.parent != self.state / "backups":
                    raise SyncError("恢复来源记录无效。")
                if stage.exists() and not backup.exists():
                    os.rename(stage, backup)
                    fsync_dir(self.state)
                    fsync_dir(backup.parent)
                record.unlink()
                recovered = True
            return recovered
