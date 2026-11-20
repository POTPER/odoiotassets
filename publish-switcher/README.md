# publish 文件同步与配置工具

“金砖赛事版本”启动器已独立到仓库根目录的 `aiot-launcher` 文件夹。安装和背景图片说明见 [启动器使用说明](../aiot-launcher/README.md)，请在该文件夹运行 `python3 aiot_launcher.py`。

中文桌面工具，面向 Ubuntu ARM64，Python 3.8+ / Tkinter，无 pip 依赖，兼容设备上的 Python 3.8.10。

## 用户界面和程序更新

运行 python3 switcher.py gui 或桌面快捷方式会打开用户界面。启动时先检查 Switcher 程序版本，发现新版本后，需要点“更新并重启”完成更新才能使用配置切换、文件更新和功能测试。版本检查失败时可重试，也可从“程序更新”导入离线发布信息。

用户界面收起了目录、仓库、同步格式、权限策略和配置映射等实施参数。按 Ctrl+Shift+F12 可切换到工程师界面，再按一次回到用户界面。重启后默认进入用户界面。实施人员也可运行 python3 switcher.py gui --engineer 直接进入工程师界面。

工程师“设置”中有独立的“Switcher 程序更新源”，可保存发布信息的 HTTPS 地址。默认预设为 https://gitee.com/potper/odoiotassets/raw/main/publish-switcher/release/switcher-update.json 。将整个 publish-switcher 文件夹上传到该仓库 main 分支即可包含发布所需文件。已安装旧版若保存过仓库根目录的更新地址，请在工程师面板改为新地址。

程序更新先下载到工具目录外，检查大小、SHA-256、安装包内部版本和完整性，准备完整的新目录后关闭当前窗口。外部更新助手保留旧程序目录，整体切换并验证新版本，再打开工具。异常时恢复旧目录。首次覆盖本版后请再运行安装脚本，桌面快捷方式会使用工具目录外的恢复入口。

### 发布新版 Switcher

更新 version.py 中的版本号后，在项目根目录运行：

~~~bash
python3 publish-switcher/tools/build_update.py
~~~

命令在 publish-switcher/release/ 内生成唯一安装包 publish-switcher.zip，以及配套的 switcher-update.json。上传整个 publish-switcher 文件夹即可。release 目录不参与 ZIP 内容打包，重复生成时也不会把上一次的 ZIP 和 JSON 装进新包。每个新版本都会要求用户完成更新后使用。如果安装包放在 Releases、对象存储或其他 HTTPS 服务器，生成时指定设备可下载的地址：

~~~bash
python3 publish-switcher/tools/build_update.py --url https://你的服务器/publish-switcher.zip
~~~

安装包更换后要重新生成发布信息，才能使大小、SHA-256 与实际文件一致。离线设备将 JSON 和 ZIP 放在同一个文件夹，在“程序更新”选择“导入离线更新”，选中 JSON。已知有较新必更版本时会拒绝较旧离线包。更新重启后仍离线时，可再次导入同一 JSON 确认当前版本并打开用户功能。

## 当前同步范围

“更新文件”页按勾选格式处理文件；“Assets 资源”页独立比较并补齐 Assets 文件。

- 默认递归同步 **`.py`、`.json`、`.ttf` 普通文件**，后缀不区分大小写；可以从远端识别更多格式并自行勾选。
- **先检查比较，再由用户选择更新方式**，默认选择增量更新。
- **增量更新**：只补齐已勾选格式的缺失文件，已有文件即使内容不同也跳过，本地多余文件保留。
- **严格更新**：新增缺失文件、替换内容不同的同名文件、删除远端没有的本地同类文件，均限定在勾选格式内；相同文件不重复下载。默认保留已有文件权限，勾选“同步文件权限”后才同时处理权限差异。
- 勾选 `.json` 时，严格更新也更新当前生效的 TrainTaskInfo.json、删除多余结果 JSON。配置切换仍是独立功能。
- **未勾选的格式不下载、不替换、不删除。** AIotApp、模型、动态库、图片、视频、压缩包、`.sh` 等默认不勾选。`.ttf` 字体会部署到 publish 的对应相对路径，不安装到系统字体目录。
- 其他文件只提示本机缺失、类型或大小不同、远端为空、本地额外文件。大小相同不表示内容相同：不会读取大文件内容计算哈希。
- 未勾选格式的空文件只提示；本次待同步的空文件默认阻止，确需允许时逐项配置 `allow_empty`。
- 文件与本机目录或符号链接冲突时停止，避免覆盖其他资源。两个更新入口都不部署远端符号链接。
- 恢复备份按**当次同步记录的格式**恢复，不受当前勾选变化影响；其他格式保持本机内容。没有格式记录的旧版备份继续只恢复 `.py/.json`。

文件更新、配置切换不会自动执行脚本或启动主程序。“IoT Demo”是独立的主动运行功能；工具只停止本次运行的 Demo，不自动结束其他已有程序。

## 同步格式勾选与字体下载

在“更新文件”页刷新远端方案、选择 Jetson 或 RK，点击 **“同步格式…”**。工具读取所选方案的完整远端清单（或固定提交的目录树），显示每种扩展名的文件数量和总大小，不下载文件正文。勾选需要同步的格式后保存，再检查差异、选择增量／严格更新并执行。

默认勾选 `.py/.json/.ttf`；新发现的其他格式不自动勾选。支持 `.otf` 等任意扩展名以及“无扩展名”；按最后一个后缀识别，如 `.tar.gz` 归为 `.gz`。目录、符号链接不计为可同步文件。修改勾选使原检查结果失效，空选时禁止更新。

格式选择保存为设置中的 `file_extensions`，最近一次清单识别结果及方案版本保存为 `format_inventory`，重启沿用；每次打开格式设置都会按当前方案重新读取。记录的是扩展名、数量和大小，不是资源正文。离线时可从已缓存清单识别格式，下载仍需文件缓存完整。“Assets 资源”页不受格式勾选影响，继续只补缺失文件；Assets 内已勾选的格式也属于“更新文件”页的范围。

SSH 数字菜单新增 **13. 读取／勾选同步文件格式**。也可以使用：

```bash
# 列出格式、勾选状态、数量和大小
python3 switcher.py formats --profile rk
# 保存格式选择；不会修改 publish
python3 switcher.py formats --profile rk --extensions .py,.json,.ttf --save
# 本次只检查／补齐 ttf，已有同名字体会跳过
python3 switcher.py check --profile rk --extensions .ttf
python3 switcher.py sync --profile rk --extensions .ttf --mode incremental --yes
```

