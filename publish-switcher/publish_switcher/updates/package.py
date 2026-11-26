"""安装包校验。

校验发布 JSON、ZIP 路径安全、大小与 SHA-256；与独立安装脚本共用规则。
"""
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
REQUIRED_FILES = BASE_FILES + UPDATE_FILES + INTERFACE_FILES + PACKAGE_FILES + LAYOUT_FILES + STARTUP_FILES + ICON_FILES


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
    return result


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
    if number >= (2026, 11, 26, 1):
        return REQUIRED_FILES
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
