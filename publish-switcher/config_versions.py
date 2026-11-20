"""Discover and transactionally activate three-file configuration bundles."""
import hashlib
import json
import os
import shutil
import stat
import time
import uuid
from pathlib import Path

from core import SyncError, atomic_json, check_cancel, digest, fsync_dir, read_json, relative_path


CONFIG_NAMES = ("TrainTaskInfo.json", "TrainOverviewInfo.json", "CodeSampleTuorialInfo.json")


def _version_path(engine, version):
    relative_path(version)
    if "/" in version:
        raise SyncError("版本名称必须是 config 下的直接子文件夹名称。")
    root = engine.target / "config"
    directory = root / version
    if root.is_symlink() or not root.is_dir():
        raise SyncError("publish/config 不存在或是符号链接。")
    if directory.is_symlink() or not directory.is_dir():
        raise SyncError("版本目录不存在或是符号链接：" + version)
    return directory


def inspect_version(engine, version):
    result = {"version": version, "valid": False, "issues": [], "mappings": [], "sources": {}}
    try:
        directory = _version_path(engine, version)
        files = list(directory.iterdir())
    except (OSError, SyncError) as exc:
        result["issues"].append(str(exc))
        return result
    for active in CONFIG_NAMES:
        prefix = Path(active).stem
        candidates = sorted((p for p in files if p.suffix.lower() == ".json" and p.stem.startswith(prefix)), key=lambda p: p.name)
        if not candidates:
            result["issues"].append("缺少 " + active)
            continue
        if len(candidates) != 1:
            result["issues"].append("同类文件冲突 " + active + "：" + "、".join(p.name for p in candidates))
            continue
        source = candidates[0]
        row = {"source": source.name, "active": active, "status": "待校验"}
        result["mappings"].append(row)
        try:
            if source.is_symlink() or not source.is_file():
                raise SyncError("源配置不是普通文件或是符号链接：" + source.name)
            raw = source.read_bytes()
            data = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(data, (list, dict)) or (active == "TrainTaskInfo.json" and not isinstance(data, list)):
                raise SyncError("任务配置应为数组，其他配置应为数组或对象：" + source.name)
            checksum = hashlib.sha256(raw).hexdigest()
            row.update(sha256=checksum, size=len(raw), status="有效")
            result["sources"][active] = {"file": source.name, "sha256": checksum}
        except (OSError, ValueError, UnicodeError, SyncError) as exc:
            row["status"] = "无效"
            result["issues"].append(source.name + "：" + str(exc))
    result["valid"] = not result["issues"] and len(result["sources"]) == 3
    return result


def list_versions(engine):
    root = engine.target / "config"
    if not root.exists():
        return []
    if root.is_symlink() or not root.is_dir():
        raise SyncError("publish/config 必须是普通目录。")
    return [inspect_version(engine, p.name) for p in sorted(root.iterdir(), key=lambda p: p.name)
            if p.is_dir() or p.is_symlink()]


def _active_snapshot(engine):
    result = {}
    for name in CONFIG_NAMES:
        path = engine.target / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise SyncError("生效配置不能是目录或符号链接：" + name)
        result[name] = {"exists": path.exists()}
        if path.exists():
            result[name].update(sha256=digest(path), mode=stat.S_IMODE(path.stat().st_mode) & 0o777)
    return result


def preview_version(engine, version):
    result = inspect_version(engine, version)
    try:
        active = _active_snapshot(engine)
        result["snapshot"] = {"sources": result["sources"], "active": active}
        for row in result["mappings"]:
            old = active[row["active"]]
            if row["status"] != "有效":
                row["action"] = "不可用"
            else:
                row["action"] = "新增" if not old["exists"] else "相同" if old["sha256"] == row["sha256"] else "替换"
    except (OSError, SyncError) as exc:
        result["issues"].append(str(exc))
        result["valid"] = False
    return result


def current_version(engine):
    try:
        active = _active_snapshot(engine)
        matches = [item["version"] for item in list_versions(engine) if item["valid"] and
                   all(active[name].get("sha256") == item["sources"][name]["sha256"] for name in CONFIG_NAMES)]
    except (OSError, SyncError):
        matches = []
    if not matches:
        return "配置版本：自定义／未识别"
    if len(matches) > 1:
        return "配置版本：匹配多个版本（" + "、".join(matches) + "）"
    return "配置版本：" + matches[0]


