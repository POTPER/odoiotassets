"""一键更新编排。

先准备工具包，再严格更新 publish，成功后再交给外部助手安装工具；不依赖 Tk。
"""
import logging
from contextlib import contextmanager
import shutil
import time
from pathlib import Path

from publish_switcher.common.compat import is_relative_to
from publish_switcher.common.errors import Cancelled, SyncError, check_cancel
from publish_switcher.sync.engine import Engine
from publish_switcher.common.files import atomic_json, read_json, operation_lock
from publish_switcher.repositories.catalog import profile_manifest
from publish_switcher.repositories.discovery import discover
from publish_switcher.updates import release as tool_update


DEFAULT_TARGETS = ("/home/ubuntu/linux-arm64/publish", "/home/ubuntu/linux_arm64/publish")


def resolve_target(saved="", defaults=DEFAULT_TARGETS):
    if saved.strip():
        path = Path(saved).expanduser().absolute()
        if path.is_symlink() or not path.is_dir():
            raise SyncError("已设置的 publish 目录不存在或不是普通目录，请在工程师设置中修正：" + str(path))
        return path.resolve()
    for value in defaults:
        path = Path(value)
        if path.is_dir() and not path.is_symlink():
            return path.resolve()
    raise SyncError("未找到 publish 目录，请在工程师设置中配置；已检查：" + "、".join(map(str, defaults)))


def run_update(install, current, target, repositories, presets, extensions, release_url,
               profile_id="rk", sync_permissions=False, cancel=None, event=lambda value: None,
               settings_path=None):
    """Return a persisted result, including partial success; never install the tool here.

    A prepared tool package is handed to the existing external updater only after
    publish succeeds. That updater keeps its own rollback journal and instance lock.
    """
    logger = logging.getLogger("publish-switcher")
    result = {"started_at": time.time(), "success": False, "publish": "未更新",
              "program": "未更新", "restart": False, "phase": "checking"}
    prepared = False
    state = None
    acquired = False

    def report(phase, message, cancellable=True, **details):
        result["phase"] = phase
        logger.info(message)
        event(dict(phase=phase, message=message, cancellable=cancellable, **details))

    def persist():
        if state is not None and acquired:
            atomic_json(state / "combined-update.json", result)

    def failed(exc):
        logger.exception("一键更新未完成")
        result.update(success=False, restart=False, cancelled=isinstance(exc, Cancelled), error=str(exc))
        if prepared:
            try:
                tool_update.recover_update(install)
                result["program"] = "未安装"
            except Exception as recovery_error:
                result["error"] += "\n清理程序准备目录失败：" + str(recovery_error)
        report("cancelled" if isinstance(exc, Cancelled) else "failed", result["error"], cancellable=False)
        try:
            persist()
        except OSError:
            logger.exception("无法保存一键更新结果；请查看运行日志")

    @contextmanager
    def locked():
        nonlocal acquired
        with operation_lock(state / "combined.lock"):
            acquired = True
            try:
                yield
            except Exception as exc:
                # Clean up and record failure before another operation acquires the lock.
                failed(exc)

    try:
        install = Path(install).resolve()
        destination = resolve_target(target)
        if is_relative_to(destination, install) or is_relative_to(install, destination):
            raise SyncError("swicher 与 publish 目录不能互相包含，请在工程师设置中修正。")
        if settings_path and is_relative_to(Path(settings_path).resolve(), destination):
            raise SyncError("设置文件必须位于 publish 外。")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise SyncError("一键更新方案 ID 不能为空。")
        state = tool_update.update_state(install)
        with locked():
            # Each engine owns crash recovery; the summary never drives a second rollback.
            tool_update.recover_update(install)
            engine = Engine(destination, extensions=extensions)
            engine.startup_recover()
            result["target"] = str(destination)
            persist()
            report("checking", "正在查询 publish 更新（方案：{}）…".format(profile_id))
            items = discover(repositories, presets, lambda text: report("checking", text),
                             cancel, profile=profile_id)
            item = items[0]
            source = item["source"]
            manifest = item.get("manifest")
            if manifest is None:
                manifest = profile_manifest(item)
            result.update(profile=manifest["id"], publish_version=manifest["version"],
                          source=source.descriptor())
            check_cancel(cancel)
            with engine.lock():
                engine.preflight()
                preview = engine.preview(manifest, cancel, mode="strict", sync_permissions=sync_permissions)
                if preview["blocker"]:
                    raise SyncError(preview["blocker"])
                files = sum(entry["size"] for entry in manifest["entries"]
                            if entry["type"] == "file" and engine.manages(entry["path"]))
                if preview["changes"] and shutil.disk_usage(engine.state).free < files + preview["download_bytes"] + 16 * 1024**2:
                    raise SyncError("publish 更新磁盘空间不足。")
            result.update(changes=len(preview["changes"]), download_bytes=preview["download_bytes"])
            report("checking", "正在检查 swicher 版本…")
            release, newer = tool_update.check_release(release_url, install, current, repositories=repositories)
            result["program_version"] = release["version"]
            result["program_update_required"] = newer
            result["program_checked_at"] = time.time()
            check_cancel(cancel)
            if newer:
                report("preparing", "正在下载并校验新版 swicher…")
                received = [0]

                def progress(size):
                    received[0] += size
                    event({"phase": "preparing", "message": "正在下载新版 swicher…",
                           "cancellable": True, "received": received[0], "total": release["size"]})

                tool_update.prepare_online(install, release, current, cancel, progress)
                prepared = True
                result["program"] = "已准备"
            else:
                result["program"] = "已是最新版"
            check_cancel(cancel)
            report("publish", "正在准备并校验 publish 文件…")
            result["phase"] = "publish"
            persist()

            def committing():
                report("publish-commit", "正在切换 publish，请勿关闭…", cancellable=False)

            info = engine.apply(manifest, source, cancel,
                                lambda text: report("publish", text), mode="strict",
                                expected_actual=preview["actual"], sync_permissions=sync_permissions,
                                on_commit=committing)
            result["publish"] = "已是最新版" if info.get("unchanged") else "更新成功"
            result["publish_record"] = info
            result["restart"] = prepared
            result["success"] = True
            report("prepared" if prepared else "complete",
                   "publish 更新完成，准备重启 swicher…" if prepared else "更新完成，请重新启动主程序。",
                   cancellable=False)
            persist()
    except Exception as exc:
        failed(exc)
    return result


def last_helper_error(install):
    """Explain a failed external restart on the next GUI launch, without hiding it."""
    try:
        result = read_json(tool_update.update_state(install) / "combined-update.json")
        if result.get("phase") == "failed" and result.get("program", "").startswith("更新失败"):
            return "上次更新：publish {}；swicher {}。\n{}".format(
                result["publish"], result["program"], result.get("error", "请查看更新日志。"))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tool_update.UpdateError):
        pass
    return ""


def start_restart(install, result, engineer=False):
    """Keep a successful publish deployment if the independent tool update fails."""
    state = tool_update.update_state(install)
    try:
        result.update(program="正在交给更新助手", phase="restarting")
        atomic_json(state / "combined-update.json", result)
        tool_update.launch_update_helper(install, engineer)
    except Exception as exc:
        result.update(success=False, restart=False, program="更新失败，保留旧版", error=str(exc), phase="failed")
        try:
            tool_update.recover_update(install)
        except Exception as recovery_error:
            result["error"] += "\n程序恢复未完成：" + str(recovery_error)
        atomic_json(state / "combined-update.json", result)
        raise
