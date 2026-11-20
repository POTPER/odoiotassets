"""Workbench directory updates using the same manifest, comparison and sync engine."""
import hashlib
import json
from pathlib import Path
import tempfile

from core import Engine, Source, SyncError, relative_path, validate_manifest
from repository import directory_manifest, repository_from_settings

EXCLUDED = {".git", ".tmp", "__pycache__", "release", "debs", "tests"}
SHARED_NAMES = {path.name for path in Path(__file__).parent.glob("*.py")}


def runtime_file(path):
    parts = Path(path).parts
    return not (set(parts) & EXCLUDED or Path(path).suffix in (".pyc", ".pyo", ".tmp")
                or Path(path).name == "aiot-workbench.desktop")


class ProgramEngine(Engine):
    scope = "workbench"
    scope_label = "工作台程序"
    allow_tool_target = True

    def manages(self, path):
        return runtime_file(path)

    def scope_scan(self, root, cancel=None):
        return {path: entry for path, entry in super().scope_scan(root, cancel).items()
                if not set(Path(path).parts) & {".tmp", "__pycache__"}}

    def preflight(self):
        # The GUI intentionally remains open during preparation. The external
        # updater holds the lifetime lock and commits only after every host exits.
        self.filesystem_preflight()

    def apply(self, *args, **kwargs):
        if not kwargs.get("_prepare_only"):
            raise SyncError("工作台只能准备更新，退出后由更新助手切换目录。")
        return super().apply(*args, **kwargs)


def repository_release(config, source=None):
    source = source or Source.remote(repository_from_settings(config), config.get("branch", ""))
    directory = relative_path(config.get("workbench_directory", "aiot-workbench"))
    tree = json.loads(source.fetch_bytes(source.tree_url()))
    if not isinstance(tree, dict) or tree.get("truncated") or not isinstance(tree.get("tree"), list):
        raise SyncError("仓库目录树不完整，禁止更新工作台。")
    prefix = directory + "/"
    nodes = [node for node in tree["tree"] if isinstance(node.get("path"), str)
             and node["path"].startswith(prefix) and runtime_file(node["path"][len(prefix):])
             and not (len(Path(node["path"][len(prefix):]).parts) == 2
                      and Path(node["path"][len(prefix):]).parts[0] in {"launcher", "engineer"}
                      and Path(node["path"]).name in SHARED_NAMES)]
    if not nodes:
        raise SyncError("资源仓库中找不到工作台目录：" + directory)
    if len(nodes) > 10000 or sum(node.get("size", 0) for node in nodes) > 256 * 1024**2:
        raise SyncError("工作台目录文件过多或超过 256 MiB，请检查仓库目录设置。")
    if any(node.get("type") not in ("tree", "blob") or node.get("mode") not in ("040000", "40000", "100644", "100755") for node in nodes):
        raise SyncError("工作台更新目录含符号链接、子模块或不支持的文件。")
    allowed = [node["path"][len(prefix):] for node in nodes if node.get("type") == "blob" and node.get("size") == 0]
    manifest = directory_manifest(source, {"id": "workbench", "name": "AIoT 工作台", "directory": directory,
        "allow_empty": allowed}, nodes)
    version_entry = next((entry for entry in manifest["entries"] if entry["path"] == "version.py" and entry["type"] == "file"), None)
    if version_entry is None:
        raise SyncError("工作台目录中缺少 version.py。")
    if version_entry["size"] > 64 * 1024:
        raise SyncError("工作台 version.py 超过合理大小。")
    with tempfile.TemporaryDirectory(prefix="workbench-version-") as temporary:
        from tool_update import package_version
        path = Path(temporary) / "version.py"
        source.download(version_entry["source"], path, version_entry["size"], "git:" + version_entry["git_sha1"], None, lambda size: None)
        raw = path.read_bytes()
        version = package_version(path)
    if len(raw) != version_entry["size"] or hashlib.sha1("blob {}\0".format(len(raw)).encode() + raw).hexdigest() != version_entry["git_sha1"]:
        raise SyncError("工作台版本文件与固定提交不匹配。")
    manifest["version"] = version
    validate_manifest(manifest)
    return {"kind": "repository", "product": "aiot-workbench", "version": version,
            "source": source.descriptor(), "manifest": manifest, "commit": source.commit,
            "notes": "来自同一资源仓库的 " + directory + "，固定提交 " + source.commit[:12]}


def compare_release(install, state, release):
    engine = ProgramEngine(install, state_dir=Path(state) / "sync")
    with engine.lock():
        engine.save_profile(release["manifest"], Source(**release["source"]))
        return engine.preview(release["manifest"], mode="strict", sync_permissions=False)


def prepare_release(install, state, release, cancel=None, log=lambda message: None):
    engine = ProgramEngine(install, state_dir=Path(state) / "sync")
    result = engine.apply(release["manifest"], Source(**release["source"]), mode="strict", cancel=cancel,
                          sync_permissions=False, log=log, _prepare_only=True)
    return None if result.get("unchanged") else Path(result["stage"])
