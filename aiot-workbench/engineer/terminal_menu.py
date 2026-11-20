"""Interactive SSH menu, using the same checked transactions as the desktop UI."""
import copy
import sys
from pathlib import Path

import switcher as cli
from compat import is_relative_to
from core import Engine, SyncError, atomic_json, read_json
from diagnostics import settings_path
from file_compare import comparison_self_test, diagnose_file, format_report
from config_versions import CONFIG_NAMES, format_comparison
from assets_sync import AssetsEngine, format_preview as assets_report
from repository import DEFAULT_REPOSITORY, REPOSITORY_DEFAULT_VERSION, repository_from_settings
from file_formats import normalize_extensions, inventory, describe, label


class TerminalMenu:
    def __init__(self, args, config, logger, logfile):
        self.args, self.config = copy.copy(args), dict(config)
        self.logger, self.logfile = logger, logfile
        self.args.target = args.target or config.get("target", "")
        self.args.repo = args.repo or repository_from_settings(config)
        self.args.branch = args.branch if args.branch is not None else config.get("branch", "")
        self.sync_permissions = cli.permission_policy(args, config)
        self.extensions = normalize_extensions(getattr(args, "extensions", None) if getattr(args, "extensions", None) is not None else config.get("file_extensions"))
        self.item = None
        self.checked = None

    def invalidate(self, source=False):
        self.checked = None
        if source:
            self.item = None

    @staticmethod
    def choose(prompt, count):
        while True:
            value = input(prompt).strip()
            if value in ("", "0"):
                return None
            if value.isdecimal() and 1 <= int(value) <= count:
                return int(value) - 1
            print("请输入列表中的数字，输入 0 返回。")

    @staticmethod
    def confirmed(message):
        print(message)
        accepted = input("输入 yes 确认，其他输入取消：").strip().lower() == "yes"
        if not accepted:
            print("已取消，未应用。")
        return accepted

    def engine(self, recover=True):
        if not self.args.target:
            value = input("请输入设备上的实际 publish 目录（留空返回）：").strip()
            if not value:
                raise SyncError("尚未选择 publish 目录。")
            self.args.target = str(Path(value).expanduser().absolute())
        target = Path(self.args.target).expanduser()
        if not target.is_dir():
            # A directory swap may have moved publish to its backup before interruption.
            state = target.parent / (".publish-switcher-" + target.name)
            pending = (state / "transaction.json").is_file() or (state / "config-transaction.json").is_file()
            if not recover or target.exists() or not pending:
                raise SyncError("publish 目录不存在：{}。请进入“设置”修改路径，避免把全部文件误判为新增。".format(target))
        if is_relative_to(settings_path().resolve(), target.resolve()) or is_relative_to(self.logfile.resolve(), target.resolve()):
            raise SyncError("设置和日志必须放在 publish 外。")
        engine = Engine(target, extensions=self.extensions)
        if recover:
            engine.startup_recover()
        if not engine.target.is_dir():
            raise SyncError("恢复后 publish 目录仍不存在，请检查事务记录和备份：" + str(engine.state))
        return engine

    def select_profile(self, recover=True):
        engine = self.engine(recover=recover) if self.args.offline else None
        print("正在读取方案列表……")
        items = cli.profiles(self.args, self.config, engine)
        if not items:
            print("没有可用方案。离线模式需要先缓存方案。")
            return False
        for index, item in enumerate(items, 1):
            profile = item.get("manifest") or item["profile"]
            print("{}. {} [{}] / {}".format(index, profile.get("name", profile["id"]), profile["id"], profile["version"]))
        choice = self.choose("选择方案编号（0 返回）：", len(items))
        if choice is None:
            return False
        profile = items[choice].get("manifest") or items[choice]["profile"]
        self.args.profile, self.args.version = profile["id"], profile["version"]
        self.item = cli.selected(self.args, [items[choice]])
        self.invalidate()
        print("已选择：{} / {}。尚未更新文件。".format(profile.get("name", profile["id"]), profile["version"]))
        return True

    def check(self):
        engine = self.engine()
        if self.item is None and not self.select_profile():
            return False
        manifest = self.item["manifest"]
        with engine.lock():
            engine.save_profile(manifest, self.item["source"])
            strict = engine.preview(manifest, mode="strict", sync_permissions=self.sync_permissions)
            incremental = engine.preview(manifest, mode="incremental", actual=strict["actual"], sync_permissions=self.sync_permissions)
        self.checked = {"target": str(engine.target), "manifest": manifest, "item": self.item,
                        "plans": {"strict": strict, "incremental": incremental}, "actual": strict["actual"],
                        "sync_permissions": self.sync_permissions}
        print("\n实际本地目标：" + str(engine.target))
        cli.show_preview(manifest, strict)
        print("增量：{} 项变更，下载 {:.2f} MiB；严格：{} 项变更，下载 {:.2f} MiB。".format(
            len(incremental["changes"]), incremental["download_bytes"] / 1024**2,
            len(strict["changes"]), strict["download_bytes"] / 1024**2))
        print("检查完成，尚未修改 publish。")
        self.logger.info("菜单检查 target=%s profile=%s version=%s permissions=%s", engine.target, manifest["id"], manifest["version"], self.sync_permissions)
        return True

    def update(self):
        if self.checked is None and not self.check():
            return
        checked = self.checked
        print("1. 增量：只新增缺失文件，已有文件跳过，本地多余文件保留。")
        print("2. 严格：替换、删除所选格式内的差异和多余文件。")
        choice = self.choose("选择更新方式（0 返回）：", 2)
        if choice is None:
            return
        mode = ("incremental", "strict")[choice]
        preview = checked["plans"][mode]
        cli.show_preview(checked["manifest"], preview)
        if preview["blocker"]:
            raise SyncError(preview["blocker"])
        if not preview["changes"]:
            print("无需更新，未修改 publish。")
            return
        permissions = "严格同步仓库权限；增量仍跳过已有文件" if checked["sync_permissions"] else "保留本地已有文件权限；新文件用仓库权限"
        detail = "增量只补齐缺失文件。" if mode == "incremental" else "严格更新会覆盖差异并删除所选格式的多余文件；勾选 JSON 时包括生效配置。"
        detail += "\n同步格式：" + describe(self.extensions)
        if not self.confirmed("目标：{}\n{}\n权限：{}\n请先退出主程序和相关 Python 任务。".format(checked["target"], detail, permissions)):
            return
        self.invalidate()
        engine = self.engine()
        result = engine.apply(checked["manifest"], checked["item"]["source"], mode=mode, sync_permissions=checked["sync_permissions"],
                              expected_actual=checked["actual"], log=self.logger.info)
        print("更新完成，请重新启动主程序。" if not result.get("unchanged") else "无需更新，未修改 publish。")
        if result.get("backup"):
            print("备份：" + str(engine.state / "backups" / result["backup"]))

    def configuration(self):
        engine = self.engine()
        versions = engine.list_config_versions()
        print(engine.task_config_status())
        if not versions:
            print("publish/config 下没有版本文件夹。")
            return
        for index, item in enumerate(versions, 1):
            print("{}. {} [{}] {}".format(index, item["version"], "可用" if item["valid"] else "不可用", "；".join(item["issues"])))
        choice = self.choose("选择配置版本查看映射（0 返回）：", len(versions))
        if choice is None:
            return
        preview = engine.preview_config_version(versions[choice]["version"])
        for row in preview["mappings"]:
            print("{} → {}：{}".format(row["source"], row["active"], row.get("action", row["status"])))
        if not preview["valid"]:
            raise SyncError("版本不可用：" + "；".join(preview["issues"]))
        if not self.confirmed("目标：{}\n将备份并替换三个生效 JSON 为“{}”。源模板保留。请先退出主程序。".format(engine.target, preview["version"])):
            return
        self.invalidate()
        result = engine.activate_config_version(preview["version"], expected_snapshot=preview["snapshot"], log=self.logger.info)
        print("配置已切换为 {}。备份：{}。请重新启动主程序。".format(result["version"], result["backup"]))

    def restore(self):
        engine = self.engine()
        if not engine.current.exists():
            raise SyncError("没有上次更新的备份记录。")
        record = read_json(engine.current)
        if not self.confirmed("目标：{}\n按上次记录的格式范围恢复内容和权限，备份标识：{}。\n其他格式保留，请先退出主程序。".format(engine.target, record.get("backup", "未知"))):
            return
        self.invalidate()
        result = engine.restore(log=self.logger.info)
        print("恢复完成，请重新启动主程序。当前操作备份：" + str(result.get("backup")))

    def configuration_diff(self):
        engine = self.engine(recover=False)
        versions = engine.list_config_versions()
        if not versions:
            print("publish/config 下没有版本文件夹。")
            return
        for index, item in enumerate(versions, 1):
            print("{}. {} [{}]".format(index, item["version"], "可用" if item["valid"] else "配置不完整"))
        choice = self.choose("选择对比的配置版本（0 返回）：", len(versions))
        if choice is None:
            return
        for index, name in enumerate(CONFIG_NAMES, 1):
            print("{}. {}".format(index, name))
        selected = self.choose("选择 JSON 文件（0 返回）：", len(CONFIG_NAMES))
        if selected is None:
            return
        report = engine.compare_config_file(versions[choice]["version"], CONFIG_NAMES[selected])
        print(format_comparison(report, color=cli.stdout_colors()))
        self.logger.info("菜单配置 JSON 对比\n%s", format_comparison(report, include_diff=False))

    def diagnose(self):
        # Inspection does not recover or otherwise modify an interrupted publish.
        engine = self.engine(recover=False)
        if self.item is None and not self.select_profile(recover=False):
            return
        path = input("输入相对文件路径（例如 IoT/01-LED_RGB/bs.py，留空返回）：").strip()
        if not path:
            return
        report = diagnose_file(engine, self.item["manifest"], self.item["source"], path,
                               offline=self.args.offline, sync_permissions=self.sync_permissions)
        print(format_report(report, color=cli.stdout_colors()))
        self.logger.info("菜单文件诊断\n%s", format_report(report, include_diff=False))

    def save_settings(self):
        engine = self.engine(recover=False)
        data = dict(self.config, target=str(engine.target), publish_dir=str(engine.target), repo=self.args.repo, branch=self.args.branch,
                    sync_permissions=self.sync_permissions, repository_default_version=REPOSITORY_DEFAULT_VERSION,
                    file_extensions=list(self.extensions))
        atomic_json(settings_path(), data)
        self.config = data
        print("已保存：" + str(settings_path()))

    def settings(self):
        while True:
            print("\n设置：1.publish 目录  2.仓库地址  3.分支  4.权限策略  5.来源模式  6.保存设置  0.返回")
            choice = self.choose("选择：", 6)
            if choice is None:
                return
            if choice == 0:
                value = input("实际 publish 目录（留空保持）：").strip()
                if value:
                    path = Path(value).expanduser()
                    if not path.is_dir():
                        raise SyncError("目录不存在，请确认路径：" + value)
                    self.args.target = str(path.absolute())
                    self.invalidate(source=True)
            elif choice == 1:
                self.args.repo = input("Gitee/GitHub 地址（留空用默认 Gitee）：").strip() or DEFAULT_REPOSITORY
                self.invalidate(source=True)
            elif choice == 2:
                self.args.branch = input("分支（留空使用仓库默认分支）：").strip()
                self.invalidate(source=True)
            elif choice == 3:
                print("1. 保留本地已有文件权限（默认）；新文件使用仓库权限。\n2. 严格更新同步仓库权限；增量仍跳过已有文件。")
                policy = self.choose("选择权限策略（0 返回）：", 2)
                if policy is not None:
                    self.sync_permissions = policy == 1
                    self.invalidate()
            elif choice == 4:
                print("1. 联网仓库\n2. 离线缓存\n3. 本地 catalog.json")
                mode = self.choose("选择来源（0 返回）：", 3)
                if mode is not None:
                    catalog = input("catalog.json 路径：").strip() if mode == 2 else None
                    if mode == 2 and (not catalog or not Path(catalog).expanduser().is_file()):
                        raise SyncError("本地 catalog.json 不存在。")
                    self.args.offline, self.args.local_catalog = mode == 1, catalog
                    self.invalidate(source=True)
            else:
                self.save_settings()
            print("当前目录：{}；权限：{}。".format(self.args.target or "未设置", "严格同步仓库" if self.sync_permissions else "保留本地"))

    def logs(self):
        print("日志文件：" + str(self.logfile))
        if self.logfile.exists():
            print("\n".join(self.logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
        else:
            print("尚无日志。")

    def formats(self):
        if self.item is None and not self.select_profile():
            return
        manifest = self.item["manifest"]
        rows = inventory(manifest)
        self.config["format_inventory"] = {"id": manifest["id"], "version": manifest["version"], "formats": rows}
        options = sorted({row["extension"] for row in rows} | set(self.extensions))
        while True:
            for index, ext in enumerate(options, 1):
                row = next((r for r in rows if r["extension"] == ext), {"count": 0, "bytes": 0})
                print("{}. [{}] {} · {} 个 · {:.2f} MiB".format(index, "x" if ext in self.extensions else " ",
                      label(ext), row["count"], row["bytes"] / 1024**2))
            choice = self.choose("输入编号切换勾选，0 保存并返回：", len(options))
            if choice is None:
                self.save_settings()
                return
            ext = options[choice]
            selected = set(self.extensions)
            selected.remove(ext) if ext in selected else selected.add(ext)
            self.extensions = normalize_extensions(selected)
            self.invalidate()

    def iot_demo(self):
        from iot_runner import main as demo_main
        engine = self.engine()
        self.invalidate()
        demo_main(["--publish", str(engine.target), "--log-dir", str(self.logfile.parent / "iot-demo")])

    def assets(self):
        target = self.engine().target
        if self.item is None and not self.select_profile():
            return
        item = self.item
        engine = AssetsEngine(target)
        manifest = item["manifest"]
        with engine.lock():
            engine.recover()
            engine.save_profile(manifest, item["source"])
            preview = engine.preview_assets(manifest, log=self.logger.info)
        print(assets_report(manifest, preview))
        if preview["blocker"]:
            raise SyncError(preview["blocker"])
        if not preview["changes"]:
            print("Assets 没有缺失文件，无需下载。")
            return
        if not self.confirmed("目标：{}\n将补齐 {} 个 Assets 文件；已有同名文件（含内容不同和空文件）保留，多余文件不删除。\n请先退出主程序和相关任务。".format(target, len(preview["changes"]))):
            return
        self.invalidate()
        result = engine.download_missing(manifest, item["source"], expected_actual=preview["actual"], log=self.logger.info, offline=self.args.offline)
        print("Assets 下载完成。备份：" + str(engine.state / "backups" / result["backup"]))

    def run(self):
        actions = (self.settings, self.select_profile, self.check, self.update, self.configuration,
                   self.restore, self.diagnose, self.self_test, self.logs, self.iot_demo, self.configuration_diff, self.assets, self.formats)
        while True:
            print("\npublish-switcher 终端菜单")
            print("publish：{}\n仓库：{}\n权限：{}".format(self.args.target or "未设置", self.args.repo,
                  "严格更新同步仓库权限" if self.sync_permissions else "保留本地已有文件权限"))
            print("来源：" + ("离线缓存" if self.args.offline else "本地 " + self.args.local_catalog if self.args.local_catalog else "联网仓库"))
            if self.item:
                print("当前所选方案：{} / {}".format(self.item["manifest"].get("name", self.item["manifest"]["id"]), self.item["manifest"]["version"]))
            print("1. 设置目录、仓库和权限\n2. 刷新并选择资源方案\n3. 检查文件差异\n4. 应用文件更新（先检查再确认）\n5. 查看／切换配置版本\n6. 恢复上次更新\n7. 诊断文件差异\n8. 运行比较自测\n9. 查看最近日志\n10. 运行 IoT Demo\n11. 查看配置 JSON 差异\n12. Assets 资源对比／增量下载\n13. 读取／勾选同步文件格式\n0. 退出")
            try:
                choice = self.choose("请输入功能编号：", len(actions))
                if choice is None:
                    print("已退出。")
                    return 0
                try:
                    actions[choice]()
                except KeyboardInterrupt:
                    self.invalidate()
                    self.logger.warning("用户中断菜单操作", exc_info=True)
                    print("当前操作已中断；返回菜单。未完成事务将在下次操作前检查。")
                except EOFError:
                    raise
                except Exception as exc:
                    self.invalidate()
                    self.logger.exception("菜单操作失败")
                    print("操作未完成：{}\n完整日志：{}".format(exc, self.logfile))
            except (EOFError, KeyboardInterrupt):
                print("\n已退出终端菜单。")
                return 0

    def self_test(self):
        report = comparison_self_test()
        print(report)
        self.logger.info("菜单比较自测\n%s", report)


def run_menu(args, config, logger, logfile):
    if not sys.stdin.isatty():
        raise SyncError("cli 数字菜单需要交互终端。请在 SSH 中运行，或使用 check/sync 等非交互子命令。")
    return TerminalMenu(args, config, logger, logfile).run()
