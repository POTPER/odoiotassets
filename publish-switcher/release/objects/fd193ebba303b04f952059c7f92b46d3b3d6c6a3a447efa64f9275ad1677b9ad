"""一键更新编排。

先准备工具包，再严格更新 publish，成功后再交给外部助手安装工具；不依赖 Tk。
"""
import logging
from contextlib import contextmanager
import shutil
import time
import urllib.error
from pathlib import Path

from publish_switcher.common.compat import is_relative_to
from publish_switcher.common.errors import Cancelled, SyncError, check_cancel
from publish_switcher.sync.engine import Engine
from publish_switcher.common.files import atomic_json, read_json, operation_lock
from publish_switcher.repositories.catalog import profile_manifest
from publish_switcher.repositories.discovery import discover, ProfileUnavailable
from publish_switcher.repositories.source import transient_network_error
from publish_switcher.updates import release as tool_update


DEFAULT_TARGETS = ("/home/ubuntu/linux-arm64/publish", "/home/ubuntu/linux_arm64/publish")


class PublishTargetMissing(SyncError):
    """No installed publish directory was found."""


def resolve_target(saved="", defaults=DEFAULT_TARGETS, *, allow_pending=False):
    def available(path):
        if path.is_symlink():
            return False
        if path.is_dir():
            return True
        if allow_pending and not path.exists():
            state = Engine.state_path(path.resolve())
            return not state.is_symlink() and (state / "transaction.json").is_file()
        return False

    if saved.strip():
        path = Path(saved).expanduser().absolute()
        if not available(path):
            if not path.is_symlink() and not path.exists():
                raise PublishTargetMissing("已设置的 publish 目录不存在：" + str(path))
            raise SyncError("已设置的 publish 不是普通目录：" + str(path))
        return path.resolve()
    for value in defaults:
        path = Path(value)
        if available(path):
            return path.resolve()
    raise PublishTargetMissing("未找到 publish 目录；已检查：" + "、".join(map(str, defaults)))


def can_retry_source(exc):
    while exc is not None:
        if isinstance(exc, ProfileUnavailable) or transient_network_error(exc):
            return True
        if isinstance(exc, urllib.error.HTTPError) and exc.code in (401, 403, 404):
            return True
        exc = exc.__cause__
    return False


