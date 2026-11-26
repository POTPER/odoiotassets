#!/usr/bin/env python3
"""首次在线安装脚本（可单独拷贝）。

在 Ubuntu 上依次尝试 Gitee / GitHub 发布信息，下载 Switcher ZIP 并调用 install.sh；
不修改 publish 资源。仅需 Python 3.8+ 标准库。
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request


SOURCES = (
    "https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/",
    "https://raw.githubusercontent.com/POTPER/odoiotassets/main/publish-switcher/release/",
)
# BEGIN GENERATED PACKAGE CHECKS
import ast
import hashlib
import re
import stat
import urllib.parse
import zipfile
from pathlib import Path, PurePosixPath


MAX_PACKAGE = 256 * 1024 * 1024
BASE_FILES = ("switcher.py", "app.py", "core.py", "version.py", "tool_update.py", "install.sh")
UPDATE_FILES = ("unified_update.py", "update_dialog.py", "update_channels.py")
INTERFACE_FILES = ("reference_ui.py", "ui_assets.py")
PACKAGE_FILES = (
    "install_online.py", "install_offline_debs.sh",
    "publish_switcher/__init__.py", "publish_switcher/cli/main.py",
    "publish_switcher/gui/app.py", "publish_switcher/gui/pages/demo.py",
    "publish_switcher/updates/release.py", "publish_switcher/updates/package.py",
    "publish_switcher/sync/engine.py",
)
LAYOUT_FILES = (
    "publish_switcher/__main__.py", "publish_switcher/version.py",
    "publish_switcher/updates/bootstrap.py",
)
STARTUP_FILES = ("publish_switcher/gui/startup.py", "publish_switcher/updates/startup.py")
ICON_FILES = tuple("icons/swicher-{}.png".format(size) for size in (16, 24, 32, 48, 64, 128, 256))
INCREMENTAL_FILES = ("publish_switcher/updates/incremental.py",)
REQUIRED_FILES = BASE_FILES + UPDATE_FILES + INTERFACE_FILES + PACKAGE_FILES + LAYOUT_FILES + STARTUP_FILES + ICON_FILES + INCREMENTAL_FILES


class PackageError(ValueError):
    pass


def version_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){1,4}", value):
        raise PackageError("程序版本应为数字版本号，例如 2026.11.20.1。")
    return tuple(int(part) for part in value.split(".")) + (0,) * (5 - len(value.split(".")))


def https_url(value):
    if not isinstance(value, str):
        raise PackageError("更新地址必须使用 HTTPS。")
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise PackageError("更新地址必须是完整的 HTTPS 地址。")
    return value.strip()


def validate_release(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("product") != "publish-switcher":
        raise PackageError("更新信息不是有效的 Switcher 发布信息。")
    version_number(data.get("version"))
    https_url(data.get("url"))
    if type(data.get("size")) is not int or not 0 < data["size"] <= MAX_PACKAGE:
        raise PackageError("程序更新包大小无效或超过 256 MiB。")
    if not isinstance(data.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
        raise PackageError("更新信息缺少有效的 SHA-256。")
    name = data.get("package_file", "publish-switcher.zip")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", name):
        raise PackageError("离线更新包文件名无效。")
    result = dict(data, package_file=name)
    result["notes"] = str(data.get("notes", ""))[:8000]
    if "files" in data or "files_url" in data:
        result["files"] = validate_files(data.get("files"), data["version"])
        base = https_url(data.get("files_url"))
        if not base.endswith("/") or urllib.parse.urlsplit(base).query:
            raise PackageError("文件更新地址必须为 HTTPS 目录地址。")
        result["files_url"] = base
    return result


def validate_files(files, version):
    if not isinstance(files, list) or not 0 < len(files) <= 10000:
        raise PackageError("程序文件清单无效。")
    paths, objects = set(), {}
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise PackageError("程序文件清单条目无效。")
        name = entry["path"]
        path = PurePosixPath(name)
        if (not path.parts or path.is_absolute() or path.as_posix() != name or ".." in path.parts
                or any(char in name for char in (chr(92), ":", chr(0)))
                or any(part.endswith((".", " ")) for part in path.parts)):
            raise PackageError("程序文件清单包含无效路径。")
        key = name.casefold()
        if key in paths:
            raise PackageError("程序文件清单包含重复路径。")
        paths.add(key)
        size, digest, mode = entry.get("size"), entry.get("sha256"), entry.get("mode")
        if (type(size) is not int or size < 0 or size > MAX_PACKAGE
                or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                or type(mode) is not int or mode not in (0o644, 0o755)):
            raise PackageError("程序文件清单缺少有效的大小、SHA-256 或权限。")
        if digest in objects and objects[digest] != size:
            raise PackageError("相同文件对象的大小不一致。")
        objects[digest] = size
        total += size
    if total > 1024 ** 3:
        raise PackageError("程序文件清单过大。")
    for name in paths:
        if any(parent.as_posix() in paths for parent in PurePosixPath(name).parents if parent.parts):
            raise PackageError("程序文件清单包含文件与目录冲突。")
    if any(name.casefold() not in paths for name in required_files(version)):
        raise PackageError("程序文件清单缺少必需文件。")
    return files


def package_version(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            version_number(value)
            return value
    raise PackageError("更新包缺少程序版本。")


def required_files(version):
    number = version_number(version)
    if number >= (2026, 11, 26, 2):
        return REQUIRED_FILES
    if number >= (2026, 11, 26, 1):
        return BASE_FILES + UPDATE_FILES + INTERFACE_FILES + PACKAGE_FILES + LAYOUT_FILES + STARTUP_FILES + ICON_FILES
    if number >= (2026, 11, 21, 5):
        return BASE_FILES + UPDATE_FILES + INTERFACE_FILES + PACKAGE_FILES + LAYOUT_FILES + STARTUP_FILES
    if number >= (2026, 11, 21, 1):
        return BASE_FILES + UPDATE_FILES + INTERFACE_FILES + PACKAGE_FILES + LAYOUT_FILES
    if number >= (2026, 11, 20, 11):
        return BASE_FILES + UPDATE_FILES + INTERFACE_FILES + PACKAGE_FILES
    if number >= (2026, 11, 20, 10):
        return BASE_FILES + UPDATE_FILES + INTERFACE_FILES
    if number >= (2026, 11, 20, 9):
        return BASE_FILES + UPDATE_FILES
    return BASE_FILES


def verify_package_file(package, release):
    if package.stat().st_size != release["size"]:
        raise PackageError("程序更新包大小不匹配。")
    digest = hashlib.sha256()
    with package.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != release["sha256"]:
        raise PackageError("程序更新包 SHA-256 校验失败。")


def archive_entries(archive):
    entries = archive.infolist()
    if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 1024 ** 3:
        raise PackageError("程序更新包展开后过大。")
    seen = set()
    for entry in entries:
        raw_name = entry.orig_filename
        path = PurePosixPath(raw_name)
        mode = entry.external_attr >> 16
        if (not path.parts or path.parts[0] != "publish-switcher" or path.is_absolute()
                or ".." in path.parts or chr(92) in raw_name or ":" in raw_name or chr(0) in raw_name
                or stat.S_IFMT(mode) not in (0, stat.S_IFDIR, stat.S_IFREG)
                or (len(path.parts) == 1 and not entry.is_dir())):
            raise PackageError("程序更新包包含无效路径或特殊文件。")
        key = path.as_posix().casefold()
        if key in seen:
            raise PackageError("程序更新包包含重复路径。")
        seen.add(key)
    return entries


def validate_payload(root, version):
    if version is None:
        version = package_version(root / "version.py")
    if any(not (root / name).is_file() for name in required_files(version)):
        raise PackageError("更新包缺少完整的 Switcher 程序文件。")
    if package_version(root / "version.py") != version:
        raise PackageError("更新信息与安装包内的版本不一致。")
    for module in root.rglob("*.py"):
        compile(module.read_bytes(), str(module), "exec")
# END GENERATED PACKAGE CHECKS


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        if not url.startswith("https://"):
            raise ValueError("拒绝跳转到非 HTTPS 地址。")
        return super().redirect_request(request, response, code, message, headers, url)


def request(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PublishSwitcher-Installer/1.0"})
    return urllib.request.build_opener(HTTPSOnly()).open(req, timeout=60)


def download(base, destination):
    with request(base + "switcher-update.json") as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("发布信息过大。")
    release = validate_release(json.loads(raw.decode("utf-8-sig")))
    if release["package_file"] != "publish-switcher.zip":
        raise PackageError("发布信息中的安装包文件名无效。")
    received = 0
    with request(base + "publish-switcher.zip") as response, destination.open("wb") as stream:
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            received += len(chunk)
            if received > release["size"]:
                raise ValueError("安装包超过发布信息标注的大小。")
            stream.write(chunk)
    verify_package_file(destination, release)
    return release


def extract(package, destination, version=None):
    with zipfile.ZipFile(package) as archive:
        entries = archive_entries(archive)
        archive.extractall(destination, members=entries)
    root = destination / "publish-switcher"
    validate_payload(root, version)
    return root


def install(directory, cli=False):
    directory = Path(directory).expanduser().absolute()
    if directory.exists() or directory.is_symlink():
        raise ValueError("目录已存在，不会覆盖：{}；请用 --directory 指定新目录，或使用软件内更新。".format(directory))
    directory.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="switcher-install-") as temporary:
        temporary = Path(temporary)
        errors = []
        for index, base in enumerate(SOURCES):
            print("正在尝试仓库：" + base, flush=True)
            try:
                release = download(base, temporary / "package.zip")
                root = extract(temporary / "package.zip", temporary / str(index), release["version"])
            except Exception as exc:
                errors.append(base + "：" + str(exc))
                print("此仓库下载或校验失败，尝试下一项：" + str(exc), flush=True)
                continue
            # copytree atomically creates the destination directory and refuses existing paths.
            # A filesystem copy failure leaves the new partial directory for inspection.
            shutil.copytree(root, directory)
            print("已下载并校验 swicher " + release["version"], flush=True)
            break
        else:
            raise RuntimeError("两个仓库均失败，未安装：\n" + "\n".join(errors))
    command = ["bash", str(directory / "install.sh")]
    if cli:
        command.append("--cli")
    subprocess.run(command, cwd=str(directory), check=True)
    print("安装目录：" + str(directory))
    print("启动：python3 \"{}\" {}".format(directory / "switcher.py", "cli" if cli else "gui"))


def main():
    parser = argparse.ArgumentParser(description="从 Gitee / GitHub 下载并安装 swicher，不下载 publish 资源。")
    parser.add_argument("--directory", default=str(Path(__file__).resolve().parent / "publish-switcher"),
                        help="新安装目录，默认在本安装脚本所在目录下新建 publish-switcher 文件夹")
    parser.add_argument("--cli", action="store_true", help="SSH 命令行安装，不安装 Tkinter")
    args = parser.parse_args()
    if sys.version_info < (3, 8):
        parser.exit(1, "需要 Python 3.8 或更新版本。\n")
    if sys.platform != "linux":
        parser.exit(1, "请在 Ubuntu 设备上执行此安装脚本。\n")
    try:
        install(args.directory, args.cli)
    except (Exception, KeyboardInterrupt) as exc:
        parser.exit(1, "安装未完成：{}\n已有文件不会覆盖；已下载的目录可保留后重试其中的 install.sh。\n".format(exc))


if __name__ == "__main__":
    main()