字体等二进制文件按大小和内容哈希比较；不会因修改时间不同而替换。文字差异视图只适用于可解码的文本。如果来源是生成器制作的 catalog，而某种格式只发布了元数据、没有上传文件正文，工具会明确阻止下载；发布方需用 `generate.py --extensions .py,.json,.ttf,.otf` 重新制作新版本。原生 publish_RK／publish_jetson 仓库中的实际 `.ttf` 文件可以直接下载。

### Gitee 字体下载提示 HTTP 403

2026-11-03 对当前资源仓库实测：约 9.8 MB 的 `IoT/06-OLED/Font.ttf` 普通下载可用，23,278,008 字节的 `app/Fire_Seg/Arial-Unicode.ttf` 普通下载地址返回 `large file require login for access`。这是 Gitee 下载端的访问限制，与本机 root／ztl 所有者、chmod 或 CRLF/LF 无关。

当前版本遇到 **Gitee 仓库相对文件的 raw 下载返回 403** 时，会尝试相同仓库的公开 Git Blob API。通过清单的 Git blob 哈希锁定文件；SHA-256 清单则从同一固定提交的完整目录树解析 Blob，再校验实际字节大小、Blob SHA 和清单校验值。任何不完整、错误编码、错误哈希的内容都不会部署；API 也拒绝访问时立即报告，不自动登录或切换到其他仓库。

已使用新版代码实际下载上述 23,278,008 字节字体，Git blob SHA-1 为 `1537c5b8ce93403eba59b2c46fc08886a1c630cf`，与固定提交一致。同内容字体共用已验证缓存，不重复请求。未使用 `contents` API 下载大文件：本次该接口声明 23,278,008 字节，但实际内容仅有 10,485,760 字节，不能当成完整字体。

Blob API 的 JSON/Base64 会增加内存和传输开销，第一版仅为不超过 32 MiB 的文件提供此备用方式，支持读取期间取消和原有网络重试。更大的文件、API 配额或权限限制仍需通过有权限的下载方式获取后手动复制，或在清单中配置 Releases HTTPS 来源；不会跳过校验。外部 HTTPS 地址和 GitHub 的 403 不使用此 Gitee 备用方式。

更新时关闭旧窗口，覆盖**整个工具文件夹**，包括新增的 `gitee_download.py`，再从该目录运行 `python3 switcher.py gui`，重新检查、同步即可；不用修改资源仓库或给字体设置 777。

## GUI 页面组织

软件图标为深色圆角底的白色／淡蓝色双向箭头，表示文件更新和配置切换。窗口、对话框和侧栏使用同一图标；`bash install.sh` 会把多尺寸 PNG 与 SVG 安装到当前用户的图标目录，并更新应用菜单和桌面上的 `publish-switcher.desktop`。快捷方式使用安装后图标的绝对路径，避免图标主题缓存影响显示。无需新增 pip 依赖，SSH 模式无需图标或 Tkinter。

图标文件在 `icons/`：SVG 可编辑，PNG 包含 16–512 像素，ICO 可用于 Windows 快捷方式。开发时重新生成位图可用 Pillow 9.1+ 运行 `python tools/build_icons.py`，普通用户无需执行。更新时请一起复制 `icons/` 和 `switcher_icon.py`，再运行 `bash install.sh`。安装脚本优先识别系统配置的桌面目录，也支持 `Desktop`／`桌面`；桌面被禁用时仅安装应用菜单入口。安装时尝试设置“信任”，若仍显示文本图标或不能双击，请在设备桌面右键新生成的快捷方式，选择“允许启动”或“信任并启动”。其他名称的旧桌面副本不会自动覆盖，请使用安装日志中显示的新入口。

界面沿用 AIoT 启动器参考的 Epic Launcher 风格：黑灰背景、左侧功能导航、浅色主操作按钮、淡蓝选中标记和深色数据列表。六个功能入口与原操作流程保持一致，命令行入口及已保存设置也保持兼容。

- **更新文件**：选择方案 → 检查差异 → 选择增量或严格方式 → 执行更新。差异表可横向、纵向滚动，选择文件后可直接查看红绿逐行差异；下方摘要显示当前方式、变更数量和下载量。
- **Assets 资源**：选择方案 → 检查资源差异 → 下载缺失资源。比较实际内容哈希，显示本地/来源大小、缓存状态和增量处理；相同内容为绿色，其他情况可查看校验信息。
- **配置切换**：版本列表、三个文件的映射预览、JSON 对比和应用按钮集中在一页；版本来自本机 `publish/config` 的直接子文件夹。
- **IoT Demo**：左侧勾选模块，顶部启动或停止队列，右侧切换“实时日志”和“本次结果”。支持单个运行、顺序运行勾选项或全部模块，以及从结果页重跑失败和未启动的模块。
- **辅助工具**：集中放置手动权限预设、恢复上次文件更新和比较自测；更新页的“权限预设 / 恢复”可直接跳转到这里。
- **设置**：修改 publish 目录、仓库、分支及方案目录，点击“保存设置 / 读取缓存”后生效。顶部始终显示目标目录，可用右上角按钮进入设置；首次未配置目录时自动打开设置页。

操作日志默认折叠，底部“展开日志”随时打开，出错时自动展开；折叠不会停止记录。进度、状态和取消按钮常驻底部。默认窗口最大 1240×780，会按屏幕尺寸收缩，最小 900×640；窄于 1120 像素时左栏变为图标与短标签，标题区收紧，保留主要操作和列表空间。方案表和差异表之间可拖动分隔线调整空间。

顶部状态标记区分就绪、处理、Demo 运行和操作失败。侧栏支持鼠标点击、Tab 焦点与 Enter/空格激活，也可使用 Ctrl+Tab 切换页面。文字、输入框、日志、方案编辑、资源详情和 JSON 对比窗口统一深色显示，红绿差异使用适合深色背景的配色。根据系统已有字体自动选择中文字体，仍只依赖 Python/Tkinter，不需要安装第三方主题或连接启动器目录。

