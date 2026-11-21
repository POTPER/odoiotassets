"""命令行共用逻辑。

读取方案列表、权限策略与预览输出格式，供各 SSH 子命令复用。
"""
import logging
import os
import sys
from pathlib import Path

from publish_switcher.sync.engine import Engine
from publish_switcher.repositories.source import Source
from publish_switcher.common.errors import SyncError
from publish_switcher.common.files import read_json
from publish_switcher.sync.manifests import validate_catalog
from publish_switcher.sync.formats import describe
from publish_switcher.repositories.catalog import DEFAULT_PROFILES, profile_manifest, validate_presets
from publish_switcher.repositories.discovery import candidates as repository_candidates, discover as discover_repositories


def permission_policy(args, config):
    return config.get("sync_permissions") is True if args.sync_permissions is None else args.sync_permissions


def stdout_colors():
    return sys.stdout.isatty() and "NO_COLOR" not in os.environ


def get_engine(args, config, recover=True):
    target = args.target or config.get("target")
    if not target:
        raise SyncError("尚未设置 publish 目录，请在命令前加 --target /实际路径/publish。")
    engine = Engine(target, extensions=getattr(args, "extensions", None) if getattr(args, "extensions", None) is not None else config.get("file_extensions"))
    if recover:
        engine.startup_recover()
    return engine


def profiles(args, config, engine=None):
    if args.offline:
        engine = engine or get_engine(args, config)
        return [{"source": Source(**p["source"]), "manifest": p["manifest"]} for p in engine.profiles()]
    if args.local_catalog:
        path = Path(args.local_catalog).expanduser().resolve()
        catalog = validate_catalog(read_json(path))
        return [{"source": Source(local=path.parent), "profile": p} for p in catalog["profiles"]]
    presets = validate_presets(config.get("directory_profiles", DEFAULT_PROFILES))
    explicit = not getattr(args, "use_repository_sources", args.repo is None)
    values = repository_candidates(config, args.repo, args.branch, explicit=explicit, extra=getattr(args, "fallback_repo", []))
    if not explicit and getattr(args, "fallback_repo", []):
        values += repository_candidates(config, args.repo, args.branch, explicit=True, extra=args.fallback_repo)[1:]
    interactive = getattr(args, "command", None) == "cli"
    return discover_repositories(values, presets, log=logging.getLogger("publish-switcher").info,
                                 profile=None if interactive else getattr(args, "profile", None),
                                 version=None if interactive else getattr(args, "version", None))


def selected(args, items):
    candidates = []
    for item in items:
        p = item.get("manifest") or item["profile"]
        if p["id"] == args.profile and (not args.version or p["version"] == args.version):
            candidates.append(item)
    if not candidates:
        raise SyncError("未找到方案，请先运行 list 查看 ID；离线模式需先缓存配置。")
    if len(candidates) > 1:
        raise SyncError("存在多个匹配的缓存方案，请使用 --version 指定版本。")
    item = candidates[0]
    if "manifest" not in item:
        item["manifest"] = profile_manifest(item)
    return item


def show_preview(manifest, preview):
    print("方案：{} / {}".format(manifest.get("name", manifest["id"]), manifest["version"]))
    print("所选格式变更 {} 项；需下载 {:.2f} MiB".format(len(preview["changes"]), preview["download_bytes"] / 1024**2))
    print("同步格式：" + describe(preview.get("extensions", ())))
    print("更新模式：" + preview["mode"])
    print("权限策略：" + ("严格更新同步仓库权限，增量仍跳过已有文件" if preview["sync_permissions"] else "保留本地已有文件权限，新文件使用仓库权限"))
    for row in preview["comparison"]:
        print("比较：{}  {}  增量={} / 严格={}".format(row["status"], row["path"], row["incremental"], row["strict"]))
        if row.get("permissions"):
            print("  权限（本地 / 仓库）：" + row["permissions"])
    for action, path in preview["changes"]:
        print("{}  {}".format(action, path))
    for message, path in preview.get("notices", []):
        print("{}  {}".format(message, path))
    print("其他文件不下载、不覆盖、不删除；只提示是否存在、类型和大小差异。")
    blocker = preview["blocker"]
    if blocker:
        print("不能应用：" + blocker)
