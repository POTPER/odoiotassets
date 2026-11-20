# AIoT 工作台（aiot-workbench）

独立整合原 AIoT Launcher 与 Publish Switcher，面向 Ubuntu ARM64 桌面和 Python 3.8.10。同步、配置版本管理、内容比较、下载校验和事务恢复统一使用 `shared/` 的一套实现。用户只接触启动、停止、成果与程序更新；按 **Ctrl+Shift+F12** 打开工程师面板。

## 首次安装

将整个 `aiot-workbench` 文件夹放到 publish 外，例如 `~/aiot-workbench`。使用桌面登录账户运行：

```bash
cd ~/aiot-workbench
bash install.sh
python3 workbench.py gui
```

默认先查找 `/home/ubuntu/linux-arm64/publish`，不存在时查找 `/home/ubuntu/linux_arm64/publish`。两者都不存在时保留第一个作为默认值，并报告未找到目录。安装时可显式指定：

```bash
bash install.sh /home/ztl/linux-arm64/publish
```

已保存的自定义路径优先，不因为其他目录出现而改换。安装创建“AIoT 工作台”桌面与应用菜单入口。桌面提示不可信时右键选择“允许启动”。不要将整个安装脚本用 sudo 运行；缺少系统依赖时脚本会单独请求 sudo。安装本身不启动 AIoT。

离线安装：

```bash
bash install.sh --offline /home/ubuntu/linux-arm64/publish
```

`debs/` 随包包含 Ubuntu 20.04 ARM64/all 的 123 个官方依赖包，包括 Python、Tkinter、Pillow/ImageTk 和 PolicyKit；`PLATFORM`、`SHA256SUMS`、`PACKAGES.tsv` 记录平台与校验信息。安装器仅使用临时本地 APT 软件源，不联网，也不移除系统包。其他 Ubuntu 版本或架构需提供匹配的依赖目录：`--deb-dir /路径`。

## 用户操作

- 启动、停止、关闭时的进程确认、外部 AIoT 检测、单实例唤起和成果工作流沿用原 Launcher。
- 主页面沿用原布局、高清背景与主题，统一换用新的设备面板图标。
- **程序更新**是唯一的用户更新入口：一次操作同时检查/更新工作台自身，并在后台严格更新 publish 的所选格式。不弹出工程师的文件对比或方案设置界面；只显示进度和结果。
- 即使工作台已是最新版，点击程序更新仍会检查和更新 publish。
- 更新完成后，有新版工作台则自动重启工作台；只有 publish 变化则无需重启工作台。更新不会自动启动 AIoT。
- 更新前必须停止 AIoT、Demo 等相关任务，并关闭工程师面板。更新过程中阻止再次启动、切换配置和替换程序目录；停止功能仍保留。

启动时检查工作台版本；发现新版或检查失败时，完成更新/验证后才允许启动。初次离线部署可以在程序更新窗口导入与 ZIP 配套的 `workbench-update.json`，通过同版本安装包校验解锁已有部署。实际离线升级到新版本还需已完整缓存对应 publish 方案。

## 工程师面板

按 Ctrl+Shift+F12 打开维护窗口。主页在维护窗口关闭后恢复使用，修改 publish 路径后工作台自动重新加载。设置、日志、缓存和备份都在 publish 外。

工程师设置包括资源仓库、分支、方案目录、同步格式和权限策略；“工作台主页更新设置”单独设置：

- 主页更新方案 ID：默认 `rk`，可改 `jetson` 或后续增加的方案 ID。
- 工作台仓库内目录：默认 `aiot-workbench`。与 publish 共用连接设置中的仓库地址与分支；默认仓库为 `https://gitee.com/potper/odoiotassets`，不再单独配置程序更新 URL。

**严格更新范围仍由已勾选的文件格式决定**。默认 `.py`、`.json`、`.ttf`；可勾选 `.rknn` 等格式。严格更新替换差异文件、删除该范围内的本地多余文件，包括根目录生效 JSON 和所选格式的运行结果。未选格式保留；默认保留已有文件权限，新文件使用仓库权限。Assets 独立比较/增量下载、文本差异诊断、权限预设和 Demo 队列仍在工程师面板。

