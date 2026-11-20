"""GitHub/Gitee catalogs or native publish_* directories, pinned to one commit."""
import hashlib
import json
import re
import urllib.error

from core import Source, SyncError, managed, relative_path, validate_catalog, validate_manifest

DEFAULT_REPOSITORY = "https://gitee.com/potper/odoiotassets"
LEGACY_DEFAULT_REPOSITORY = "https://github.com/POTPER/odoiotassets"
REPOSITORY_DEFAULT_VERSION = 2
DEFAULT_PROFILES = [
    {"id": "jetson", "name": "Jetson", "directory": "publish_jetson",
     "executables": [], "allow_empty": []},
    {"id": "rk", "name": "RK", "directory": "publish_RK",
     "executables": [], "allow_empty": []},
]


def repository_from_settings(config):
    saved = config.get("repo") or DEFAULT_REPOSITORY
    normalized = saved.strip().rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    if config.get("repository_default_version", 1) < REPOSITORY_DEFAULT_VERSION and normalized.lower() == LEGACY_DEFAULT_REPOSITORY.lower():
        return DEFAULT_REPOSITORY
    return saved


def validate_presets(profiles):
    if not isinstance(profiles, list):
        raise SyncError("方案设置必须是 JSON 数组。")
    ids, directories = set(), set()
    for p in profiles:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", p["id"]):
            raise SyncError("方案 id 只允许字母、数字、下划线和短横线。")
        if not isinstance(p.get("name"), str) or not p["name"].strip():
            raise SyncError("方案名称不能为空。")
        directory = relative_path(p.get("directory"))
        if p["id"] in ids or directory in directories:
            raise SyncError("方案 id 或目录重复。")
        ids.add(p["id"])
        directories.add(directory)
        for key in ("executables", "allow_empty"):
            if not isinstance(p.get(key, []), list):
                raise SyncError(f"{key} 必须是相对路径数组。")
            for path in p.get(key, []):
                relative_path(path)
    return profiles


def remote_profiles(source, presets):
    """Prefer explicit publisher manifests; fall back only on catalog 404."""
    try:
        catalog = validate_catalog(json.loads(source.metadata("catalog.json").decode("utf-8-sig")))
        return [{"source": source, "profile": p} for p in catalog["profiles"]]
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    validate_presets(presets)
    tree = json.loads(source.fetch_bytes(source.tree_url()))
    if tree.get("truncated"):
        raise SyncError("远端目录列表被截断，禁止对不完整列表执行同步。请改用 catalog 清单。")
    nodes = tree.get("tree")
    if not isinstance(nodes, list):
        raise SyncError("远端返回的目录树无效。")
    directories = {n["path"] for n in nodes if n["type"] == "tree"}
    selected = [dict(p) for p in presets if p["directory"] in directories]
    covered = {p["directory"] for p in selected}
    used_ids = {p["id"] for p in selected}
    for directory in sorted(directories):
        if "/" not in directory and directory.startswith("publish_") and directory not in covered:
            suffix = directory[len("publish_"):]
            pid = re.sub(r"[^A-Za-z0-9_-]", "_", suffix).lower() or "profile"
            while pid in used_ids:
                pid += "_"
            used_ids.add(pid)
            selected.append({"id": pid, "name": suffix, "directory": directory})
    if not selected:
        raise SyncError("未找到 catalog.json 或方案目录。请修改方案设置中的 directory。")
    items = []
    for p in selected:
        profile = {"id": p["id"], "name": p["name"], "version": source.commit[:12], "directory": p["directory"]}
        items.append({"source": source, "profile": profile, "directory_preset": p, "git_tree": nodes})
    return items


def directory_manifest(source, preset, nodes):
    validate_presets([preset])
    prefix = preset["directory"] + "/"
    entries, empty = [], []
    for n in nodes:
        if not n["path"].startswith(prefix):
            continue
        path = relative_path(n["path"][len(prefix):])
        if n["type"] == "tree":
            entries.append({"type": "directory", "path": path, "mode": "0755"})
        elif n["type"] == "blob" and n["mode"] == "120000":
            data = source.metadata(n["path"])
            if hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest() != n["sha"]:
                raise SyncError("符号链接内容与 Git 提交不匹配。")
            target = data.decode("utf-8")
            entries.append({"type": "symlink", "path": path, "target": target})
        elif n["type"] == "blob" and n["mode"] in ("100644", "100755"):
            mode = "0755" if n["mode"] == "100755" or path in preset.get("executables", []) else "0644"
            entries.append({"type": "file", "path": path, "mode": mode,
                            "size": n["size"], "git_sha1": n["sha"], "source": n["path"]})
            if managed(path) and n["size"] == 0 and path not in preset.get("allow_empty", []):
                empty.append(path)
        else:
            raise SyncError(f"不支持的 Git 条目：{n['path']}（可能是子模块）")
    manifest = {"schema_version": 1, "id": preset["id"], "name": preset["name"],
                "version": source.commit[:12], "entries": entries, "root_mode": "0755",
                "commit": source.commit, "directory": preset["directory"], "allowed_empty": preset.get("allow_empty", [])}
    if empty:
        manifest["blocked_reason"] = "远端默认同步格式包含未允许的零字节文件：\n" + "\n".join(empty)
    return validate_manifest(manifest)
