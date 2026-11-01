# 启动器与控制台

[文档目录](../docs/README.md) · [首次安装](../docs/first-start.md)

## 打开与管理服务

完成首次安装后，双击根目录的 `start-console.cmd`。控制台以 Microsoft Edge 独立应用窗口运行。点击顶部“启动服务”打开工作台，再通过“启动游戏”按钮拉起客户端。

游戏服务默认监听 `http://127.0.0.1:18083`。启动器使用独立端口，提供启动、停止、重启和实时日志查看功能。关闭控制台窗口不会终止后台服务。

若需指定端口或数据目录，先在项目根目录 PowerShell 中加载 [维护命令参数](../changelog.md#维护命令参数) 变量块，再运行：

```powershell
.\start-console.ps1 -Port 18083 -DataDirectory $dataDirectory
```

连接参数保存在 `%LOCALAPPDATA%\DotAbyssConsole\settings.json`。

## 存档与游戏启动

1. 在顶部选择或新建存档（新档默认开启序章引导，可分别设置存档显示名与游戏昵称）。
2. 点击“启动游戏”，自动生成 `pc-local.json` 并写入隔离目录、服务地址与当前存档标识。
3. 切换存档时，先退出游戏，在顶部选择目标存档后重新启动。

顶部区分“当前编辑档”与“游戏使用档”。重命名仅修改控制台显示名称（最多 64 字符），游戏内昵称可通过“玩家资料”修改。

## 编辑与热更新

1. 在左侧选择功能模块与具体修改项。
2. 填写参数，支持通过“选择…”按译名、原文或 ID 搜索并多选回填。
3. 点击“预览修改”核对变更明细与生效方式。
4. 点击“应用修改”提交保存。

热更新生效方式视模块而定：部分即时同步，部分在切换页面、下一场战斗或重新登录后生效。详细规则见 [养成、奖励与解锁](../docs/progression-and-rewards.md)。

“任务与邮件”支持开放特殊任务天数、批量设置任务完成状态、一键领取可领任务奖励，详见 [任务批量操作](../docs/progression-and-rewards.md#任务批量操作)。

## 备份与恢复

“存档备份”支持手动备份、JSON 导入导出，以及按操作历史预览并回滚存档。

## 翻译与快捷操作

“繁体中文”栏提供翻译插件与字典的一键安装及更新（需先退出游戏，详见 [翻译集成说明](../pc-translation/README.md)）。

- `F5` 刷新当前页面，`Ctrl+F` 聚焦搜索框。
- `start-console.ps1 -Demo` 启动离线界面演示模式。
- `start-console.ps1 -Classic` 启动备用 Tk 桌面界面。

## 架构与测试

启动接口通过 `profile_id` 与系统锁管理游戏进程。控制台仅限本机访问，基于 `admin-token.txt` 生成一次性会话票据鉴权，日志保存在 `artifacts/launcher/`。

相关测试位于 [console/tests](tests/) 和 [tests/test_admin_launcher.py](../tests/test_admin_launcher.py)。
