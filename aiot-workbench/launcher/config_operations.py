"""Headless, lock-protected configuration selection using Switcher transactions."""
from pathlib import Path

from collection_config import recover_overlay
from config_versions import activate_version_locked, clear_task_files_locked, current_version, list_versions, preview_version
from core import Engine, SyncError, check_cancel


def configure_questions(target, version=None, exclude_pids=(), cancel=None, log=lambda message: None, clear_only=False):
    target = Path(target)
    if not target.is_dir():
        raise SyncError("未找到 publish 安装目录，请检查部署设置。")
    engine = Engine(target)
    engine.exclude_pids = exclude_pids
    engine.startup_recover()
    with engine.lock():
        engine.recover()
        recover_overlay(engine)
        engine.preflight()
        check_cancel(cancel)
        if clear_only:
            result = clear_task_files_locked(engine, log=log)
            result["current"] = current_version(engine, user_only=True)
            return result
        if version is None:
            return {"versions": list_versions(engine, user_only=True), "current": current_version(engine, user_only=True)}
        preview = preview_version(engine, version, user_only=True)
        if not preview["valid"]:
            raise SyncError("赛题不可用：" + "；".join(preview["issues"]))
        # Once replacement starts, finish commit/rollback even if stop is requested.
        check_cancel(cancel)
        result = activate_version_locked(engine, version, preview["snapshot"], log=log, cleanup_task_files=True, user_only=True)
        result["current"] = current_version(engine, user_only=True)
        return result
