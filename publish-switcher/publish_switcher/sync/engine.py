"""文件同步引擎。

预览差异、下载对象、按增量或严格模式应用更新；启动时恢复未完成事务。
assert_stopped 用于更新前确认 AIoT 等进程已退出。
"""
from __future__ import annotations

from publish_switcher.common.paths import INSTALL_ROOT
import os
import shutil
import stat
import sys
import time
import uuid
from publish_switcher.common.compat import is_relative_to, remove_suffix
from publish_switcher.sync.formats import LEGACY_EXTENSIONS, describe, file_extension, normalize_extensions
from pathlib import Path
from publish_switcher.common.errors import SyncError, check_cancel
from publish_switcher.common.files import fsync_dir, operation_lock, read_json, relative_path
from publish_switcher.repositories.source import Source
from publish_switcher.sync.hashes import content_matches, equivalent, hash_field
from publish_switcher.sync.manifests import sync_blockers, validate_manifest
from publish_switcher.sync.scan import scan
from publish_switcher.sync import cache, preview, transaction


def assert_stopped(target, exclude_pids=()):
    """确认目标 publish 未被 AIoT / 相关 Python 任务占用（仅 Linux）。"""
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
    """针对某一个 publish 目录的同步引擎。

    preview 只读规划；apply 下载并切换目录；startup_recover 处理上次未完成事务。
    """

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
        if is_relative_to(INSTALL_ROOT, self.target):
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
        from publish_switcher.configuration.versions import list_versions
        with self.lock():
            return list_versions(self, user_only=user_only)

    def config_summary(self, user_only=False):
        from publish_switcher.configuration.versions import configuration_summary
        with self.lock():
            return configuration_summary(self, user_only=user_only)

    def preview_config_version(self, version, user_only=False):
        from publish_switcher.configuration.versions import preview_version
        with self.lock():
            return preview_version(self, version, user_only=user_only)

    def activate_config_version(self, version, expected_snapshot=None, log=lambda message: None, user_only=False):
        from publish_switcher.configuration.versions import activate_version
        return activate_version(self, version, expected_snapshot, log, user_only=user_only)

    def compare_config_file(self, version, name, expected_snapshot=None, cancel=None):
        from publish_switcher.configuration.versions import compare_file
        return compare_file(self, version, name, expected_snapshot, cancel)

    def task_config_status(self, user_only=False):
        from publish_switcher.configuration.versions import current_version
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
        return cache._object(self, entry)

    def cached(self, entry, cancel=None):
        return cache.cached(self, entry, cancel)

    def save_profile(self, manifest, source):
        return cache.save_profile(self, manifest, source)

    def profiles(self):
        return cache.profiles(self)

    def preview(self, manifest, cancel=None, mode="strict", actual=None, sync_permissions=False, _restore=False):
        """比较本地与清单，返回变更列表；不写入 publish。"""
        return preview.preview(self, manifest, cancel, mode, actual, sync_permissions, _restore)

    def recover(self):
        return transaction.recover(self)

    def _release_stage(self, stage):
        return transaction._release_stage(self, stage)

    @staticmethod
    def _remove_stage(path):
        # Generated trees may contain read-only directories; never follow symlinks.
        return transaction._remove_stage(path)

    def _commit(self, stage, info):
        return transaction._commit(self, stage, info)

    def apply(self, manifest, source, cancel=None, log=lambda msg: None, mode="strict", expected_actual=None, sync_permissions=False, _restore=False, on_commit=None):
        """下载缺失对象并应用更新；strict 会删除范围内多余文件。"""
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
        """启动时根据事务记录回滚或清理未完成的目录切换。"""
        return transaction.startup_recover(self)
