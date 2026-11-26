"""Automatic startup updates, channel failover and local-use eligibility."""
from pathlib import Path

from publish_switcher.common.compat import is_relative_to
from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import read_json
from publish_switcher.sync.engine import Engine
from publish_switcher.updates import release, unified
from publish_switcher.updates.channels import channel_name, selected_channel


def check_local_program(install, current):
    state = release.update_state(install)
    required = state / "required.json"
    if required.exists() and release.version_number(read_json(required)["version"]) > release.version_number(current):
        raise SyncError("已知有必更版本。")
    if (state / "pending.json").exists():
        raise SyncError("程序更新尚未恢复。")


def local_target(install, current, target, settings_path):
    check_local_program(install, current)
    destination = unified.resolve_target(target, allow_pending=True)
    if is_relative_to(destination, install) or is_relative_to(install, destination):
        raise SyncError("swicher 与 publish 目录不能互相包含。")
    if settings_path and is_relative_to(Path(settings_path).resolve(), destination):
        raise SyncError("设置文件必须位于 publish 外。")
    Engine(destination).startup_recover()
    if not destination.is_dir():
        raise SyncError("恢复后 publish 目录不可用，请在工程师设置中检查。")
    return str(destination)


def include_local_option(result, install, current, target, settings_path):
    try:
        result["local_target"] = local_target(install, current, result.get("target", target), settings_path)
    except (OSError, ValueError, TypeError, KeyError, SyncError, release.UpdateError) as exc:
        result["local_error"] = str(exc)
    return result


def run_startup_update(*, install, current, target, repositories, presets, extensions, release_url,
                       profile_id, sync_permissions, cancel, settings_path, event):
    result = {"success": False, "restart": False, "error": "没有配置更新通道。"}
    failures = []
    for index in range(len(repositories)):
        label = channel_name(index)
        event(dict(phase="checking", message="正在检查更新…", reset=True, cancellable=True))
        try:
            selected, address = selected_channel(repositories, index, release_url)
        except (ValueError, SyncError) as exc:
            result["error"] = str(exc)
            break
        result = unified.run_update(
            install, current, target, selected, presets, extensions, address,
            profile_id=profile_id, sync_permissions=sync_permissions, cancel=cancel,
            settings_path=settings_path, startup=True, event=event,
        )
        result["channel"] = index
        if result["success"]:
            return result
        if result.get("cancelled"):
            break
        failures.append("{} · {}".format(label, result["error"]))
        if not result.get("retry_source"):
            break
    if failures and not result.get("cancelled"):
        result["error"] = "\n".join(failures)
    return include_local_option(result, install, current, target, settings_path)


def resume_startup_update(install, current, target, settings_path):
    try:
        record = read_json(release.update_state(install) / "combined-update.json")
        if record.get("phase") == "complete" and record.get("success") and record.get("program_version") == current:
            if record.get("publish_skipped"):
                check_local_program(install, current)
                return dict(record, restart=False)
            resolved = local_target(install, current, record.get("target", target), settings_path)
            return dict(record, restart=False, target=resolved)
        message = record.get("error") or "上次更新未完成。"
    except (OSError, ValueError, TypeError, KeyError, AttributeError, SyncError, release.UpdateError) as exc:
        message = str(exc)
    return include_local_option(dict(success=False, restart=False, error=message),
                                install, current, target, settings_path)