2026-10-29 已再次修正旧版深色主题的 Python 3.8 字体调用兼容问题。若启动报 `nametofont() takes 1 positional argument but 2 were given` 或 `nametofont() got an unexpected keyword argument 'root'`，更新 switcher_style.py 或覆盖完整修复包即可；不需要升级系统 Python。当前使用 `font.Font(root=root, name=字体名, exists=True)` 访问指定 Tk 实例的已有字体，不再调用 nametofont。已对照 [CPython 3.8.10 源码](https://github.com/python/cpython/blob/v3.8.10/Lib/tkinter/font.py) 修正模拟测试：nametofont 的真实签名只有 (name)，也不接受 root 关键字。

“清单已缓存”表示方案的文件列表已缓存，资源文件是否完整缓存仍需检查，不代表已经应用该方案。

## Assets 资源对比与增量下载

在“Assets 资源”页选择 Jetson/RK 等方案，可直接刷新远端列表或导入本地 catalog，然后点“1. 检查资源差异”。资源来源与更新文件页相同，仓库内下载固定到同一提交。比较覆盖方案中 Assets/assets 顶层目录下递归的普通文件，图片、视频、图标、字体、文本等均可；路径大小写和文件名按仓库原样保留。

比较按实际内容哈希判断，不能仅用大小推断相同：本地流式计算 SHA-256 和 Git blob SHA-1，按清单提供的校验类型比较。表格显示相同、新增、内容不同、本地空文件、路径冲突和仅本地文件；“查看资源校验信息”显示双方大小、哈希、权限及固定来源。图片、视频等二进制文件不生成红绿逐行文本差异。

**增量规则沿用已有约定：只新增缺失文件。已有同名文件即使内容不同、大小不同或为零字节，也不会覆盖；本地额外资源不删除。** 本地空文件单独标出并跳过；来源中待下载文件为空时默认阻止，确需保留应在清单/preset 中设置 allowed_empty/allow_empty。资源页没有严格更新或删除功能。

检查完成后点击“2. 下载缺失资源”确认。界面显示新增总量、实际联网下载量及每个文件的下载字节进度，可取消准备；完整缓存可直接复用，相同资源不重复下载。下载到 publish 外校验大小与 SHA-256/Git blob SHA-1，再在同一文件系统准备并校验新目录，最后切换；网络失败、校验失败、取消或预览后本地资源变化均保留原目录，未完成切换在下次打开工具时恢复。现有资源文件通过硬链接保留，保持其内容、权限和所有者；已有目录沿用原权限，新文件使用清单权限。

操作使用与文件更新、配置切换、IoT Demo 相同的外部锁，应用前要求相关程序退出。缓存仍位于目标旁 .publish-switcher-publish/objects，资源操作记录为 assets-current.json，事务为 assets-transaction.json；不会覆盖所选格式的 current.json 恢复记录。资源操作会生成整目录备份，路径在操作日志中显示；当前“恢复上次更新”仍按原规则只恢复所选格式，图片/视频等资源不会被该功能撤回。Assets 内如含已勾选格式，也属于文件更新范围；恢复按当次记录的格式执行，资源页只提供额外的缺失补齐入口。

SSH 终端菜单增加 **12. Assets 资源对比／增量下载**，先显示比较，再输入 yes 确认下载；不确认则只检查。直接命令：

```bash
# 比较 Assets 内容，不下载
python3 switcher.py assets check --profile rk

# 再次检查并确认补齐缺失资源
python3 switcher.py assets download --profile rk --yes

# 完整缓存支持离线补齐，不允许回退到网络下载
python3 switcher.py --offline assets download --profile rk --yes
```

--target、--repo、--branch、--local-catalog 等全局参数放在 assets 前，--profile/--version 放在 check/download 后。完整缓存指待补齐文件的实际内容已下载并校验，不是只有清单。缓存和备份不自动清理。

原生 publish_* 仓库已有 Assets 文件时无需另做清单。使用 generate.py 发布 catalog 时，新版本会复制所选格式**以及 Assets 文件**；旧版生成器只复制过所选格式，旧 catalog 中缺少实际资源时须重新生成新版本或设置真实外部来源。大资源可用 --external-map 指向 Releases 的 HTTPS 下载地址，清单应记录实际资源的大小和 SHA-256。Git LFS 指针不会被当成图片/视频部署；如果下载得到指针会停止并提示改用实际资源来源。

## 配置 JSON 对比

在“配置切换”页选择版本，再在下面的三个文件映射表中选择一个 JSON，点击 **“查看所选 JSON 差异”**，也可以双击文件行。对比方向固定为 **publish 根目录当前生效文件 → publish/config/所选版本/对应模板**，全程只读，不联网、不上传、不应用配置。

窗口提供三个页签：

- **对比摘要**：版本、双方完整路径、文件大小、SHA-256 和结果。字节相同显示“相同”；统一 JSON 格式后相同显示“仅 JSON 格式不同”；其他显示“内容不同”或“新增”。映射表绿色表示字节相同，其他情况可查看具体差异。
- **JSON 内容差异（格式化）**：默认页签，将双方统一缩进并排序对象字段，减少缩进、对象字段顺序等干扰；数组顺序和数值/字符串/布尔等类型差异仍保留。红色 - 是当前配置被删除的内容，绿色 + 是版本模板新增的内容。显示前后各三行上下文，两列行号对应格式化后的旧版/新版。
- **原始文本差异**：查看实际文件文本的行号和变化；CRLF/LF、BOM 差别会单独说明。支持双向滚动和复制完整对比。

当前生效文件缺失时显示模板新增的全部内容；当前文件无法解析、包含重复字段或非标准数值时，仅提供原始文本差异及原因。缺失其他配置的版本也可查看其中有效文件的差异，但仍禁止应用不完整版本。源模板冲突/无效、路径为符号链接、未完成事务等情况会阻止相应对比。超过每侧 1 MiB 时保留摘要，文本预览还沿用行数及输出截断限制。

格式化只用于显示，**应用版本仍按模板原始字节整套复制三个文件**，不会重排或重写 JSON。预览后或读取期间任一配置发生变化，会要求重新检查版本。日志只保存摘要，不写入 JSON 逐行正文。

SSH 数字菜单新增 **11. 查看配置 JSON 差异**；直接命令支持：

```bash
# 对比指定 JSON；--target 可省略，沿用已保存目录
python3 switcher.py config diff --version 福建农职 --file TrainTaskInfo.json

# 不指定 --file 时对比三个 JSON
python3 switcher.py config diff --version 福建农职

# 查看原始文本差异
python3 switcher.py config diff --version 福建农职 --file TrainTaskInfo.json --raw
```

SSH 默认展示格式化后的 JSON 差异，无法可靠解析时自动展示原始文本；交互终端红绿着色，重定向或 NO_COLOR 时输出纯文本。文件更新页中，云端所选格式与本地文件的比较仍使用“查看选中文件差异”入口。

## IoT Demo 运行与调试

已整合到 Switcher，无需再安装独立 iot-demo-runner，也无需 pip。沿用设置中保存的 publish 目录，读取根目录当前生效的 TrainTaskInfo.json；不读取 config 中尚未启用的版本。打开“IoT Demo”页自动读取任务，也可手动刷新。配置切换或文件更新后任务缓存失效，重新进入页面后按新配置显示，真正启动前再次读取当前 JSON。

退出主程序及其他硬件任务后，打开“IoT Demo”。单击卡片可选中模块，再点“运行当前”。双击卡片也可进入运行确认。勾选卡片上的复选框后，点“运行勾选”组队列。左侧可刷新模块、全选可运行项或清空勾选，分隔条可拖动调整左右宽度。点“停止全部”或窗口底部的停止按钮可结束本次启动的脚本，关闭窗口会等待进程退出。

“运行勾选”和“全部运行”都按当前 TrainTaskInfo.json 的排列顺序执行。当前模块的脚本退出、进程和日志线程清理完成后才启动下一项。启动前会重新读取配置并预检待运行脚本与解释器，配置变化时需刷新。全部运行的确认窗口会列出缺少脚本等不可运行模块。

不同模块即使引用相同脚本，也会按顺序各执行一次，使用各自配置的解释器，不跨模块合并或共用进程。模块内部若配置了 `|` 分隔的多个脚本，仍按原组合规则同时运行并去重，必须全部结束才轮到下一个模块。任一模块异常时中止后续队列。全部停止及关闭窗口只清理当前模块的本次进程，并把剩余模块标为“未启动”，不结束其他已有程序。

队列运行时可以点“跳过当前”。工具会停止当前模块的本次脚本，等进程及输出线程清理完成后再启动下一项。单独运行时使用“停止全部”结束任务。一直运行的 Demo 需要自行结束或手动跳过。“跳过当前”以队列正在运行的模块为准，同时请求跳过和停止时按停止处理。

**队列进度与耗时**：上方显示“正在运行第 N / 总数 个”、模块名称、当前模块用时及总用时；进度条按已处理的模块数推进，完成、跳过和异常分别保留各自状态。卡片保留该模块耗时，运行结束后计时停止。进度包含清理阶段，只有清理完成才算处理完当前模块，不把未启动的模块算作已完成。

卡片状态来自运行器的结构化进程事件，不从日志文字猜测：显示等待启动、运行中、已完成、异常、已跳过、已停止或未启动；每个脚本列出实际相对路径、PID 及退出码。组合模块分别显示多个脚本状态。顶部和下方摘要实时统计模块状态；运行期间可选择其他卡片查看，下一个模块开始时自动跟随，但不能重复启动、更新文件或切换配置。

右侧“本次结果”列出各模块的状态、耗时和退出码。选中一行，下方会显示具体脚本及其退出码、启动检查错误或未启动原因。选中的模块有日志时，可以点“查看日志”。“重跑失败及未启动”会按原顺序运行待处理模块。脚本自行返回退出码 130 时会记为异常，手动停止会记为已停止。

启动检查发现任务配置已变化、脚本缺失或解释器失效时，请根据结果页的提示处理，再点左侧“刷新”。如果模块列表为空，左栏会说明是当前配置没有 IoT 模块，还是任务配置读取失败。

队列保存独立的 `iotdemo-all-*.log` 汇总日志，每个模块也有自己的完整日志文件。“实时日志”可选“全部日志”或“当前模块日志”，后者对应左侧选中的卡片。向上滚动时会暂停跟随，点“回到最新”可以继续看实时输出。运行器识别的失败信息用红色显示，停止和跳过提示用黄色显示。

路径栏随筛选范围显示汇总或模块日志文件。界面缓存全批次最近约 3000 行，较早模块的输出已离开缓存时可以从日志文件读回末尾。“复制”复制当前显示的内容，“导出…”保存当前范围的完整日志文件。运行中导出保存截至导出时刻的内容。

路径规则与现有配置一致：

- `PythonScriptPath: "ActiveBuzzer_Demo30.py"` 配合 `ScriptFloderPath: "IoT/02-ActiveBuzzer"`，运行 IoT/02-ActiveBuzzer/ActiveBuzzer_Demo30.py。
- 已有 `IoT/.../xxx.py` 的路径相对于 publish 定位，支持反斜杠；多个路径用 `|` 分隔时同时运行，重复路径去重。
- **只运行 PythonScriptPath**。组合任务中 ScriptFloderPath 可能列出其他执行器，运行器不额外启动这些执行器，也不模拟主程序告警联动。app 中的 AI 模型任务不在本页运行范围。
- 每个脚本以自己所在目录为工作目录，保证原 Demo 的 `./libSmartSensorDriver.so` 等相对路径按原目录加载。启动前校验全部脚本；缺失、零字节、不可读取、路径越界或解释器不可执行时禁止启动。就绪只表示路径与解释器检查通过，硬件和 Python 依赖仍需实机验证。

SSH 数字菜单 `python3 switcher.py cli` 新增 **10. 运行 IoT Demo**，输入配置中的 TrainTaskId 运行，Ctrl+C 停止任务，0/q 返回 Switcher 主菜单。也支持直接命令：

```bash
# 已保存 publish 目录时：进入任务菜单
python3 switcher.py demo

# 临时指定目录，只列任务或检查某个任务
python3 switcher.py --target /实际路径/publish demo --list
python3 switcher.py --target /实际路径/publish demo --task 2 --check

# 直接运行当前 JSON 中编号为 2 的任务
python3 switcher.py demo --task 2

# 临时覆盖 PythonExePath（例如使用虚拟环境）
python3 switcher.py demo --task 2 --python python3
```

PythonExePath 有值时使用其指定解释器，缺失或为空时使用启动工具的解释器。默认日志位于 `~/.config/publish-switcher/logs/iot-demo/`，遵循 XDG_CONFIG_HOME；SSH 的全局 --log-file 可改变其默认父目录，也可用 demo --demo-log-dir 指定 publish 外的日志目录。GUI 路径框可复制本次文件路径，SSH 可使用 tail -f 完整路径 查看。运行过程日志与 Switcher 操作日志分开，操作日志记录任务启动/结束及结果。

运行全程持有现有外部操作锁，阻止其他 Switcher 实例同时更新文件、恢复或切换配置；本窗口相关按钮也禁用。Ubuntu 启动前检查主程序及相关任务已退出，不自动结束已有程序。组合任务任一脚本异常退出会停止本次其他脚本，Ctrl+C/停止/关闭均清理本次启动的进程；Ubuntu 终端模式还处理 SIGTERM/SIGHUP，先发停止信号，超时再终止。直接 --task 正常返回 0，失败返回非零，手动停止返回 130。

运行器不修改配置和 Demo 源码；原 Demo 本身仍会操作硬件、发送 UDP、写入 student_data 或成果文件，具体行为和停止后的硬件状态由原脚本决定。运行 Demo 后文件检查会失效，需要重新检查再更新。该功能的测试只运行模拟 Demo，真实 ARM64 驱动、传感器及组合任务仍需设备验收。

## 手动权限预设

“辅助工具”页面提供“所有者设为 root:root”“权限设为 777”“依次设为 root:root 和 777”三个按钮。目标使用顶部当前选定并保存的 publish 目录，路径没有写死；例如目标为 /home/ubuntu/linux-arm64/publish 时，组合预设按顺序执行与下面两条命令对应的操作：

```bash
sudo chown -R root:root /home/ubuntu/linux-arm64/publish
sudo chmod -R 777 /home/ubuntu/linux-arm64/publish
```

这是独立的手动操作，递归修改整个 publish 的文件属性，包括主程序、.sh、动态库、模型、配置和日志；普通文件更新仍只同步所选格式。777 允许所有用户读写执行；设为 root:root 改变所有者和所属组。预设不修改文件内容、不下载资源，也不会自动应用远端方案。桌面上的 AIOT.desktop 位于 publish 外，因此不属于这个预设范围。

操作前退出主程序及相关任务。点击按钮后先确认目标目录、实际命令和影响范围，再由 Ubuntu 的系统授权窗口请求管理员权限（pkexec），工具不收集或保存密码。使用普通账户运行 GUI 即可，无需把整个 Switcher 用 sudo 启动。缺少授权组件时重新运行 `bash install.sh`；GUI 安装会检查并安装 policykit-1，`--cli` 模式不安装这一图形授权依赖。Windows 上这些按钮不可用。

执行使用外部操作锁，拒绝系统目录、主目录、工具所在目录、目标符号链接及挂载点；检查嵌套挂载点，授权后再次核对目录身份，未完成切换必须先恢复。实际 chown 增加 -h/-P，避免跟随子目录内符号链接修改目录外目标；递归 chmod 跳过遇到的符号链接。对普通文件和目录的效果与上述预设一致。

权限预设不生成备份，也不是事务替换；失败可能已经修改部分条目，错误和已完成的步骤记录在日志。组合预设中第一条失败时不继续执行第二条。非所选格式资源与旧备份可能共享硬链接，修改这些文件的所有者或权限也会影响共享同一文件的副本。完成或失败后原文件检查失效，需要重新检查；权限改为 root 后，部分目录可能需要管理员权限才能再次读取。

## SSH 命令行与错误日志

无需桌面、DISPLAY、X11 转发或 Tkinter。通过 SSH 登录设备，进入工具目录即可运行；环境检查可执行 `bash install.sh --cli`，不会安装 Tkinter 或创建桌面快捷方式。仍支持 Python 3.8.10。

### 数字菜单入口

已经覆盖新版完整工具文件夹后，在 SSH 终端运行：

```bash
cd ~/publish-switcher
python3 switcher.py cli
```

首次进入可选“1. 设置目录、仓库和权限”，填写设备上的实际 publish 目录，再选“6. 保存设置”；以后 GUI 和终端共用保存的目录、仓库及权限偏好。若已有 GUI 设置会直接读取。菜单会显示当前目录、来源、所选方案和权限策略。也可用全局参数临时指定，例如 `python3 switcher.py --target /实际路径/publish cli`。

```text
1. 设置目录、仓库和权限
2. 刷新并选择资源方案
3. 检查文件差异
4. 应用文件更新（先检查再确认）
5. 查看／切换配置版本
6. 恢复上次更新
7. 诊断文件差异
8. 运行比较自测
9. 查看最近日志
10. 运行 IoT Demo
11. 查看配置 JSON 差异
12. Assets 资源对比／增量下载
0. 退出
```

更新先选择方案并检查，再选择增量或严格方式。确认界面显示目标、处理范围和权限策略，输入 yes 才执行。切换配置同样先显示版本名称、三个文件映射，再确认整套应用。设置或权限策略变化后需要重新检查；检查后本地文件被修改时阻止应用。程序或网络错误会保留日志并返回菜单。

菜单中的 publish 目录必须存在，路径错误时提示修改，不会按空目录继续检查；若目录因上次切换中断暂时缺失且有事务记录，会先尝试恢复再检查。来源可在设置中选择联网仓库、离线缓存或本地 catalog；来源模式只在本次菜单会话生效，也可通过 `--offline`、`--local-catalog` 启动。菜单不依赖 Tkinter，需交互终端；直接执行远程命令时 SSH 可使用 `ssh -t` 分配终端。Ctrl+C 中断当前操作返回菜单，在主菜单按 Ctrl+C 或输入 0 退出；文件切换仍使用原有事务恢复机制。

### 直接命令

```bash
# 查看命令
python3 switcher.py --help

# 列出远端方案（ID 默认 jetson / rk）
python3 switcher.py list

# 只检查，不应用；同时显示两种方式会如何处理
python3 switcher.py --target /home/ubuntu/linux-arm64/publish check --profile rk --mode incremental

# 针对一个文件显示大小、SHA-256、Git blob SHA-1、权限及文本差异原因
python3 switcher.py --target /home/ubuntu/linux-arm64/publish diagnose --profile rk --path IoT/01-LED_RGB/bs.py

# 不联网、不需要设置 publish，在独立临时目录验证比较规则
python3 switcher.py self-test

# 核对后增量更新，只补齐缺失（--mode 默认 incremental）
python3 switcher.py --target /home/ubuntu/linux-arm64/publish sync --profile rk --mode incremental --yes

# 明确选择严格更新，确认覆盖差异及删除本地多余所选格式
python3 switcher.py --target /home/ubuntu/linux-arm64/publish sync --profile rk --mode strict --yes

# 显式保留已有文件权限，不因 0777 / 0644 差异替换文件
python3 switcher.py --target /home/ubuntu/linux-arm64/publish check --profile rk --mode strict --keep-permissions

# 确实需要同步仓库权限时，先检查再应用
python3 switcher.py --target /home/ubuntu/linux-arm64/publish check --profile rk --mode strict --sync-permissions
python3 switcher.py --target /home/ubuntu/linux-arm64/publish sync --profile rk --mode strict --sync-permissions --yes

# 列出本机配置版本（config 直接子文件夹）
python3 switcher.py --target /home/ubuntu/linux-arm64/publish config list

# 查看某版本的三个文件映射，不替换
python3 switcher.py --target /home/ubuntu/linux-arm64/publish config check --version "福建农职"

# 核对后整套应用，不联网
python3 switcher.py --target /home/ubuntu/linux-arm64/publish config apply --version "福建农职" --yes

# 恢复上次同步的所选格式
python3 switcher.py --target /home/ubuntu/linux-arm64/publish restore --yes

# 查看最近100行错误/运行日志
python3 switcher.py logs --tail 100
```

把示例目标目录改为实际路径。若桌面工具已经保存了目录，后续可省略 `--target`。平台仍可用 `--repo`、`--branch` 改写；`--offline` 使用已缓存配置；`--local-catalog` 指定本地 catalog.json。全局选项放在子命令前，`--profile`、`--version`、`--yes` 等放在 check/sync 子命令后。例如 `python3 switcher.py --offline --target /实际/publish check --profile rk --version 版本号`。

日志默认存于 `~/.config/publish-switcher/logs/switcher.log`，遵循 XDG_CONFIG_HOME；每个文件最大2MiB，保留3份轮转备份。SSH 终端同步显示进度和完整错误栈，GUI 后台操作错误也写入日志。通过 `--log-file /可写位置/debug.log` 可改写命令行日志路径。

```bash
# 持续查看（Ctrl+C 只停止看日志）
tail -f ~/.config/publish-switcher/logs/switcher.log

# 如需单独诊断主程序，可从 publish 目录启动并保存主程序输出
./AIotApp 2>&1 | tee AIotApp-debug.log
```

工具日志记录的是同步与配置切换错误；主程序自身错误需用上面的独立命令查看。CLI 成功退出码0，失败1，命令参数错误2，Ctrl+C 中断130。中断后检查当前状态，未完成的事务会在下次打开目标时恢复。

首次更新必须覆盖全部源码，包括 switcher.py、terminal_menu.py 和 diagnostics.py。SSH 菜单用 `python3 switcher.py cli`，仍可用下面的直接命令自动化操作；直接运行 app.py 需要图形桌面。

## 比较结果、文件诊断和自测

比较在本机完成：读取当前选定远端方案的固定提交清单，与本地 publish 同路径文件的大小、校验值及 Linux 权限比较。不上传本地文件。不会因修改时间不同而判为内容不同；选择 RK 时比较 publish_RK 对应目录，选择 Jetson 时比较其对应目录。

- 绿色“相同”：字节与权限一致；绿色“内容相同”：字节一致，权限有差异但当前选择保留本地权限。两者严格更新均不替换。
- 橙色“权限不同”：开启“同步文件权限”后，字节一致但读/写/执行权限不同。例如设备文件为 0777，仓库普通文件映射为 0644；不代表代码修改。表格的权限列显示两侧数值及处理方式。
- “内容不同”：大小或校验值不同。Git 上传可能转换 CRLF/LF 换行；BOM、空格或 JSON 排版也会影响字节校验。不会自动忽略这些差异，增量/严格更新规则保持不变。

GUI 先检查差异，选择表格里一个文件，再点“查看选中文件差异”。报告显示所选方案、固定提交、来源、本地/远端大小、两种哈希和权限；下载内容校验通过后，进一步区分仅换行不同、仅 UTF-8 BOM 不同、两者皆不同或其他文本变化。

诊断窗口提供“诊断摘要”和“文本差异”两个页签。文本差异类似 Git unified diff，固定以本地为旧版、远端为新版：红色 - 行为本地被删除的内容，绿色 + 行为远端新增的内容；修改表现为旧行删除加新行新增。显示本地/远端行号、@@ 变更位置、前后各 3 行上下文，支持横向/纵向滚动。点击“复制完整报告”可复制摘要和逐行差异。这个视图只预览，不会自动修改或合并文件。

仅 CRLF/LF 或 UTF-8 BOM 不同时单独说明，避免把整份文字一致的文件显示成全部删除/新增；仅权限不同时没有文本变更。行末空格、缩进等其他文本差异仍参与对比，文件末尾没有换行时显示 Git 风格的标记。本地缺失的文本显示全部新增，仅本地文件显示全部删除。

SSH diagnose 命令和 cli 菜单“诊断文件差异”也输出同方向的逐行差异，交互终端自动使用绿色/红色，重定向时输出纯文本；设置 NO_COLOR 可关闭终端颜色。操作日志只保存诊断摘要和差异统计，逐行正文只显示在窗口/终端中，不自动写入日志。

文本原因分析最多读取每侧 16 MiB；逐行预览限每侧 1 MiB、10000 行，最多显示 2000 行或约 250000 字符。超过输入限制、无效 UTF-8 或含 NUL 字节时说明原因并保留校验摘要；输出截断时明确提示，新增/删除数只统计已显示部分。控制字符以转义形式显示。这些显示限制不改变同步校验和增量/严格更新规则。

诊断只下载选定文件到 publish 外的临时目录，完成或失败后清理；有完整已校验缓存时复用缓存。诊断始终如实显示权限差异，并单独说明当前更新策略，不会因表格显示绿色而隐藏两侧权限。SSH 加 --offline 时必须有该文件缓存。只读诊断不覆盖或删除 publish 内文件，也不会自动恢复未完成事务；遇到未完成切换时先提示处理事务。

### 文件权限策略

默认不勾选“同步文件权限”。已有所选格式即使从 0777 对应到仓库的 0644，也不会仅因权限不同而替换；内容更新时仍保留该文件原权限。新文件没有本地权限可保留，使用仓库清单的权限（通常普通文件 0644，可执行文件 0755）。其他资源和已有目录权限不受此选项影响。

勾选后，严格更新会把文件权限同步为仓库要求；内容相同的文件直接复用，不重新下载。增量更新无论是否勾选，始终跳过已有文件。切换选项后检查结果失效，需重新检查再应用；点击“保存设置 / 读取缓存”会保存偏好，SSH 默认读取同一设置，也可用 --keep-permissions / --sync-permissions 临时覆盖（选项放在 check/sync/diagnose 子命令后）。

例如：本地 script.py 为 0777，仓库为 0644，内容相同。默认严格更新不变；开启同步权限后严格更新为 0644；增量始终保持 0777。“恢复上次更新”恢复备份中的内容和权限，不受当前更新偏好影响。配置切换仍沿用原规则，保留已有三个生效 JSON 的权限。

“运行比较自测”按钮及 SSH self-test 命令使用 comparison-samples 下的独立 local/remote 样例：相同内容、CRLF/LF、实际内容变化、仅权限不同、空占位文件、缺失文件。样例复制到临时目录后测试，不执行其中的脚本，不读取用户的 publish，不需要仓库。Windows 跳过 Linux 权限差异判断，Ubuntu 会检查；临时目录退出后自动清理。更新工具时必须连同 comparison-samples 和 file_compare.py 一起复制。

## 按 config 文件夹切换整套配置

桌面仍分为“更新文件”和“配置切换”，两者独立。配置页自动扫描 publish/config 的直接子文件夹，**文件夹原名就是版本名称**，无需在工具内预设名称或额外清单。

```text
publish/
  TrainTaskInfo.json                  ← 当前生效配置
  TrainOverviewInfo.json              ← 当前生效配置
  CodeSampleTuorialInfo.json          ← 当前生效配置
  config/
    福建农职/
      TrainTaskInfo_福建农职.json
      TrainOverviewInfo_福建农职.json
      CodeSampleTuorialInfo_福建农职.json
    赛事版本1/
      TrainTaskInfo.json
      TrainOverviewInfo.json
      CodeSampleTuorialInfo.json
```

每个版本按 TrainTaskInfo、TrainOverviewInfo、CodeSampleTuorialInfo 名称前缀各识别一个 JSON。允许无版本后缀、下划线/括号/其他版本后缀以及 .JSON 扩展名；名称前缀大小写应与上述标准名一致。

- 选择版本后自动校验并显示三个源文件到三个标准生效文件的映射，确认后一次替换全部三个文件。源模板保留，其他资源不变，操作不联网。
- 缺少任意一类、同类出现多个文件、无效 JSON、目录不可读取、目录或源文件是符号链接时，显示原因并禁止应用。**不会因为存在无后缀文件而优先选择它**。
- config 根目录的旧散装模板和版本文件夹中的无关文件不参与切换。空版本文件夹显示不可用，补齐文件后刷新即可。
- 打开配置页、切换并保存 publish、完成文件更新时自动刷新；可手动点击“刷新版本列表”。新增、删除或重命名版本文件夹会在刷新后自动显示。
- 当前版本按根目录三个生效文件的实际内容共同匹配。只匹配部分时显示“自定义／未识别”；不同版本内容完全相同时列出所有匹配名称。
- 预览后源模板或生效配置发生变化时要求重新检查。先退出主程序，成功后再重新启动。

旧配置整套备份在目标旁的 .publish-switcher-publish/config-backups/时间标识/，包括原有文件、缺失状态和 record.json。三个新文件全部校验完成后才替换；中途失败整套回滚，原本不存在的生效文件会在回滚时移除。config-transaction.json 保存在工具状态目录，异常退出后在下次打开目标时优先恢复。不要手动删除未完成事务的备份和记录。

Jetson/RK 是资源平台，配置版本是 config 下的本机文件夹。增量更新只补齐缺失文件，严格更新仍会更新根目录生效 JSON，配置页随后重新识别当前版本。把同样的版本目录结构上传到各平台资源目录，文件更新功能就能下载其中的所选格式。

SSH 使用 config list / config check --version 名称 / config apply --version 名称 --yes。**旧 competition 命令及单文件切换已停用**，会提示改用版本名称，不会再猜测哪个文件夹是赛事版。

## 安装和操作

把整个工具文件夹放在 publish 外，保持路径不变。在 Ubuntu 桌面终端运行：

```bash
cd /path/to/publish-switcher
bash install.sh
python3 app.py
```

安装脚本检查 Python/Tkinter，缺少时使用 apt 安装，并添加应用菜单和桌面快捷方式。请以登录桌面的普通用户执行 `bash install.sh`，需要安装系统依赖时脚本会自行调用 sudo；不要使用 `sudo bash install.sh`，以免快捷方式装到 root 的目录。需要图形桌面和中文字体。

### 离线安装

将 `publish-switcher.zip` 拷到离线 Ubuntu 设备，解压后进入工具目录。本包的 `debs/` 自带 **Ubuntu 20.04 ARM64** 的 Python 3、Tkinter、PolicyKit 和所需依赖。设备上缺少的组件会从该目录补齐。只通过 SSH 使用时，只需 Python 3.8+。

```bash
bash install.sh --offline          # 桌面版
bash install.sh --offline --cli    # SSH 命令行版
bash install.sh --offline --with-polkit  # 桌面版及管理员授权组件
```

使用其他 Ubuntu 版本或 CPU 架构时，可以通过 `--deb-dir` 指定匹配的本地包目录。目标机用 `dpkg --print-architecture` 查看架构，Ubuntu ARM64 的输出为 `arm64`。本包的 `debs/PACKAGES.tsv` 记录软件包版本，`debs/SHA256SUMS` 可用于完整性检查。

```bash
bash install.sh --offline --deb-dir "/media/$USER/U盘/debs"
```

可在同版本、同架构的联网 Ubuntu 上准备依赖。下面的 APT 命令只下载软件包，使用空的安装状态计算依赖，以便连准备机上已安装的依赖也能收集。只准备命令行版时可去掉 `python3-tk`。

```bash
mkdir -p debs
sudo apt-get update
sudo apt-get --download-only --no-install-recommends \
  -o Dir::State::status=/dev/null -o Dir::Cache::archives="$PWD/debs" \
  install python3 python3-tk
```

把下载的 `.deb` 文件拷到离线设备。离线安装只读取本地包并使用临时 APT 软件源，依赖不齐时会显示 APT 的具体提示。需要“辅助工具”中的管理员授权操作时，将当前 Ubuntu 提供的 `pkexec` 或 `policykit-1` 一并加入下载清单，并在桌面版安装时加上 `--with-polkit`。安装完成后从应用菜单打开，或执行 `python3 switcher.py gui`。离线同步资源需要完整的本地资源包或已完整缓存的方案。

### 已安装用户更新

1. 关闭正在运行的工具。
2. 解压 `publish-switcher.zip`，用其中 publish-switcher 文件夹的全部内容覆盖原工具文件夹。
3. 在原工具目录重新运行安装脚本。离线设备使用 `bash install.sh --offline`。然后从菜单打开，或执行 `python3 switcher.py gui`。

打开“设置 → 关于工具”可查看当前运行版本和目录。终端执行 `python3 switcher.py --version` 可查看版本。

无需卸载，也无需升级系统 Python。安装脚本可重复执行，会更新快捷方式。用户设置保存在 ~/.config/publish-switcher，缓存和备份保存在目标目录旁，覆盖工具源码不会清除这些数据，也不会自动同步 publish。若工具换了位置，必须在新位置重新运行安装脚本更新快捷方式。

1. 在“设置”页选择设备上的 publish 目录，点击“保存设置 / 读取缓存”。
2. 在“更新文件”页刷新远端方案，选择 Jetson 或 RK，再点击“检查所选方案”。
3. 默认保留本地已有文件权限；需要按仓库部署权限时先勾选“严格更新同时同步仓库权限”并重新检查。表格列出新增、内容不同、权限不同、相同/内容相同、仅本地存在的文件，显示两侧权限及增量/严格更新的处理；其他类型文件的提示数量显示在摘要，详情查看操作日志。
4. 检查完成后选择“增量”或“严格”，下方摘要显示对应变更数量和下载大小，再点击“执行更新”并确认。未检查时不能执行；切换方案、权限策略或修改目录/仓库后需要重新检查。
5. 操作前退出相关任务。检查后或下载期间本地文件发生变化时停止，要求重新检查；完成后手动重启主程序。需要撤回时进入“辅助工具”使用“恢复上次更新”。

例如本地有 hat20.py、远端只有 hat30.py：增量会保留 hat20.py 并新增 hat30.py；严格会删除 hat20.py 并新增 hat30.py。如果 hat30.py 本地已有但内容不同，增量跳过，严格替换。Assets 外的模型 .rknn 等其他资源仍由你自行管理。

## 默认仓库与可编辑方案

默认仓库：`https://gitee.com/potper/odoiotassets`。同时支持修改为公开 GitHub 仓库。

| 方案 | 仓库目录 |
|---|---|
| Jetson | publish_jetson |
| RK | publish_RK |

仓库地址、分支可以修改；旧版空地址或原 GitHub 默认地址会采用新 Gitee 默认地址，其他自定义地址保留。保存设置后也可以显式改回 GitHub，后续会保留你的选择。点击设置页的“方案目录设置（Jetson / RK 等）”修改 JSON 数组，可添加方案或修改名称、目录。刷新会自动发现新增的顶层 publish_* 目录；其他命名或嵌套目录需显式添加。

设置示例：

```json
[
  {"id":"jetson","name":"Jetson","directory":"publish_jetson","executables":[],"allow_empty":[]},
  {"id":"rk","name":"RK","directory":"publish_RK","executables":[],"allow_empty":[]}
]
```

executables 指定实际同步文件的仓库目标权限：新增文件使用，已有文件仅在严格更新开启“同步文件权限”时采用；未勾选格式不受影响。allow_empty 是明确允许为空的相对文件路径。修改后保存并刷新远端；设置只保存在本机。

当前仓库不需要 catalog。工具识别 Gitee 或 GitHub 地址，使用相应平台接口读取目录树并固定到一次提交，用 Git blob SHA-1（包含 blob 头部）校验所选格式和 Assets 内容，避免混用不同提交。Git 不保留空目录，工具按实际文件创建所需父目录。缓存记录托管平台，旧 GitHub 缓存仍可离线使用。

网络中断（IncompleteRead、连接断开、超时及部分临时 HTTP 错误）自动重试，最多3次，间隔1秒、2秒，并记录日志。每次重新下载该文件，不沿用未校验的部分内容。404、证书校验失败及校验值不符不盲目重试。GitHub 分支提交使用较小的 Git reference 接口；Gitee 使用 branch 接口。两边的实际资源更新需要由仓库维护者同步，工具不会自动向另一平台推送。

## 可选：制作清单方案

现有 publish_* 布局直接可用。需要明确发布版本或指定下载来源时，可以生成 catalog：

```bash
python3 generate.py /path/to/source/publish /path/to/resource-repo \
  --id competition --name 比赛版 --version 1.0.0
```

输出仓库与源目录必须互不包含。同 ID 的新版本更新 catalog 指向；旧版本保留，已有版本不能覆写。生成命令默认复制 .py/.json/.ttf 和 Assets 普通文件；发布更多格式时指定 --extensions .py,.json,.ttf,.otf。其他文件只记录元数据并标记 payload_available=false，客户端选择这些文件时会提示发布方补齐。外部下载映射中的文件不复制到仓库。

默认拒绝空所选格式；使用可重复的 --allow-empty relative/path.py 显式允许。Windows 源缺少 Linux 权限，使用 --executable relative/script.py 指定可执行脚本；Ubuntu 生成会保留实际权限。

```text
catalog.json
profiles/competition/1.0.0/
  manifest.json
  resources/
    TrainTaskInfo.json
    TrainOverviewInfo.json
    CodeSampleTuorialInfo.json
    app/.../*.py
    IoT/.../*.py
```

catalog 使用 schema_version: 1 和 profiles 数组，每项包含 id、name、version、description、manifest（相对路径）和清单 sha256。manifest 包含 schema_version、id、name、version、entries；普通文件记录 path、type=file、mode、size、sha256、source，目录记录 path、type=directory、mode。所有父目录需显式列出，路径禁止越出方案。清单方案按 SHA-256 校验；所选格式 与 Assets 在各自入口应用。

--external-map 支持将相对文件路径映射到 HTTPS 来源。对应文件已勾选或属于 Assets 时才下载；大模型和主程序无需上传到本工具仓库。

## 缓存、备份和限制

设置默认存于 ~/.config/publish-switcher/settings.json；缓存和事务记录在目标旁的 .publish-switcher-publish/，包括 objects、profiles、backups 和 history。目标名称不同，状态目录后缀相应变化。

工具在同一文件系统准备新目录再切换。所选格式 使用独立文件；其他普通文件通过硬链接保留，内容、权限不改动，不复制大文件数据。**备份中的其他文件并非独立历史副本**，硬链接可能反映后续原地写入；恢复功能只恢复所选格式。文件系统需支持硬链接。不要手动修改工具状态目录。

准备失败、取消或校验失败不替换当前目录。切换阶段不能取消，异常退出后重新打开并保存设置会优先处理未完成事务。需要足够空间容纳本次新增/更新文件的暂存副本、未缓存的下载及余量。缓存和备份不自动清理。

Linux 通过 /proc 检查目标程序、工作目录和脚本参数。相关进程未退出或无法检查时阻止应用；请勿在切换期间重新启动任务。publish 不能是符号链接、挂载点或包含嵌套挂载点。第一版不支持特殊设备文件。仅普通 rwx 权限，不保存所有者、ACL 或扩展属性。

已缓存配置和完整的本机所选格式或文件缓存支持离线同步。第一次刷新需联网。下载中断后重新下载该文件，不做断点续传。

## 测试

```bash
python3 -m unittest discover -s tests -v
```

测试只操作独立临时目录；Windows 沙箱可能限制硬链接，需要允许测试访问独立测试目录。部署前在 ARM64 设备确认主程序仍能加载本机已安装的模型、动态库和其他资源；Assets 外的主程序、模型与驱动不由资源下载页补齐。
