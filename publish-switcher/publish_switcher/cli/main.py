"""命令行入口。

解析 sync / config / assets / demo / gui 等子命令；除 gui 外不导入 Tkinter。
"""
import argparse
import sys
from pathlib import Path

from publish_switcher.common.paths import INSTALL_ROOT
from publish_switcher.common.errors import SyncError
from publish_switcher.common.settings import read_settings, save_settings
from publish_switcher.common.diagnostics import default_log_path, settings_path, setup_logging
from publish_switcher.cli.common import get_engine, permission_policy, profiles, selected, show_preview, stdout_colors
from publish_switcher.sync.diagnostics import diagnose_file, format_report, comparison_self_test
from publish_switcher.configuration.versions import CONFIG_NAMES, format_comparison
from publish_switcher.sync.assets import AssetsEngine, format_preview as assets_report
from publish_switcher.sync.formats import normalize_extensions, inventory, describe, label
from publish_switcher.version import VERSION


def permission_options(command):
    group = command.add_mutually_exclusive_group()
    group.add_argument("--sync-permissions", dest="sync_permissions", action="store_true", help="严格更新按仓库同步权限；增量仍跳过已有文件")
    group.add_argument("--keep-permissions", dest="sync_permissions", action="store_false", help="保留本地已有文件权限，新文件使用仓库权限（默认）")
    command.set_defaults(sync_permissions=None)


