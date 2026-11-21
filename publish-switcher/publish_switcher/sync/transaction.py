"""事务与崩溃恢复。

用 transaction.json 记录目录切换阶段；中途断电或崩溃后，下次启动可回滚或续做。
"""
import os
import shutil
import time
import uuid
from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import atomic_json, fsync_dir, read_json, relative_path


def recover(engine):
    """Recover pending config bundles and directory swaps before any operation."""
    assets_recovered = False
    if engine.scope != "assets" and (engine.state / "assets-transaction.json").exists():
        from publish_switcher.sync.assets import AssetsEngine
        assets_recovered = AssetsEngine(engine.target).recover()
    from publish_switcher.configuration.versions import recover_transaction
    config_recovered = recover_transaction(engine)
    if not engine.journal.exists():
        return config_recovered or assets_recovered
    data = read_json(engine.journal)
    backup = engine.state / "backups" / relative_path(data["backup"])
    stage = engine.state / relative_path(data["stage"])
    # Transaction paths must be immediate children of their designated directories.
    if backup.parent != engine.state / "backups" or stage.parent != engine.state:
        raise SyncError("事务记录中的路径无效。")
    engine.preflight()
    if data.get("phase") == "committed":
        atomic_json(engine.current, data["new_state"])
        atomic_json(engine.state / "history" / (backup.name + ".json"), data)
    else:
        if backup.exists():
            if engine.target.exists():
                if stage.exists():
                    engine._release_stage(stage)
                os.rename(engine.target, stage)
            os.rename(backup, engine.target)
            fsync_dir(engine.target.parent)
            fsync_dir(backup.parent)
        elif not data["had_target"] and engine.target.exists():
            if stage.exists():
                engine._release_stage(stage)
            os.rename(engine.target, stage)
            fsync_dir(engine.target.parent)
        elif data["had_target"] and not engine.target.exists():
            raise SyncError("恢复失败：原目录和备份均不存在，请人工检查事务记录。")
        if data["old_state"] is None:
            engine.current.unlink(missing_ok=True)
        else:
            atomic_json(engine.current, data["old_state"])
    if stage.exists():
        engine._release_stage(stage)
    engine.journal.unlink()
    fsync_dir(engine.state)
    return True



def _release_stage(engine, stage):
    """A restore's staged tree is a real backup, never discard it on rollback."""
    record = engine.state / "restore-source.json"
    if record.exists():
        data = read_json(record)
        backup = engine.state / "backups" / relative_path(data["backup"])
        if backup.parent != engine.state / "backups":
            raise SyncError("恢复来源记录无效。")
        if data["stage"] == stage.name and not backup.exists():
            os.rename(stage, backup)
            fsync_dir(backup.parent)
            fsync_dir(engine.state)
            return
    engine._remove_stage(stage)



def _remove_stage(path):
    # Generated trees may contain read-only directories; never follow symlinks.
    for root, dirs, files in os.walk(path, followlinks=False):
        os.chmod(root, 0o700)
    shutil.rmtree(path)



def _commit(engine, stage, info):
    engine.preflight()
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    backup = engine.state / "backups" / token
    old = read_json(engine.current) if engine.current.exists() else None
    new = dict(info, backup=token)
    data = {"phase": "prepared", "backup": token, "stage": stage.name,
            "had_target": engine.target.exists(), "old_state": old, "new_state": new}
    atomic_json(engine.journal, data)
    try:
        if engine.target.exists():
            os.rename(engine.target, backup)
            fsync_dir(engine.target.parent)
            fsync_dir(backup.parent)
        os.rename(stage, engine.target)
        fsync_dir(engine.target.parent)
        fsync_dir(engine.state)
        data["phase"] = "committed"
        atomic_json(engine.journal, data)
        atomic_json(engine.current, new)
        atomic_json(engine.state / "history" / (token + ".json"), data)
        engine.journal.unlink()
        fsync_dir(engine.state)
    except BaseException:
        # A committed deployment is finalized by recover; an uncommitted one rolls back.
        engine.recover()
        raise
    return new



def startup_recover(engine):
    with engine.lock():
        recovered = engine.recover()
        record = engine.state / "restore-source.json"
        if record.exists():
            data = read_json(record)
            stage = engine.state / relative_path(data["stage"])
            backup = engine.state / "backups" / relative_path(data["backup"])
            if stage.parent != engine.state or backup.parent != engine.state / "backups":
                raise SyncError("恢复来源记录无效。")
            if stage.exists() and not backup.exists():
                os.rename(stage, backup)
                fsync_dir(engine.state)
                fsync_dir(backup.parent)
            record.unlink()
            recovered = True
        return recovered

