"""Build a self-contained catalog from a complete publish directory."""
import argparse
import sys
import json
import os
import re
import shutil
import stat
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootstrap import configure
configure()

from compat import is_relative_to

from core import SyncError, asset_file, atomic_json, digest, managed, read_json, relative_path, scan, validate_catalog, validate_manifest
from file_formats import normalize_extensions, file_extension


def generate(source, output, profile_id, name, version, allow_empty=(), executable=(), external=None, extensions=None):
    extensions = normalize_extensions(extensions)
    source = Path(source).resolve()
    output = Path(output).resolve()
    if not source.is_dir() or output == source or is_relative_to(output, source) or is_relative_to(source, output):
        raise SyncError("源目录必须存在，输出仓库与源目录必须互不包含。")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile_id):
        raise SyncError("方案 ID 只允许字母、数字、下划线和短横线。")
    if not version or not name:
        raise SyncError("名称与版本不能为空。")
    allow_empty = {relative_path(p) for p in allow_empty}
    executable = {relative_path(p) for p in executable}
    external = external or {}
    actual = scan(source)
    unknown = (allow_empty | executable | set(external)) - actual.keys()
    if unknown:
        raise SyncError("指定的路径不在源目录中：" + ", ".join(sorted(unknown)))
    if any(actual[p]["type"] != "file" for p in allow_empty | executable | set(external)):
        raise SyncError("allow-empty、executable 和 external-map 只能指定普通文件。")
    entries = []
    prefix = f"profiles/{profile_id}/{version}"
    relative_path(prefix)
    for path, record in sorted(actual.items()):
        item = dict(record, path=path)
        if record["type"] == "file":
            published = file_extension(path) in extensions or asset_file(path) or path in external
            if published and record["size"] == 0 and path not in allow_empty:
                raise SyncError(f"拒绝发布零字节文件：{path}；确需保留时使用 --allow-empty 指定。")
            item["source"] = external.get(path, f"{prefix}/resources/{path}")
            item["payload_available"] = published
            if os.name == "nt":
                item["mode"] = "0755" if path in executable else "0644"
            elif path in executable:
                item["mode"] = f"0{int(item['mode'], 8) | 0o111:03o}"
        elif record["type"] == "directory" and os.name == "nt":
            item["mode"] = "0755"
        entries.append(item)
    manifest = {"schema_version": 1, "id": profile_id, "name": name,
                "version": version, "root_mode": "0755" if os.name == "nt" else f"0{stat.S_IMODE(source.stat().st_mode) & 0o777:03o}",
                "entries": entries, "allowed_empty": sorted(allow_empty)}
    validate_manifest(manifest)
    manifest_path = output / prefix / "manifest.json"
    if manifest_path.parent.exists():
        raise SyncError("该方案版本的输出目录已存在。请使用新版本或新输出目录。")
    catalog_path = output / "catalog.json"
    catalog = validate_catalog(read_json(catalog_path)) if catalog_path.exists() else {"schema_version": 1, "profiles": []}
    # Nothing is written until the entire source and manifest have passed validation.
    manifest_path.parent.mkdir(parents=True)
    try:
        for entry in entries:
            if entry["type"] == "file" and entry["payload_available"] and entry["path"] not in external:
                dest = output / entry["source"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / entry["path"], dest)
                if digest(dest) != entry["sha256"]:
                    raise SyncError("复制期间源文件发生变化：" + entry["path"])
        atomic_json(manifest_path, manifest)
        profile = {"id": profile_id, "name": name, "version": version,
                   "description": "", "manifest": f"{prefix}/manifest.json", "sha256": digest(manifest_path)}
        catalog["profiles"] = [p for p in catalog["profiles"] if p["id"] != profile_id] + [profile]
        validate_catalog(catalog)
        atomic_json(catalog_path, catalog)
    except BaseException:
        shutil.rmtree(manifest_path.parent)
        raise
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description="发布所选格式（默认 .py/.json/.ttf）及 Assets；其他文件只记录元数据。")
    parser.add_argument("--extensions", help="需发布的扩展名，逗号分隔，例如 .py,.json,.ttf,.otf；无扩展名用 <none>")
    parser.add_argument("source", help="完整 publish 路径")
    parser.add_argument("output", help="独立的资源仓库目录")
    parser.add_argument("--id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--allow-empty", action="append", default=[], help="允许为空的相对文件路径，可重复")
    parser.add_argument("--executable", action="append", default=[], help="需执行权限的相对文件路径，可重复")
    parser.add_argument("--external-map", help="JSON 对象：相对文件路径 -> Releases HTTPS 下载地址")
    args = parser.parse_args()
    try:
        external = read_json(args.external_map) if args.external_map else None
        if external is not None and not isinstance(external, dict):
            raise SyncError("external-map 必须是 JSON 对象。")
        path = generate(args.source, args.output, args.id, args.name, args.version,
                        args.allow_empty, args.executable, external, args.extensions)
        print("已生成：", path)
        if os.name == "nt":
            print("Windows 不保留 Linux 执行权限；请用 --executable 列出 AIotApp、启动脚本及其他可执行文件。")
    except (OSError, ValueError, SyncError) as exc:
        parser.exit(1, f"生成失败：{exc}\n")


if __name__ == "__main__":
    main()