def run_update(install, current, target, repositories, presets, extensions, release_url,
               profile_id="rk", sync_permissions=False, cancel=None, event=lambda value: None,
               settings_path=None, *, startup=False, allow_missing_target=False):
    """Return a persisted result, including partial success; never install the tool here.

    A prepared tool package is handed to the external updater after the publish
    deployment, when a target is present. The updater owns the tool rollback.
    """
    logger = logging.getLogger("publish-switcher")
    result = {"started_at": time.time(), "success": False, "publish": "未更新",
              "program": "未更新", "restart": False, "phase": "checking"}
    prepared = False
    state = None
    acquired = False
    commit_started = False
    allow_missing_target = startup or allow_missing_target

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
        if startup:
            result["retry_source"] = not commit_started and not result["cancelled"] and can_retry_source(exc)
        if prepared:
            try:
                tool_update.recover_update(install)
                result["program"] = "未安装"
            except Exception as recovery_error:
                result["error"] += "\n清理程序准备目录失败：" + str(recovery_error)
                if startup:
                    result["retry_source"] = False
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

    def check_program():
        report("checking", "正在检查 swicher 版本…")
        release, newer = tool_update.check_release(release_url, install, current, repositories=repositories)
        result.update(program_version=release["version"], program_update_required=newer,
                      program_checked_at=time.time())
        check_cancel(cancel)
        return release, newer

    try:
        check_cancel(cancel)
        install = Path(install).resolve()
        try:
            destination = resolve_target(target, allow_pending=allow_missing_target)
        except PublishTargetMissing as exc:
            if not allow_missing_target:
                raise
            logger.info("跳过文件更新：%s", exc)
            destination = None
            result.update(publish="未找到目录", publish_skipped=True)
        if destination is not None:
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
            if destination is not None:
                engine = Engine(destination, extensions=extensions)
                engine.startup_recover()
                if allow_missing_target and not destination.is_dir():
                    raise SyncError("恢复后 publish 目录不可用，请在工程师设置中检查。")
                result["target"] = str(destination)
            persist()
            if startup:
                release, newer = check_program()
                report("connected", "连接成功")
            if destination is not None:
                message = "正在查询 publish 更新（方案：{}）…".format(profile_id)
                log_query = logger.info if startup else lambda text: report("checking", text)
                log_query(message)
                items = discover(repositories, presets, log_query, cancel, profile=profile_id)
                item = items[0]
                source = item["source"]
                manifest = item.get("manifest")
                if manifest is None:
                    manifest = profile_manifest(item)
                result.update(profile=manifest["id"], publish_version=manifest["version"],
                              source=source.descriptor())
                check_cancel(cancel)
                with engine.lock():
                    if not startup:
                        engine.preflight()
                    preview = engine.preview(manifest, cancel, mode="strict", sync_permissions=sync_permissions)
                    if preview["blocker"]:
                        raise SyncError(preview["blocker"])
                    if startup and preview["changes"]:
                        engine.preflight()
                    files = sum(entry["size"] for entry in manifest["entries"]
                                if entry["type"] == "file" and engine.manages(entry["path"]))
                    if preview["changes"] and shutil.disk_usage(engine.state).free < files + preview["download_bytes"] + 16 * 1024**2:
                        raise SyncError("publish 更新磁盘空间不足。")
                result.update(changes=len(preview["changes"]), download_bytes=preview["download_bytes"])
            if not startup:
                release, newer = check_program()
            if newer:
                report("preparing", "正在下载并校验新版 swicher…")
                received = [0]
                download_total = [release["size"]]

                def publish_transfer(phase, message, count, total, reset=False):
                    event(dict(phase=phase, message=message, cancellable=True,
                               received=count, total=total, reset=reset))

                def progress(size):
                    received[0] += size
                    publish_transfer("preparing", "正在下载新版 swicher…", received[0], download_total[0])

                def reset_transfer():
                    received[0] = 0
                    publish_transfer("preparing", "正在下载新版 swicher…", 0, download_total[0], True)

                def plan_transfer(total):
                    download_total[0] = total
                    reset_transfer()

                download_options = {"on_attempt": reset_transfer, "on_plan": plan_transfer}
                tool_update.prepare_online(install, release, current, cancel, progress, **download_options)
                prepared = True
                result["program"] = "已准备"
            else:
                result["program"] = "已是最新版"
            check_cancel(cancel)

            def committing():
                nonlocal commit_started
                commit_started = True
                report("publish-commit", "正在切换 publish，请勿关闭…", cancellable=False)
                if startup:
                    check_cancel(cancel)

            def resource_progress(count, total, reset):
                event(dict(phase="publish-download", message="正在下载 publish 文件…", cancellable=True,
                           received=count, total=total, reset=reset))

            if destination is not None:
                report("publish", "正在准备并校验 publish 文件…")
                persist()
                apply_options = {"on_download": resource_progress} if startup else {}
                info = engine.apply(manifest, source, cancel,
                                    lambda text: report("publish", text), mode="strict",
                                    expected_actual=preview["actual"], sync_permissions=sync_permissions,
                                    on_commit=committing, **apply_options)
                result["publish"] = "已是最新版" if info.get("unchanged") else "更新成功"
                result["publish_record"] = info
            result["restart"] = prepared
            result["success"] = True
            message = "更新成功" if result["publish"] == "更新成功" else "已是最新版本"
            if prepared:
                message = "准备重启…"
            report("prepared" if prepared else "complete", message, cancellable=False)
            if prepared and not commit_started and (startup or destination is None):
                check_cancel(cancel)
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


def start_restart(install, result, engineer=False, *, startup=False):
    """Keep a successful publish deployment if the independent tool update fails."""
    state = tool_update.update_state(install)
    try:
        result.update(program="正在交给更新助手", phase="restarting")
        atomic_json(state / "combined-update.json", result)
        options = {"startup": True} if startup else {}
        tool_update.launch_update_helper(install, engineer, **options)
    except Exception as exc:
        result.update(success=False, restart=False, program="更新失败，保留旧版", error=str(exc), phase="failed")
        try:
            tool_update.recover_update(install)
        except Exception as recovery_error:
            result["error"] += "\n程序恢复未完成：" + str(recovery_error)
        atomic_json(state / "combined-update.json", result)
        raise
