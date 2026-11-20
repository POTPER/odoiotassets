"""Verified, recoverable updates for AIoT Workbench itself. Compatible with Python 3.8."""
import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import uuid
import zipfile

MAX_PACKAGE = 256 * 1024 * 1024
REQUIRED_FILES = ("workbench.py", "workbench_ui.py", "workbench_paths.py", "workbench_install.py",
                  "content_update.py", "workbench_updates.py", "engineer_entry.py",
                  "launcher/aiot_launcher.py", "launcher/launcher_runtime.py", "launcher/session_cli.py",
                  "engineer/app.py", "bootstrap.py", "shared/core.py", "shared/config_versions.py",
                  "shared/program_sync.py", "version.py", "tool_update.py", "install.sh")


class UpdateError(RuntimeError):
    pass


def version_number(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){1,4}", value):
        raise UpdateError("程序版本应为数字版本号，例如 2026.11.20.1。")
    return tuple(int(part) for part in value.split(".")) + (0,) * (5 - len(value.split(".")))


def https_url(value):
    if not isinstance(value, str):
        raise UpdateError("更新地址必须使用 HTTPS。")
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise UpdateError("更新地址必须是完整的 HTTPS 地址。")
    return value.strip()


def read_json(path):
    with Path(path).open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def save_json(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".writing")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def sync_directory(path):
    if os.name == "posix":
        descriptor = os.open(str(path), os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def update_state(install):
    install = Path(install).absolute()
    if install.is_symlink() or install == install.parent:
        raise UpdateError("程序安装目录不能是符号链接或文件系统根目录。")
    state = install.parent / ("." + install.name + "-updater")
    if state.is_symlink():
        raise UpdateError("程序更新目录不能是符号链接。")
    state.mkdir(exist_ok=True)
    return state


@contextmanager
def instance_lock(install, timeout=0):
    """Every GUI instance and the external update helper use the same lock."""
    path = update_state(install) / "instance.lock"
    deadline = time.monotonic() + timeout
    with path.open("a+b", buffering=0) as stream:
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise UpdateError("另一个 AIoT Workbench 窗口或程序更新正在运行，请先关闭其他窗口。") from exc
                time.sleep(0.1)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def validate_release(data):
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("product") != "aiot-workbench":
        raise UpdateError("更新信息不是有效的 AIoT Workbench 发布信息。")
    version_number(data.get("version"))
    https_url(data.get("url"))
    if type(data.get("size")) is not int or not 0 < data["size"] <= MAX_PACKAGE:
        raise UpdateError("程序更新包大小无效或超过 256 MiB。")
    if not isinstance(data.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"]):
        raise UpdateError("更新信息缺少有效的 SHA-256。")
    name = data.get("package_file", "aiot-workbench.zip")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+\.zip", name):
        raise UpdateError("离线更新包文件名无效。")
    result = dict(data, package_file=name)
    result["notes"] = str(data.get("notes", ""))[:8000]
    return result


def remote_file(url):
    """Preserve the existing Gitee public Blob fallback for ZIP downloads."""
    from core import Source
    parsed = urllib.parse.urlsplit(https_url(url))
    parts = parsed.path.strip("/").split("/")
    if parsed.hostname == "gitee.com" and len(parts) >= 5 and parts[2] == "raw" and not parsed.query:
        owner, repo, _, ref = parts[:4]
        source = (Source(owner=owner, repo=repo, commit=ref, provider="gitee") if re.fullmatch(r"[0-9a-f]{40}", ref)
                  else Source.remote("https://gitee.com/{}/{}".format(owner, repo), urllib.parse.unquote(ref)))
        return source, urllib.parse.unquote("/".join(parts[4:]))
    return Source(), url


def check_repository(settings, install, current):
    from program_sync import repository_release, compare_release
    config = read_json(settings) if Path(settings).exists() else {}
    release = repository_release(config)
    state = update_state(install)
    required = state / "required.json"
    if required.exists() and version_number(release["version"]) < version_number(read_json(required)["version"]):
        raise UpdateError("仓库版本低于已知版本，请检查仓库分支。")
    save_json(required, release)
    # Local engineering builds can be newer than the public folder, never downgrade them.
    older = version_number(release["version"]) < version_number(current)
    preview = None if older else compare_release(install, state, release)
    release["changes"] = preview["changes"] if preview else []
    if preview and preview["blocker"]:
        raise UpdateError(preview["blocker"])
    return release, not older and (bool(release["changes"]) or version_number(release["version"]) > version_number(current))


def package_version(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VERSION" for t in node.targets):
            value = ast.literal_eval(node.value)
            version_number(value)
            return value
    raise UpdateError("更新包缺少程序版本。")


def prepare_package(install, release, package, current):
    install, package = Path(install).absolute(), Path(package)
    release = validate_release(release)
    state = update_state(install)
    if version_number(release["version"]) < version_number(current):
        raise UpdateError("不能用较旧的安装包更新程序。")
    required = state / "required.json"
    if required.exists() and version_number(release["version"]) < version_number(read_json(required)["version"]):
        raise UpdateError("此离线包低于已知的必更版本，请准备最新安装包。")
    if package.stat().st_size != release["size"]:
        raise UpdateError("程序更新包大小不匹配。")
    digest = hashlib.sha256()
    with package.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != release["sha256"]:
        raise UpdateError("程序更新包 SHA-256 校验失败。")
    if (state / "pending.json").exists():
        raise UpdateError("存在未完成的程序更新，请关闭并重新打开工具。")
    if not install.is_dir() or os.path.ismount(install):
        raise UpdateError("程序安装目录不存在或是挂载点，无法整体替换。")
    token = uuid.uuid4().hex
    stage = state / ("stage-" + token)
    stage.mkdir()
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 1024 ** 3:
                raise UpdateError("程序更新包展开后过大。")
            required_space = sum(((entry.file_size + 4095) // 4096 + 1) * 4096 for entry in entries)
            if shutil.disk_usage(install.parent).free < required_space:
                raise UpdateError("程序更新磁盘空间不足。")
            seen = set()
            for entry in entries:
                raw_name = entry.orig_filename
                path = PurePosixPath(raw_name)
                mode = entry.external_attr >> 16
                if (not path.parts or path.parts[0] != "aiot-workbench" or path.is_absolute()
                        or ".." in path.parts or "\\" in raw_name or ":" in raw_name
                        or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFDIR, stat.S_IFREG)):
                    raise UpdateError("程序更新包包含无效路径或特殊文件。")
                relative = path.parts[1:]
                if not relative:
                    continue
                key = "/".join(relative).casefold()
                if key in seen:
                    raise UpdateError("程序更新包包含重复路径。")
                seen.add(key)
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
        if any(not (stage / name).is_file() for name in REQUIRED_FILES):
            raise UpdateError("更新包缺少完整的 AIoT Workbench 程序文件。")
        for module in stage.rglob("*.py"):
            compile(module.read_bytes(), str(module), "exec")
        if package_version(stage / "version.py") != release["version"]:
            raise UpdateError("更新信息与安装包内的版本不一致。")
        record = {"phase": "prepared", "stage": stage.name, "backup": "backup-" + token, "version": release["version"]}
        save_json(state / "pending.json", record)
        return record
    except BaseException:
        shutil.rmtree(stage)
        raise


def prepare_online(install, release, current, cancel, progress):
    if release.get("kind") == "repository":
        return prepare_repository(install, release, current, cancel, progress)
    state = update_state(install)
    package = state / "download.zip"
    source, location = remote_file(release["url"])
    source.download(location, package, release["size"], release["sha256"], cancel, progress)
    return prepare_package(install, release, package, current)


def prepare_repository(install, release, current, cancel=None, progress=lambda size: None):
    from program_sync import prepare_release
    if version_number(release["version"]) < version_number(current):
        return None
    state = update_state(install)
    if (state / "pending.json").exists():
        raise UpdateError("存在未完成的程序更新，请重新启动工作台。")
    required = state / "required.json"
    if required.exists() and version_number(release["version"]) < version_number(read_json(required)["version"]):
        raise UpdateError("检查后发现更高版本，请重新检查。")
    stage = prepare_release(install, state, release, cancel)
    if stage is None:
        return None
    try:
        if any(not (stage / name).is_file() or (stage / name).stat().st_size == 0 for name in REQUIRED_FILES):
            raise UpdateError("仓库的 aiot-workbench 目录缺少完整程序文件。")
        for module in stage.rglob("*.py"):
            if not set(module.relative_to(stage).parts) & {"debs", "tests", ".tmp", "__pycache__", "release"}:
                compile(module.read_bytes(), str(module), "exec")
        if package_version(stage / "version.py") != release["version"]:
            raise UpdateError("工作台目录版本校验失败。")
        token = uuid.uuid4().hex
        ready = state / ("stage-" + token)
        os.replace(stage, ready)
        stage = ready
        record = {"phase": "prepared", "stage": stage.name, "backup": "backup-" + token,
                  "version": release["version"], "commit": release["commit"], "replace_program": True}
        save_json(state / "pending.json", record)
        return record
    except BaseException:
        shutil.rmtree(stage)
        raise


def prepare_offline(install, manifest, current):
    manifest = Path(manifest)
    release = validate_release(read_json(manifest))
    return prepare_package(install, release, manifest.parent / release["package_file"], current)


def pending_paths(install):
    state = update_state(install)
    record = read_json(state / "pending.json")
    for key in ("stage", "backup"):
        if not re.fullmatch(key + r"-[0-9a-f]{32}", record.get(key, "")):
            raise UpdateError("程序更新恢复记录路径无效。")
        if (state / record[key]).is_symlink():
            raise UpdateError("程序更新目录不能是符号链接。")
    return state, record, state / record["stage"], state / record["backup"]


def recover_update(install):
    install = Path(install).absolute()
    state = update_state(install)
    if not (state / "pending.json").exists():
        return
    state, record, stage, backup = pending_paths(install)
    if record["phase"] != "committed" and backup.is_dir():
        if install.exists():
            os.replace(install, state / ("failed-" + uuid.uuid4().hex))
        os.replace(backup, install)
        sync_directory(install.parent)
        sync_directory(state)
    if not install.is_dir():
        raise UpdateError("程序更新恢复失败，请从完整安装包恢复工具目录。")
    if stage.is_dir():
        shutil.rmtree(stage)
    (state / "pending.json").unlink()


def commit_update(install):
    install = Path(install).absolute()
    state, record, stage, backup = pending_paths(install)
    if record["phase"] != "prepared" or not stage.is_dir():
        raise UpdateError("程序更新准备记录无效。")
    try:
        os.replace(install, backup)
        sync_directory(install.parent)
        sync_directory(state)
        record["phase"] = "backed_up"
        save_json(state / "pending.json", record)
        os.replace(stage, install)
        sync_directory(install.parent)
        sync_directory(state)
        probe = subprocess.run([sys.executable, "-B", str(install / "workbench.py"), "--version"],
                               cwd=str(install.parent), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               encoding="utf-8", errors="replace", timeout=30)
        if probe.returncode or probe.stdout.strip() != "AIoT Workbench " + record["version"]:
            raise UpdateError("新版启动校验失败：" + probe.stderr[-2000:])
        record["phase"] = "committed"
        save_json(state / "pending.json", record)
        save_json(state / "last-update.json", {"version": record["version"], "backup": str(backup), "error": None})
        (state / "pending.json").unlink()
    except BaseException as exc:
        recover_update(install)
        save_json(state / "last-update.json", {"error": str(exc)})
        raise


def launch_update_helper(install, engineer=False):
    state = update_state(install)
    helper = state / "apply-update.py"
    shutil.copyfile(Path(__file__), helper)
    command = [sys.executable, "-B", str(helper), "--apply", str(Path(install).absolute())]
    if engineer:
        command.append("--engineer")
    options = {"start_new_session": True} if os.name == "posix" else {"creationflags": subprocess.CREATE_NO_WINDOW}
    with (state / "helper.log").open("a", encoding="utf-8") as log:
        return subprocess.Popen(command, cwd=str(state), stdout=log, stderr=log, **options)


def helper_main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--apply")
    action.add_argument("--launch")
    parser.add_argument("--engineer", action="store_true")
    args = parser.parse_args()
    install = Path(args.apply or args.launch)
    with instance_lock(install, timeout=90):
        if args.launch:
            recover_update(install)
        else:
            try:
                commit_update(install)
            except Exception as exc:
                print(str(exc), file=sys.stderr, flush=True)
    command = [sys.executable, str(install / "workbench.py"), "gui", "--desktop"]
    if args.engineer:
        command.append("--engineer")
    os.chdir(install)
    os.execv(sys.executable, command)


if __name__ == "__main__":
    helper_main()