def _comparison_bytes(path, expected, cancel):
    from file_compare import DIFF_INPUT_LIMIT
    check_cancel(cancel)
    if path.is_symlink() or not path.is_file():
        raise SyncError("配置不是普通文件或是符号链接：" + str(path))
    before = path.stat()
    with path.open("rb") as stream:
        raw = stream.read(DIFF_INPUT_LIMIT + 1)
    checksum = hashlib.sha256(raw).hexdigest() if len(raw) <= DIFF_INPUT_LIMIT else digest(path, cancel)
    after = path.stat()
    if checksum != expected or (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise SyncError("对比期间配置发生变化，请重新检查版本：" + path.name)
    return raw if len(raw) <= DIFF_INPUT_LIMIT else None, after.st_size


def _comparison_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("JSON 含重复字段：" + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("JSON 含非标准数值：" + value)
    return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=constant)


def compare_file(engine, version, name, expected_snapshot=None, cancel=None):
    """Read-only active -> template comparison. Never recover or apply a transaction."""
    from file_compare import text_diff
    if name not in CONFIG_NAMES:
        raise SyncError("只能对比三个标准配置 JSON：" + str(name))
    with engine.lock():
        if any((engine.state / filename).exists() for filename in ("transaction.json", "assets-transaction.json", "config-transaction.json", "restore-source.json")):
            raise SyncError("存在未完成的切换，请先恢复事务，再查看配置差异。")
        preview = preview_version(engine, version)
        snapshot = preview.get("snapshot")
        if expected_snapshot is not None and snapshot != expected_snapshot:
            raise SyncError("预览后配置文件发生变化，请重新检查版本。")
        source = preview["sources"].get(name)
        if snapshot is None or source is None:
            raise SyncError("不能对比这个配置：" + "；".join(preview["issues"]))
        source_path = _version_path(engine, version) / source["file"]
        active_path = engine.target / name
        old = snapshot["active"][name]
        new_raw, new_size = _comparison_bytes(source_path, source["sha256"], cancel)
        old_raw, old_size = _comparison_bytes(active_path, old["sha256"], cancel) if old["exists"] else (b"", 0)
        options = {"local_exists": old["exists"], "cancel": cancel, "old_label": "当前生效", "new_label": "版本模板"}
        raw_diff = text_diff(old_raw, new_raw, name, **options)
        json_diff, json_note, json_equal = None, "", None
        if old_raw is None or new_raw is None:
            json_note = "文件超过 1 MiB，未生成 JSON 格式化对比；请根据摘要和原始文本预览提示检查。"
        else:
            side = "当前生效"
            try:
                old_json = _comparison_json(old_raw) if old["exists"] else None
                side = "版本模板"
                new_json = _comparison_json(new_raw)
            except (ValueError, UnicodeError) as exc:
                json_note = "{} JSON 不能可靠解析：{}。仍可查看原始文本差异。".format(side, exc)
            else:
                # Sort OBJECT keys only; array order and values remain significant.
                old_text = (json.dumps(old_json, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8") if old["exists"] else b""
                new_text = (json.dumps(new_json, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
                json_equal = old["exists"] and old_text == new_text
                json_diff = text_diff(old_text, new_text, name, **options)
                json_note = "仅为查看而统一缩进、排序对象字段；忽略排版和字段顺序，数组顺序保留。行号为格式化后的行号。"
        if preview_version(engine, version).get("snapshot") != snapshot:
            raise SyncError("对比期间配置发生变化，请重新检查版本。")
        check_cancel(cancel)
        byte_equal = old["exists"] and old["sha256"] == source["sha256"]
        status = "新增" if not old["exists"] else "相同" if byte_equal else "仅 JSON 格式不同" if json_equal else "内容不同"
        return {"version": version, "name": name, "status": status, "active_path": str(active_path), "source_path": str(source_path),
                "active": {"exists": old["exists"], "sha256": old.get("sha256"), "size": old_size},
                "source": {"sha256": source["sha256"], "size": new_size}, "raw_diff": raw_diff, "json_diff": json_diff,
                "json_note": json_note, "byte_equal": byte_equal, "json_equal": json_equal}


def format_comparison(report, include_diff=True, color=False, raw=False):
    from file_compare import format_diff
    old = report["active"]
    lines = ["配置 JSON 对比：" + report["name"], "配置版本：" + report["version"], "结果：" + report["status"],
             "当前生效：" + report["active_path"], "版本模板：" + report["source_path"],
             "当前生效：{} 字节；SHA-256：{}".format(old["size"], old["sha256"]) if old["exists"] else "当前生效文件：不存在",
             "版本模板：{} 字节；SHA-256：{}".format(report["source"]["size"], report["source"]["sha256"]),
             report["json_note"], "对比方向：当前生效 → 版本模板。只读查看，不联网、不修改文件；应用时仍原样复制模板。"]
    if include_diff:
        diff = report["raw_diff"] if raw or report["json_diff"] is None else report["json_diff"]
        lines += ["", "原始文本差异：" if raw or report["json_diff"] is None else "JSON 内容差异（格式化）：", format_diff(diff, color)]
    return "\n".join(lines)


def _write_file(path, raw, mode):
    with path.open("xb") as out:
        out.write(raw)
        out.flush()
        os.chmod(path, mode)
        os.fsync(out.fileno())


def _transaction_paths(engine, data):
    token = relative_path(data["token"])
    stage_name = relative_path(data["stage"])
    if "/" in token or "/" in stage_name or not stage_name.startswith("config-stage-"):
        raise SyncError("配置事务路径无效。")
    backup_root = engine.state / "config-backups"
    if backup_root.is_symlink():
        raise SyncError("配置备份目录不能是符号链接。")
    backup, stage = backup_root / token, engine.state / stage_name
    if backup.is_symlink() or stage.is_symlink():
        raise SyncError("配置事务目录不能是符号链接。")
    if set(data.get("old", {})) != set(CONFIG_NAMES):
        raise SyncError("配置事务中的文件集合无效。")
    return backup, stage


def recover_transaction(engine):
    journal = engine.state / "config-transaction.json"
    if not journal.exists():
        return False
    data = read_json(journal)
    if data.get("schema_version") != 1 or data.get("phase") not in ("prepared", "committed"):
        raise SyncError("配置事务记录无效，请保留记录并检查备份。")
    backup, stage = _transaction_paths(engine, data)
    engine.preflight()
    if data["phase"] != "committed":
        # Validate the whole backup before restoring anything; keep backup bytes for retry.
        for name in CONFIG_NAMES:
            old, saved = data["old"][name], backup / name
            if old["exists"] and (saved.is_symlink() or not saved.is_file() or digest(saved) != old["sha256"]):
                raise SyncError("配置备份不完整，已保留事务记录：" + name)
        _active_snapshot(engine)
        stage.mkdir(exist_ok=True)
        for name in CONFIG_NAMES:
            active, old = engine.target / name, data["old"][name]
            if old["exists"]:
                temp = stage / ("rollback-" + uuid.uuid4().hex + ".tmp")
                _write_file(temp, (backup / name).read_bytes(), old["mode"])
                os.replace(temp, active)
            else:
                active.unlink(missing_ok=True)
            fsync_dir(engine.target)
        data["phase"] = "rolled_back"
    atomic_json(backup / "record.json", data)
    if stage.exists():
        engine._remove_stage(stage)
    journal.unlink()
    fsync_dir(engine.state)
    return True


def activate_version(engine, version, expected_snapshot=None, log=lambda message: None):
    engine.startup_recover()
    with engine.lock():
        engine.recover()
        return activate_version_locked(engine, version, expected_snapshot, log)


def activate_version_locked(engine, version, expected_snapshot=None, log=lambda message: None):
    """Apply a bundle with the caller holding engine.lock() and recovery complete.

    The launcher keeps that same lock through process startup and shutdown.
    Existing GUI/CLI callers continue to use activate_version(), which owns its lock.
    """
    engine.preflight()
    preview = preview_version(engine, version)
    if not preview["valid"]:
        raise SyncError("版本无法应用：\n" + "\n".join(preview["issues"]))
    if expected_snapshot is not None and preview["snapshot"] != expected_snapshot:
        raise SyncError("预览后配置文件发生变化，请重新检查版本。")
    directory = _version_path(engine, version)
    payloads = {}
    for row in preview["mappings"]:
        raw = (directory / row["source"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise SyncError("读取期间源配置发生变化，请重新检查版本。")
        payloads[row["active"]] = raw
    token = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:12]
    backup_root = engine.state / "config-backups"
    if backup_root.is_symlink():
        raise SyncError("配置备份目录不能是符号链接。")
    backup_root.mkdir(exist_ok=True)
    backup = backup_root / token
    backup.mkdir()
    fsync_dir(backup_root)
    stage = engine.state / ("config-stage-" + uuid.uuid4().hex)
    stage.mkdir()
    journal = engine.state / "config-transaction.json"
    data = {"schema_version": 1, "phase": "prepared", "token": token, "stage": stage.name,
            "version": version, "sources": preview["sources"], "old": preview["snapshot"]["active"]}
    try:
        for name in CONFIG_NAMES:
            old = data["old"][name]
            if old["exists"]:
                raw = (engine.target / name).read_bytes()
                if hashlib.sha256(raw).hexdigest() != old["sha256"]:
                    raise SyncError("备份期间生效配置发生变化，请重新检查。")
                _write_file(backup / name, raw, old["mode"])
            source_mode = stat.S_IMODE((directory / preview["sources"][name]["file"]).stat().st_mode) & 0o777
            _write_file(stage / name, payloads[name], old.get("mode", source_mode))
        atomic_json(backup / "record.json", data)
        fsync_dir(stage)
        refreshed = preview_version(engine, version)
        if not refreshed["valid"] or refreshed["snapshot"] != preview["snapshot"]:
            raise SyncError("准备期间配置发生变化，请重新检查版本。")
        engine.preflight()
        atomic_json(journal, data)
        try:
            for name in CONFIG_NAMES:
                os.replace(stage / name, engine.target / name)
                fsync_dir(engine.target)
                log("配置已替换：" + name)
            data["phase"] = "committed"
            atomic_json(journal, data)
        except BaseException:
            recover_transaction(engine)
            raise
        recover_transaction(engine)
        log("整套配置已应用：" + version + "；备份：" + str(backup))
        return {"version": version, "backup": str(backup), "mappings": preview["mappings"]}
    finally:
        if stage.exists() and not journal.exists():
            engine._remove_stage(stage)
