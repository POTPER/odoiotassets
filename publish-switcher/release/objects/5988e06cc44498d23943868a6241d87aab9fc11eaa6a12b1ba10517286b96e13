"""Assets 资源同步。

只比较 Assets 内容并下载缺失文件；已有同名文件与本地多余资源默认保留。
"""
from pathlib import Path

from publish_switcher.sync.engine import Engine
from publish_switcher.common.errors import SyncError, check_cancel
from publish_switcher.sync.manifests import asset_file, validate_manifest


class CachedOnlySource:
    def __init__(self, source):
        self.source = source

    def descriptor(self):
        return self.source.descriptor()

    def download(self, *args, **kwargs):
        raise SyncError("离线 Assets 缓存缺失或校验失败，禁止联网下载。")


class AssetsEngine(Engine):
    scope = "assets"
    scope_label = "Assets 资源"
    retain_links = True

    def __init__(self, target):
        raw = Path(target).expanduser().absolute()
        pending = raw.parent / (".publish-switcher-" + raw.name) / "assets-transaction.json"
        if not raw.is_dir() and not pending.exists():
            raise SyncError("publish 目录不存在，请确认路径：" + str(raw))
        super().__init__(target)
        self.journal = self.state / "assets-transaction.json"
        self.current = self.state / "assets-current.json"

    def manages(self, path):
        return asset_file(path)

    def blockers(self, manifest, paths):
        empty = [e["path"] for e in manifest["entries"] if e["type"] == "file" and self.manages(e["path"])
                 and e["path"] in paths and e["size"] == 0 and e["path"] not in manifest.get("allowed_empty", [])]
        return "待下载的 Assets 资源为空，请补齐资源或在清单中显式允许：\n" + "\n".join(empty) if empty else ""

    def validate_object(self, entry, path):
        with Path(path).open("rb") as stream:
            prefix = stream.read(1024)
        if prefix.startswith(b"version https://git-lfs.github.com/spec/v1") and b"\noid sha256:" in prefix and b"\nsize " in prefix:
            raise SyncError("资源下载结果是 Git LFS 指针而非实际文件：{}。请使用实际资源或配置 Releases 下载地址及实际大小/校验值。".format(entry["path"]))

    def preview_assets(self, manifest, cancel=None, log=lambda message: None):
        validate_manifest(manifest)
        log("正在读取本地 Assets 并计算内容哈希…")
        preview = self.preview(manifest, cancel, mode="incremental")
        entries = {e["path"]: e for e in manifest["entries"] if e["type"] == "file" and self.manages(e["path"])}
        blockers = [preview["blocker"]] if preview["blocker"] else []
        preview["resource_bytes"] = sum(e["size"] for p, e in entries.items() if p not in preview["actual"])
        preview["scope"] = "assets"
        for row in preview["comparison"]:
            check_cancel(cancel)
            path = row["path"]
            local, remote = preview["actual"].get(path), entries.get(path)
            row["local"] = local
            row["remote"] = remote
            row["action"] = "下载" if local is None and remote else "保留" if remote is None else "跳过"
            if remote and local is not None and local["type"] == "file" and local["size"] == 0 and remote["size"] > 0:
                row["status"] = "本地空文件"
            elif row["status"] in ("相同", "内容相同"):
                row["status"] = "相同"
            row["cached"] = bool(remote and self.cached(remote, cancel))
            if local is None:
                parent = Path(path).parent
                while parent.as_posix() != ".":
                    old = preview["actual"].get(parent.as_posix())
                    if old and old["type"] != "directory":
                        blockers.append("资源父目录与本地文件或符号链接冲突：" + parent.as_posix())
                    parent = parent.parent
        if not entries:
            blockers.append("所选方案不包含 Assets 资源文件。")
        preview["blocker"] = "\n".join(dict.fromkeys(blockers))
        log("Assets 比较完成：{} 项；缺失 {} 项；需下载 {:.2f} MiB。".format(
            len(preview["comparison"]), len(preview["changes"]), preview["download_bytes"] / 1024**2))
        return preview

    def download_missing(self, manifest, source, expected_actual=None, cancel=None, log=lambda message: None, offline=False):
        # Preflight and commit use the same non-blocking lock as Python/JSON/config/Demo.
        Engine(self.target).startup_recover()
        if offline:
            with self.lock():
                preview = self.preview_assets(manifest, cancel)
                if preview["download_bytes"]:
                    raise SyncError("离线模式缺少完整的 Assets 缓存，请先联网下载。")
        return self.apply(manifest, CachedOnlySource(source) if offline else source, cancel=cancel, log=log, mode="incremental", expected_actual=expected_actual)


def format_preview(manifest, preview):
    lines = ["Assets 资源比较：{} / {}".format(manifest.get("name", manifest["id"]), manifest["version"]),
             "增量规则：只下载缺失文件；已有文件（含空文件和内容不同）跳过，本地额外文件保留。",
             "缺失 {} 项；新增资源 {:.2f} MiB；实际需联网下载 {:.2f} MiB。".format(
                 len(preview["changes"]), preview["resource_bytes"] / 1024**2, preview["download_bytes"] / 1024**2)]
    for row in preview["comparison"]:
        local, remote = row["local"], row["remote"]
        lines.append("{}  {}  本地={} / 来源={} 字节  {}{}".format(
            row["status"], row["path"], local.get("size", "—") if local else "缺失", remote["size"] if remote else "无",
            row["action"], "（已校验缓存）" if row["cached"] else ""))
    if preview["blocker"]:
        lines.append("不能下载：" + preview["blocker"])
    return "\n".join(lines)


def format_details(engine, manifest, source, row):
    lines = ["Assets 资源：" + row["path"], "方案：{} / {}".format(manifest.get("name", manifest["id"]), manifest["version"]),
             "结果：{}；增量处理：{}".format(row["status"], row["action"]), "本地路径：" + str(engine.target / row["path"])]
    if source.commit:
        lines.append("固定提交：" + source.commit)
    for label, entry in (("本地", row["local"]), ("来源", row["remote"])):
        if not entry:
            lines.append(label + "文件不存在")
        else:
            lines.append("{}：类型 {}，大小 {}，权限 {}".format(label, entry["type"], entry.get("size", "—"), entry.get("mode", "—")))
            for key in ("sha256", "git_sha1"):
                if entry.get(key):
                    lines.append(label + " " + key + "：" + entry[key])
    if row["remote"]:
        lines.append("下载来源：" + str(source.url(row["remote"]["source"])))
    lines.append("按大小和内容哈希比较；权限不同不替换已有资源。此窗口仅显示检查时的信息，请重新检查以刷新。")
    return "\n".join(lines)
