# 繁体翻译集成

繁体译文源自 [s88037zz/dotabyss-translation](https://github.com/s88037zz/dotabyss-translation)，翻译插件基于 [s88037zz/AbyssMod](https://github.com/s88037zz/AbyssMod)（[MIT 许可](LICENSE.AbyssMod)）。集成方案采用完整本地字典缓存，无需在游戏运行时请求外部 CDN。

## 启动器一键安装

准备好本地 PC 客户端、Git 和 .NET SDK 后，打开启动器，在“繁体中文”栏点击“一键安装”或“更新翻译”（安装前请先退出游戏）。启动器会自动拉取插件源码、兼容补丁、字体依赖与译文仓库，编译并安装到本地客户端，重开游戏即可生效。

## 安装路径与配置

基线版本与统计记录见 [翻译基线](../changelog.md#翻译基线)。插件直接基于本地客户端的 BepInEx core 与 interop 编译：

- 插件路径：`dotabyss_pc/local-client/BepInEx/plugins/AbyssMod/`
- 配置文件：`dotabyss_pc/local-client/BepInEx/config/AbyssMod.cfg`

默认启用 `zh_Hant` 本地翻译，关闭在线 CDN、实时机翻与文本采集。项目维护的补充译文位于 `overrides/`。

## 通用文本补译

除上游剧情与主表字典外，本地补译覆盖了以下内容：

- 被动、觉醒和主动技能说明、技能名称、魔力水晶及深渊代码效果。
- 教程资源文本、训练帮助与过场提示。
- 界面按钮、确认弹窗、菜单与系统提示（保留数值与角色名等动态格式化参数）。
- 任务条件、商品与礼包说明、订阅说明、兑换分类。
- 设施、研究、酒馆提案、道具用途，以及补充的角色、服装和武器外观名称。

安装脚本在合并补译前会自动校验格式化变量、数字、富文本标签与换行符。`mapping-overrides.json` 用于补充主表字段映射，`corrections.json` 用于修正已知词条。

## 本地兼容补丁

- 排除主表 `MNgWords`（屏蔽词表）的翻译映射，避免影响起名过滤规则。
- `input-text-compat.patch`：保护 `TMP_InputField` 的玩家输入值不被 UI 翻译覆盖，仅翻译占位提示文本。
- `general-text-compat.patch`：修复空字典屏蔽新技能字典、带参数技能描述无法命中、以及纯汉字词条被跳过的问题，精准保留技能固定秒数、HIT 数与触发条件。

## 命令行更新与快捷键

也可在退出游戏后，于项目根目录手动执行更新：

```powershell
.\update-translation.ps1 -Fetch
```

该命令会拉取最新译文、合并补译、重建本地清单并编译安装插件（省略 `-Fetch` 则仅用本地缓存重新安装）。安装记录保存在 `artifacts/translation/installed.json`，备份位于 `artifacts/translation/backups/`。

游戏内快捷键：`F8` 切换翻译开关，`F10` 重载配置文件。
