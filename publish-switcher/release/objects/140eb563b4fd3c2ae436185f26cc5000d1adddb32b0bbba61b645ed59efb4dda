"""只读差异预览。

比较本地与清单，生成将下载、替换、删除的变更列表及下载字节估算，不改磁盘。
"""
import os
from publish_switcher.common.errors import SyncError
from publish_switcher.sync.hashes import content_matches, equivalent, hash_field
from publish_switcher.sync.manifests import validate_manifest


def preview(engine, manifest, cancel=None, mode="strict", actual=None, sync_permissions=False, _restore=False):
    validate_manifest(manifest, allow_empty_entries=_restore)
    if mode not in ("incremental", "strict"):
        raise SyncError("更新模式应为 incremental 或 strict。")
    if engine.target.is_symlink():
        raise SyncError("目标不能是符号链接。")
    if actual is None:
        actual = engine.scope_scan(engine.target, cancel) if engine.target.exists() else {}
    desired = {e["path"]: e for e in manifest["entries"] if e["type"] == "file" and engine.manages(e["path"])}
    changes, downloads, notices, comparison = [], 0, [], []
    planned_objects = set()
    for path, entry in desired.items():
        old = actual.get(path)
        same_content = content_matches(old, entry)
        same = same_content and (not sync_permissions or equivalent(old, entry))
        if old is None:
            status = "新增"
        elif old["type"] != "file":
            status = "路径冲突"
        elif not same_content:
            status = "内容不同"
        elif not equivalent(old, entry):
            status = "权限不同" if sync_permissions else "内容相同"
        else:
            status = "相同"
        permission_note = "{} / {}（{}）".format(old.get("mode", "—") if old else "—", entry["mode"],
                                                  "Windows 不比较" if os.name != "posix" else "新文件用仓库" if old is None else "按仓库同步" if sync_permissions and mode == "strict" else "保留本地")
        comparison.append({"path": path, "status": status, "incremental": "新增" if old is None else "跳过", "strict": "新增" if old is None else "不变" if same else "替换", "permissions": permission_note})
        if mode == "incremental" and old is not None:
            continue
        if old is None:
            changes.append(("新增", path))
        elif not same:
            changes.append(("替换", path))
        if entry["type"] == "file":
            reusable = content_matches(old, entry)
            key = hash_field(entry)
            object_key = (key, entry[key], entry["size"])
            if not reusable and object_key not in planned_objects and not engine.cached(entry, cancel):
                downloads += entry["size"]
                planned_objects.add(object_key)
    local_only = [path for path, old in actual.items() if old["type"] == "file" and engine.manages(path) and path not in desired]
    comparison += [{"path": p, "status": "仅本地", "incremental": "保留", "strict": "删除"} for p in local_only]
    if mode == "strict":
        changes += [("删除", path) for path in local_only]
    for e in manifest["entries"]:
        if e["type"] == "directory" or e["path"] in desired:
            continue
        old = actual.get(e["path"])
        if old is None:
            notices.append(("仅提示：本机缺失，不下载", e["path"]))
        elif e["type"] != old["type"] or (e["type"] == "file" and e["size"] != old["size"]):
            notices.append(("仅提示：类型或大小不同，保留本机", e["path"]))
        elif e["type"] == "file" and e["size"] == 0:
            notices.append(("仅提示：远端为空，保留本机", e["path"]))
    remote_paths = {e["path"] for e in manifest["entries"]}
    notices += [("仅提示：本地额外文件，保留", p) for p, old in actual.items()
                if old["type"] != "directory" and not engine.manages(p) and p not in remote_paths]
    included = set(desired) if mode == "strict" else set(desired) - set(actual)
    return {"changes": sorted(changes, key=lambda x: x[1]), "download_bytes": downloads, "mode": mode, "sync_permissions": bool(sync_permissions),
            "extensions": list(engine.extensions),
            "actual": actual, "comparison": sorted(comparison, key=lambda row: row["path"]),
            "notices": sorted(notices, key=lambda x: x[1]),
            "blocker": ("请至少勾选一种同步文件格式。" if not engine.extensions else engine.blockers(manifest, included))}

