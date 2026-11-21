"""HTTPS 资源源。

封装仓库元数据与文件下载：仅 HTTPS、固定提交、重试瞬时网络错误；
支持本地方案导入与已缓存离线读取。
"""
from __future__ import annotations

import hashlib
import http.client
import io
import json
import logging
import os
import re
import ssl
import time
import urllib.request
import uuid
from publish_switcher.common.compat import is_relative_to
from pathlib import Path
from publish_switcher.common.errors import Cancelled, SyncError, check_cancel
from publish_switcher.common.files import fsync_dir
from publish_switcher.sync.manifests import validate_manifest, validate_source


class AccessDenied(urllib.error.HTTPError):
    """Keep HTTP status handling while exposing the refused endpoint to users."""
    def __init__(self, url, code, msg, hdrs, fp):
        # CPython 3.8 skips response initialization when fp=None. In that case
        # accessing .url or calling .close() delegates to an uninitialized
        # tempfile wrapper and raises KeyError('file'), masking the HTTP 403.
        super().__init__(url, code, msg, hdrs, io.BytesIO() if fp is None else fp)

    def __str__(self):
        parsed = urllib.parse.urlsplit(self.filename)
        address = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if parsed.hostname == "gitee.com" and parsed.path.startswith("/api/"):
            return ("Gitee API 拒绝访问（HTTP 403）：" + address +
                    "。无法获取对应仓库数据，可能涉及平台访问策略或接口限额。"
                    "请稍后重试，或在设置中选择可访问的仓库／使用已完整缓存的离线方案。")
        return "服务器拒绝访问（HTTP 403）：" + address


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
            from publish_switcher.repositories.gitlab import tree
            return tree(self, getattr(self, "cancel_event", None))
        return json.loads(self.fetch_bytes(self.tree_url()))

    @staticmethod
    def remote(address, branch=""):
        if address.strip().startswith("https://gitee.com/"):
            return Source.gitee(address, branch)
        if address.strip().startswith("https://github.com/"):
            return Source.github(address, branch)
        from publish_switcher.repositories.gitlab import connect
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
                    refused = AccessDenied(exc.filename, exc.code, exc.msg, exc.headers, None)
                    if exc.fp is not None:
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
                    refused = AccessDenied(exc.filename, exc.code, exc.msg, exc.headers, None)
                    if exc.fp is not None:
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
                        from publish_switcher.repositories.gitee import download_blob
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