def parser():
    p = argparse.ArgumentParser(description="swicher：文件更新、配置切换与 IoT Demo。")
    # Keep the legacy machine-readable probe for already-installed update helpers.
    p.add_argument("--version", action="version", version="Publish Switcher " + VERSION)
    p.add_argument("--target", help="publish 目录，默认读取已保存设置")
    p.add_argument("--repo", help="首选 HTTPS 项目地址：Gitee/GitHub/GitLab/极狐；显式指定时不使用已保存的候补")
    p.add_argument("--fallback-repo", action="append", default=[], help="候补仓库，可重复指定，按顺序查询")
    p.add_argument("--branch", help="分支，留空使用仓库默认分支")
    p.add_argument("--log-file", help="日志文件，默认 ~/.config/publish-switcher/logs/switcher.log")
    p.add_argument("--local-catalog", help="本地资源仓库的 catalog.json")
    p.add_argument("--offline", action="store_true", help="只使用已缓存的方案")
    p.add_argument("--extensions", help="同步格式，逗号分隔；默认读取设置或 .py,.json,.ttf；无扩展名用 <none>")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="列出可用方案和 ID")
    formats = sub.add_parser("formats", help="读取远端方案格式、数量和大小，可保存格式选择")
    formats.add_argument("--profile", required=True)
    formats.add_argument("--version")
    formats.add_argument("--save", action="store_true", help="保存格式选择和本次识别的格式列表")
    menu = sub.add_parser("cli", help="打开 SSH 交互数字菜单，无需 Tkinter")
    permission_options(menu)
    assets = sub.add_parser("assets", help="比较 Assets 内容并增量下载缺失资源")
    asset_commands = assets.add_subparsers(dest="assets_command", required=True)
    for name in ("check", "download"):
        command = asset_commands.add_parser(name, help="只比较资源，不下载" if name == "check" else "只下载缺失资源，已有文件保留")
        command.add_argument("--profile", required=True, help="方案 ID，例如 rk 或 jetson")
        command.add_argument("--version", help="固定方案版本")
        if name == "download":
            command.add_argument("--yes", action="store_true", help="确认只新增缺失的 Assets 文件")
    demo = sub.add_parser("demo", help="选择运行当前配置中的 IoT Demo，实时显示错误和日志")
    demo.add_argument("--task", help="直接运行 TrainTaskId；留空进入任务菜单")
    demo_modes = demo.add_mutually_exclusive_group()
    demo_modes.add_argument("--list", action="store_true", help="只列出当前 IoT 任务")
    demo_modes.add_argument("--check", action="store_true", help="只检查路径和解释器，不运行")
    demo.add_argument("--python", help="临时覆盖配置中的 PythonExePath")
    demo.add_argument("--demo-log-dir", help="Demo 日志目录，必须在 publish 外")
    sub.add_parser("self-test", help="在独立临时目录运行比较样例，无需设置 publish 或联网")
    diagnose = sub.add_parser("diagnose", help="只读诊断一个文件的内容、换行和权限差异")
    diagnose.add_argument("--profile", required=True, help="方案 ID，例如 rk 或 jetson")
    diagnose.add_argument("--version", help="指定方案版本")
    diagnose.add_argument("--path", required=True, help="publish 内相对文件路径，例如 IoT/01-LED_RGB/bs.py")
    permission_options(diagnose)
    for name, help_text in (("check", "只检查并显示变更和其他资源提示"), ("sync", "按勾选格式下载并同步文件")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--profile", required=True, help="方案 ID，例如 jetson 或 rk")
        command.add_argument("--version", help="指定版本；多个缓存版本时必须提供")
        command.add_argument("--mode", choices=("incremental", "strict"), default="incremental",
                             help="incremental 只补齐缺失（默认）；strict 替换差异并删除所选格式的多余文件")
        permission_options(command)
        if name == "sync":
            command.add_argument("--yes", action="store_true", help="已检查并确认所选更新模式")
    sub.add_parser("competition", help="旧命令已停用，请改用 config apply --version 版本名称")
    config = sub.add_parser("config", help="列出、检查、对比或应用 config 子文件夹内的整套配置")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_commands.add_parser("list", help="列出本机 config 版本和可用状态")
    for name in ("check", "apply", "diff"):
        command = config_commands.add_parser(name, help={"check": "检查版本映射", "apply": "备份并替换三个生效 JSON", "diff": "只读对比当前生效 JSON 与版本模板"}[name])
        command.add_argument("--version", required=True, help="config 直接子文件夹名称")
        if name == "apply":
            command.add_argument("--yes", action="store_true", help="确认一次替换三个配置")
        if name == "diff":
            command.add_argument("--file", choices=CONFIG_NAMES, help="对比一个标准配置名；不填则对比三个 JSON")
            command.add_argument("--raw", action="store_true", help="显示原始文本差异；默认格式化 JSON，不能解析时自动显示原始文本")
    restore = sub.add_parser("restore", help="按上次同步记录的格式范围恢复备份")
    restore.add_argument("--yes", action="store_true", help="确认按上次记录的格式恢复文件")
    logs = sub.add_parser("logs", help="查看最近的运行日志，实时查看可用 tail -f")
    logs.add_argument("--tail", type=int, default=80, help="显示最后多少行，默认80")
    gui = sub.add_parser("gui", help="打开用户界面（需要图形桌面和 Tkinter）")
    gui.add_argument("--engineer", action="store_true", help="直接打开工程师界面")
    gui.add_argument("--resume-startup-update", action="store_true", help=argparse.SUPPRESS)
    for command in (formats, menu, diagnose, sub.choices["check"], sub.choices["sync"]):
        command.add_argument("--extensions", default=argparse.SUPPRESS,
                             help="本次同步格式，逗号分隔，例如 .py,.json,.ttf")
    return p


def settings():
    try:
        return read_settings(settings_path())
    except ValueError as exc:
        raise SyncError("设置文件不是有效 JSON，请检查 " + str(settings_path())) from exc


def confirm(args, message):
    if args.yes:
        return
    if not sys.stdin.isatty():
        raise SyncError("非交互执行需要加 --yes；请先使用 check 核对变更。")
    if input(message + "\n输入 yes 确认：").strip().lower() != "yes":
        raise SyncError("已取消，未应用配置。")


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "logs":
        path = Path(args.log_file).expanduser() if args.log_file else default_log_path()
        if args.tail < 1:
            print("--tail 必须大于 0。", file=sys.stderr)
            return 2
        try:
            print("日志：" + str(path))
            if not path.exists():
                print("尚无日志。")
            else:
                print("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-args.tail:]))
            return 0
        except OSError as exc:
            print("日志读取失败：" + str(exc), file=sys.stderr)
            return 1
    try:
        logger, logfile = setup_logging(args.log_file, console=True)
    except OSError as exc:
        print("无法创建日志：{}；可使用 --log-file 指定可写位置。".format(exc), file=sys.stderr)
        return 1
    logger.info("启动 command=%s target=%s log=%s", args.command, args.target or "已保存设置", logfile)
    try:
        if args.command == "gui":
            import tkinter as tk
            from publish_switcher.updates import bootstrap as tool_update
            from publish_switcher.gui.widgets.icons import WM_CLASS
            install = INSTALL_ROOT
            with tool_update.instance_lock(install):
                if args.engineer:
                    tool_update.recover_update(install)
                from publish_switcher.gui.app import Application
                root = tk.Tk(className=WM_CLASS)
                root.report_callback_exception = lambda typ, value, tb: logger.error("界面回调异常", exc_info=(typ, value, tb))
                Application(root, engineer=args.engineer, updates=True, auto_update=not args.engineer,
                            resume_update=args.resume_startup_update)
                root.mainloop()
            return 0
        if args.command == "competition":
            raise SyncError("旧 competition 命令已停用。请运行 config list，再用 config apply --version 版本名称。")
        if args.command == "self-test":
            report = comparison_self_test()
            print(report)
            logger.info("比较自测\n%s", report)
            return 0
        config = settings()
        if args.command == "cli":
            from publish_switcher.cli.menu import run_menu
            return run_menu(args, config, logger, logfile)
        if args.command == "demo":
            from publish_switcher.demo.runner import main as demo_main
            target = args.target or config.get("target")
            if not target:
                raise SyncError("请先设置 publish 目录，或使用 --target /实际路径/publish demo。")
            options = ["--publish", str(target), "--log-dir", args.demo_log_dir or str(logfile.parent / "iot-demo")]
            if args.task:
                options += ["--task", args.task]
            if args.python:
                options += ["--python", args.python]
            if args.list:
                options += ["--list"]
            if args.check:
                options += ["--check"]
            return demo_main(options)
        if args.command == "list":
            for item in profiles(args, config):
                p = item.get("manifest") or item["profile"]
                print("{}\t{}\t{}".format(p["id"], p.get("name", p["id"]), p["version"]))
            return 0
        readonly = args.command == "diagnose" or (args.command == "config" and args.config_command == "diff")
        engine = get_engine(args, config, recover=not readonly)
        logger.info("目标目录：%s", engine.target)
        if args.command == "formats":
            item = selected(args, profiles(args, config, engine))
            with engine.lock():
                engine.save_profile(item["manifest"], item["source"])
            rows = inventory(item["manifest"])
            for row in rows:
                print("{} {}：{} 个；{:.2f} MiB{}".format("[x]" if row["extension"] in engine.extensions else "[ ]",
                      label(row["extension"]), row["count"], row["bytes"] / 1024**2,
                      "；含仅元数据文件，需重新发布" if row["unavailable"] else ""))
            if args.save:
                save_settings(settings_path(), {
                    "file_extensions": list(engine.extensions),
                    "format_inventory": {"id": item["manifest"]["id"], "version": item["manifest"]["version"], "formats": rows},
                })
                print("格式选择和识别结果已保存。")
            return 0
        if args.command == "assets":
            item = selected(args, profiles(args, config, engine))
            manifest = item["manifest"]
            assets = AssetsEngine(engine.target)
            with assets.lock():
                assets.recover()
                assets.save_profile(manifest, item["source"])
                preview = assets.preview_assets(manifest, log=logger.info)
            print(assets_report(manifest, preview))
            if preview["blocker"]:
                raise SyncError(preview["blocker"])
            if args.assets_command == "check":
                return 0
            if not preview["changes"]:
                print("Assets 没有缺失资源，无需下载。")
                return 0
            confirm(args, "只新增缺失的 Assets 资源；已有文件（含空文件和不同内容）保留，多余资源不删除。请先退出主程序和相关任务。")
            result = assets.download_missing(manifest, item["source"], expected_actual=preview["actual"], log=logger.info, offline=args.offline)
            logger.info("Assets 增量下载完成：%s", result)
            print("Assets 下载完成，已有资源保持原样。备份：" + str(assets.state / "backups" / result["backup"]))
            return 0
        if args.command == "diagnose":
            item = selected(args, profiles(args, config, engine))
            report = diagnose_file(engine, item["manifest"], item["source"], args.path, offline=args.offline,
                                   sync_permissions=permission_policy(args, config))
            print(format_report(report, color=stdout_colors()))
            logger.info("比较诊断\n%s", format_report(report, include_diff=False))
            return 0
        if args.command == "config":
            if args.config_command == "diff":
                for name in ([args.file] if args.file else CONFIG_NAMES):
                    report = engine.compare_config_file(args.version, name)
                    print(format_comparison(report, color=stdout_colors(), raw=args.raw))
                    logger.info("配置 JSON 对比\n%s", format_comparison(report, include_diff=False))
                return 0
            if args.config_command == "list":
                summary = engine.config_summary()
                for item in sorted(summary["versions"], key=lambda item: item["version"]):
                    print("{}\t{}\t{}".format(item["version"], "可用" if item["valid"] else "不可用", "；".join(item["issues"])))
                print(summary["current_label"])
                return 0
            preview = engine.preview_config_version(args.version)
            print("配置版本：" + preview["version"])
            for row in preview["mappings"]:
                print("{} → {}  {}".format(row["source"], row["active"], row.get("action", row["status"])))
            if not preview["valid"]:
                raise SyncError("版本不可用：\n" + "\n".join(preview["issues"]))
            if args.config_command == "check":
                return 0
            confirm(args, "将整套备份并替换三个根目录 JSON。请先退出主程序。")
            result = engine.activate_config_version(args.version, expected_snapshot=preview["snapshot"], log=logger.info)
            logger.info("配置版本已应用：%s；备份：%s", result["version"], result["backup"])
        elif args.command == "restore":
            confirm(args, "按上次同步记录的格式恢复备份，其他格式保留。请先退出相关任务。")
            result = engine.restore(log=logger.info)
            logger.info("恢复完成，备份：%s", result["backup"])
        else:
            item = selected(args, profiles(args, config, engine))
            manifest = item["manifest"]
            sync_permissions = permission_policy(args, config)
            with engine.lock():
                engine.save_profile(manifest, item["source"])
                preview = engine.preview(manifest, mode=args.mode, sync_permissions=sync_permissions)
            show_preview(manifest, preview)
            logger.info("方案 id=%s version=%s changes=%s download_bytes=%s", manifest["id"], manifest["version"], len(preview["changes"]), preview["download_bytes"])
            if preview["blocker"]:
                raise SyncError(preview["blocker"])
            if args.command == "sync":
                detail = "增量更新：只补齐缺失，已有文件跳过，本地多余文件保留。" if args.mode == "incremental" else "严格更新：替换、删除所选格式内的差异和多余文件（勾选 JSON 时包括生效配置和结果）。"
                detail += "\n同步格式：" + describe(engine.extensions)
                detail += "\n权限策略：" + ("严格同步仓库权限；增量不改已有文件。" if sync_permissions else "保留已有文件权限，新文件使用仓库权限。")
                confirm(args, detail + "请先退出相关任务。")
                result = engine.apply(manifest, item["source"], log=logger.info, mode=args.mode, expected_actual=preview["actual"],
                                      sync_permissions=sync_permissions)
                logger.info("同步完成，备份：%s", result["backup"])
        if args.command != "check":
            print("无需更新，未修改 publish。" if result.get("unchanged") else "操作完成，请重新启动主程序。")
        return 0
    except KeyboardInterrupt:
        logger.warning("用户中断操作；请查看当前配置及恢复记录。", exc_info=True)
        return 130
    except Exception:
        logger.exception("操作失败；完整错误日志：%s", logfile)
        return 1


if __name__ == "__main__":
    sys.exit(main())