配置版本来自 `publish/config` 的直接子文件夹；三个标准前缀 JSON 整套切换、冲突检查、内容对比、事务备份与异常恢复保留。用户设置中的配置切换保留原 Launcher 清理任务生成文件的事务行为。`publish/config/versions.json` 控制用户可见目录，例如：

```json
{
  "default_user_visible": true,
  "rules": [{"prefix": "F", "user_visible": false}],
  "versions": {"教学版本1": {"display_name": "基础训练", "order": 1}}
}
```

工程师可查看全部目录。该规则只控制用户界面显示，不作为文件访问权限或身份认证。

## SSH 与日志

```bash
bash install.sh --cli
python3 workbench.py cli
python3 workbench.py cli --help
python3 workbench.py cli --target /home/ubuntu/linux-arm64/publish config list
python3 workbench.py doctor
```

CLI 无需 Tkinter。`~/.config/aiot-workbench/settings.json` 保存部署设置；`logs/` 内有 `workbench.log`、`engineer.log`、`content-update.log`、`engineer-startup.log` 和桌面启动日志。资源缓存与事务备份继续使用 publish 同级 `.publish-switcher-<目录名>`，以保持兼容。

## 一个仓库，两个更新目录

默认仓库的结构为：

```text
odoiotassets/
  aiot-workbench/   工作台完整源文件，含 version.py、bootstrap.py、shared、launcher、engineer
  publish_RK/       RK 的 publish 资源
  publish-switcher/ 原独立工具，本工作台不从这里更新自身
```

点击程序更新后，先读取同一次固定提交的目录树：`aiot-workbench` 用于更新工作台，`publish_RK` 等方案用于严格更新设备的 publish。两部分复用同一个同步引擎、文件哈希比较和下载校验。工作台的源文件与资源都直接从该仓库读取，**在线更新不需要 ZIP，也不需要额外的发布 JSON**。

发布时上传完整的 `aiot-workbench` 源码目录并提交即可；建议同时递增 `aiot-workbench/version.py` 的 VERSION。相同版本号下的代码差异也能检测和修复。不会降级较新的本机程序。目录树被截断、文件不完整、校验失败时阻止替换。

本次上传请同时提交旧 `launcher/core.py`、`engineer/core.py` 等私有副本的删除，保持仓库整洁。即使远端遗留这些旧副本，更新器也会忽略它们，以 shared 为准，并在设备更新时清理对应的本地旧代码。

工作台在线同步其运行所需的全部格式，包括 Python、脚本、图标、背景等。`release/`、`debs/`、测试和缓存不从仓库下载；本机离线依赖保留。已相同的文件复用，只下载变化的文件。publish 的更新范围仍由工程师勾选格式决定。

先准备并校验新版工作台目录，再严格更新 publish，最后退出工作台、备份并替换自身。publish 失败会撤销已准备的工作台更新；如果工作台切换失败，则恢复旧程序。两个目录各有恢复记录，不构成跨目录原子事务；publish 已完成而工作台切换失败时，重试即可。设置、日志、缓存和备份不存放在被更新目录内。

## 安装包和旧版升级

`python3 tools/build_update.py` 仍生成一个 `release/aiot-workbench.zip` 和配套 `workbench-update.json`，用于首次分发、U 盘安装和离线验证。它们不是在线同步的前提。完整包保留 123 个 ARM64 离线依赖。

从 2026.11.20.1 或更早整合版升级到当前版本，请先退出程序，用新安装包**覆盖整个 aiot-workbench 目录**，然后运行 `bash install.sh`。公共模块已迁移到 shared，不能只替换 session_cli.py。原外部设置和 publish 资源保留；以后通过主页“程序更新”从仓库自身目录升级。

## 开发与验收

`shared/` 是唯一的同步、比较和配置事务后台；`launcher/` 保留启动停止、成果与会话控制；`engineer/` 保留维护界面和 Demo。维护窗口仍使用独立进程，防止 Tk 主题和长任务干扰用户主页。所有独立入口显式加载 bootstrap，不依赖 PYTHONPATH 或当前工作目录。

```bash
python3 tools/test.py all
```

测试分别启动独立解释器，日志保存在 `.tmp/`。Ubuntu WSL 验证后台流程；缺少 Tk 的环境跳过 GUI 测试。Python 3.8 语法兼容已检查。ARM64 实机上的 AIotApp、动态库、硬件 Demo、桌面信任状态和网络条件，仍需在实际设备验收。
