# dot-abyss-ps

《ドットアビスX》PC 版的本地服务端、客户端适配插件与管理启动器。适配版本与运行环境见 [changelog](changelog.md)。

- 涵盖常驻养成、主线剧情与教程、各战斗模式、活动及本地复刻。
- 支持多存档管理、数据编辑、备份恢复与客户端同步。
- 通过控制台启动、停止或重启服务，实时查看日志。
- 启动器内置繁体翻译一键安装与更新。
- 支持配置与数据热更新，根据模块在实时、切换页面、下一场战斗或重新登录后生效。

具体玩法规则与说明见 [文档目录](docs/README.md)。

## 使用

准备 Windows、Python、.NET SDK，以及对应版本的 PC 客户端和已下载资源。游戏加载器使用 BepInEx IL2CPP x64，版本要求见 [运行与构建环境](changelog.md#运行与构建环境)。

```powershell
.\setup-pc.ps1 -Source 'D:\dot\dotabyss_x_cl'
```

将路径替换为原版游戏目录。脚本会自动配置 Python 环境、本机配置、主数据和资源索引；加载器安装与首次 interop 生成见 [PC 首次启动](docs/first-start.md)。

配置完成后，双击 `start-console.cmd`，点击“启动服务”，选择或创建存档，再点击“启动游戏”。日常编辑、热更新和备份说明见 [启动器与控制台](console/README.md)。

版本、结构和资源绑定统一维护在 [版本清单](pc/releases/manifest.json)，各端自动读取或生成绑定。主数据维护与更新方法见 [主数据维护](docs/masterdata.md#2-版本清单维护与热更新)。

## 文档

- [首次启动与缓存位置](docs/first-start.md)
- [养成、奖励与解锁](docs/progression-and-rewards.md)
- [主线与教程](docs/main-story-battle.md)、[其他战斗模式](docs/other-battle-modes.md)、[活动与复刻](docs/events-and-reruns.md)
- [数据维护及完整目录](docs/README.md)
- [适配记录](changelog.md)

## 运行库兼容补丁

根目录提供 [Il2CppInterop.Runtime.dll](Il2CppInterop.Runtime.dll) 和 [Il2CppInterop.HarmonySupport.dll](Il2CppInterop.HarmonySupport.dll)，用于修复 Windows x64 值类型参数传递和泛型字段装箱问题。

1. 退出游戏，备份游戏目录 `BepInEx/core/` 中的两个同名 DLL（哈希说明见 [兼容构建说明](third_party/Il2CppInterop/COMPATIBILITY.md)）。
2. 将仓库根目录的两个 DLL 复制到游戏的 `BepInEx/core/` 并覆盖原文件。
3. 重新启动游戏。

源码与修改记录位于 [third_party/Il2CppInterop](third_party/Il2CppInterop/)。

## 中文翻译

繁体译文基于 [s88037zz/dotabyss-translation](https://github.com/s88037zz/dotabyss-translation)，翻译插件基于 [s88037zz/AbyssMod](https://github.com/s88037zz/AbyssMod)（[MIT 许可](pc-translation/LICENSE.AbyssMod)）。内置本地缓存，并补充了技能说明、新手引导、通用界面、任务和商店译文，启动器更新时会自动合并。

配置与更新方式见 [翻译集成说明](pc-translation/README.md)。

## 参与贡献

欢迎提交 Issue 和 PR。反馈问题请附上客户端版本、复现步骤及相关日志片段。
