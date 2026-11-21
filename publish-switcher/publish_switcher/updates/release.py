"""工具版本检查与准备。

下载并校验 Switcher 安装包，写入 pending 记录；真正替换目录由根目录 tool_update 完成。
"""
import json
import os
import logging
import re
import shutil
import urllib.error
import urllib.parse
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from publish_switcher.common.errors import Cancelled
from publish_switcher.repositories.catalog import DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY
from publish_switcher.repositories.discovery import normalize
from publish_switcher.repositories.source import Source
from publish_switcher.updates.package import (
    PackageError, REQUIRED_FILES, archive_entries, https_url, package_version,
    validate_payload, validate_release as validate_manifest, verify_package_file, version_number,
)
from publish_switcher.updates.bootstrap import (
    UpdateError, commit_update, instance_lock, launch_update_helper,
    read_json, recover_update, save_json, update_state,
)

DEFAULT_UPDATE_URL = "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/switcher-update.json"


def validate_release(data):
    try:
        return validate_manifest(data)
    except PackageError as exc:
        raise UpdateError(str(exc)) from exc


def prepare_package(install, release, package, current):
    try:
        return _prepare_package(install, release, package, current)
    except PackageError as exc:
        raise UpdateError(str(exc)) from exc


def _prepare_package(install, release, package, current):
    install, package = Path(install).absolute(), Path(package)
    release = validate_release(release)
    state = update_state(install)
    if version_number(release["version"]) < version_number(current):
        raise UpdateError("不能用较旧的安装包更新程序。")
    required = state / "required.json"
    if required.exists() and version_number(release["version"]) < version_number(read_json(required)["version"]):
        raise UpdateError("此离线包低于已知的必更版本，请准备最新安装包。")
    verify_package_file(package, release)
    if (state / "pending.json").exists():
        raise UpdateError("存在未完成的程序更新，请关闭并重新打开工具。")
    if not install.is_dir() or os.path.ismount(install):
        raise UpdateError("程序安装目录不存在或是挂载点，无法整体替换。")
    token = uuid.uuid4().hex
    stage = state / ("stage-" + token)
    stage.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive_entries(archive)
            required_space = sum(((entry.file_size + 4095) // 4096 + 1) * 4096 for entry in entries)
            if shutil.disk_usage(install.parent).free < required_space:
                raise UpdateError("程序更新磁盘空间不足。")
            for entry in entries:
                relative = PurePosixPath(entry.orig_filename).parts[1:]
                if not relative:
                    continue
                mode = entry.external_attr >> 16
                destination = stage.joinpath(*relative)
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as incoming, destination.open("xb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing)
                        outgoing.flush()
                        os.fsync(outgoing.fileno())
                    destination.chmod(0o755 if mode & 0o111 else 0o644)
        validate_payload(stage, release['version'])
        record = {"phase": "prepared", "stage": stage.name, "backup": "backup-" + token, "version": release["version"]}
        save_json(state / "pending.json", record)
        return record
    except BaseException:
        shutil.rmtree(stage)
        raise


def remote_file(url):
    """Preserve the existing Gitee public Blob fallback for ZIP downloads."""
    parsed = urllib.parse.urlsplit(https_url(url))
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "gitee.com" and len(parts) >= 5 and parts[2] == "raw" and not parsed.query:
        owner, repo, _, ref = parts[:4]
        try:
            source = (Source(owner=owner, repo=repo, commit=ref, provider="gitee") if re.fullmatch(r"[0-9a-f]{40}", ref)
                      else Source.remote("https://gitee.com/{}/{}".format(owner, repo), urllib.parse.unquote(ref)))
        except urllib.error.HTTPError as exc:
            if exc.code != 403:
                raise
            logging.getLogger("publish-switcher").warning(
                "Gitee API 返回 403，程序更新改为直接访问配置的公开文件地址；不切换仓库：%s", url)
            if exc.fp is not None:
                exc.close()
            # Publisher metadata supplies version, size and SHA-256. The package
            # must still pass all validation before replacing the installation.
            return Source(), url
        return source, urllib.parse.unquote("/".join(parts[4:]))
    return Source(), url


def mirror_locations(url, repositories=None):
    """Map only recognized repository raw URLs; external publisher URLs stay exact."""
    if not repositories:
        return [url]
    values = normalize(repositories)
    parsed = urllib.parse.urlsplit(https_url(url))
    parts = parsed.path.strip("/").split("/")
    origin = None
    if parsed.hostname == "gitee.com" and len(parts) >= 5 and parts[2] == "raw":
        origin, ref, path = "https://gitee.com/" + "/".join(parts[:2]), parts[3], "/".join(parts[4:])
    elif parsed.hostname == "raw.githubusercontent.com" and len(parts) >= 4:
        origin, ref, path = "https://github.com/" + "/".join(parts[:2]), parts[2], "/".join(parts[3:])
    elif "-" in parts:
        marker = parts.index("-")
        if marker >= 2 and parts[marker + 1:marker + 2] == ["raw"] and len(parts) > marker + 3:
            origin = parsed.scheme + "://" + parsed.netloc + "/" + "/".join(parts[:marker])
            ref, path = parts[marker + 2], "/".join(parts[marker + 3:])
    # Published mirrors commonly retain the canonical Gitee package URL in the
    # metadata. Remap that package as well when the user selects GitHub alone.
    origins = {item["url"] for item in values} | {DEFAULT_REPOSITORY, LEGACY_DEFAULT_REPOSITORY}
    if origin is None or origin not in origins:
        return [url]
    results = []
    for item in values:
        base = item["url"]
        branch = urllib.parse.quote(item["branch"], safe="") if item["branch"] else ref
        if base.startswith("https://gitee.com/"):
            address = base + "/raw/" + branch + "/" + path
        elif base.startswith("https://github.com/"):
            address = base.replace("https://github.com/", "https://raw.githubusercontent.com/", 1) + "/" + branch + "/" + path
        else:
            address = base + "/-/raw/" + branch + "/" + path
        results.append(address)
    return results


def check_release(url, install, current, repositories=None):
    failures = []
    for address in mirror_locations(url, repositories):
        try:
            logging.getLogger("publish-switcher").info("查询程序更新地址：%s", address)
            source, location = remote_file(address)
            release = validate_release(json.loads(source.metadata(location).decode("utf-8-sig")))
            release = remember_release(release, install, current)
            if repositories:
                release[0]["mirror_repositories"] = repositories
            return release
        except Exception as exc:
            if not repositories:
                raise
            failures.append(address + "：" + str(exc))
            logging.getLogger("publish-switcher").warning("程序更新地址不可用：%s；%s", address, exc)
    raise UpdateError("程序更新地址均不可用：\n" + "\n".join(failures))


def remember_release(release, install, current):
    state = update_state(install)
    required = state / "required.json"
    if required.exists() and version_number(release["version"]) < version_number(read_json(required)["version"]):
        raise UpdateError("更新源返回的版本低于此前检查到的版本，请联系实施人员。")
    save_json(required, release)
    return release, version_number(release["version"]) > version_number(current)


def prepare_online(install, release, current, cancel, progress):
    state = update_state(install)
    package = state / "download.zip"
    failures = []
    addresses = mirror_locations(release["url"], release.get("mirror_repositories"))
    for address in addresses:
        try:
            source, location = remote_file(address)
            source.download(location, package, release["size"], release["sha256"], cancel, progress)
            break
        except Exception as exc:
            if isinstance(exc, Cancelled) or not release.get("mirror_repositories"):
                raise
            failures.append(address + "：" + str(exc))
            logging.getLogger("publish-switcher").warning("程序包地址不可用：%s；%s", address, exc)
    else:
        raise UpdateError("程序包下载地址均不可用：\n" + "\n".join(failures))
    return prepare_package(install, release, package, current)


def prepare_offline(install, manifest, current):
    manifest = Path(manifest)
    release = validate_release(read_json(manifest))
    return prepare_package(install, release, manifest.parent / release["package_file"], current)
