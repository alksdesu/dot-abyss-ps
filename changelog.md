# 更新与适配记录

记录客户端适配版本、构建环境与内容快照。玩法与使用说明见 [文档目录](docs/README.md)。

## 2026-11-01

### 客户端支持

| 客户端 | 版本 | 支持范围 | 结构描述 |
| --- | --- | --- | --- |
| Windows x64 PC，`dotabyss_x_cl` | **1.15.0** | 主要适配目标：常驻养成、主线与教程、战斗模式、活动、启动器与管理功能 | [PC schema](artifacts/master-schema-pc-1.15.0.json) |
| Android Google Play，`com.exnoa.abyss` | 1.15.0 | 基础协议与主数据兼容 | [Play schema](artifacts/master-schema-play-1.15.0.json) |
| Android FANZA MOD，`jp.co.fanzagames.dotabyss_x_a.mod` | 1.14.4 | 协议诊断 | [FANZA schema](artifacts/master-schema-fanza-1.14.4.json) |

PC release 标识为 `pc-1.15.0-d38f026a`，定义在 [统一版本清单](pc/releases/manifest.json)；[release 示例](pc/releases/pc-1.15.0.example.json) 为自动生成的旧格式投影。对应 metadata SHA-256 为 `d38f026a769e522b136830785ad2789f834c47127be764f89ab294b4d91f056d`。

### 更新内容

- 集中维护适配版本、运行环境和维护命令参数。
- 统一版本清单分开保存客户端结构与内容快照；Python 直接解析，自动生成旧格式投影与 C# 结构常量。
- 插件改为校验运行时内容关联及结构契约，不再写死主数据或 catalog 内容哈希；安装器复用匹配的构建记录，单纯更新内容时跳过重编译。
- 安装、启动器、翻译准备和资源导入统一读取路径与隔离配置。
- 内容选择器支持单选立即回填关闭、多选确认回填，优化短窗口下的底部按钮布局。
- 内置条款与版本启动接口，修复干净安装时的 `terms/fetch` 4040 错误。
- 首次安装自动准备配置、catalog 索引和资源映射；角色收藏支持保存完整选择。
- 支持任务开放天数、批量完成和领奖独立操作；日常与周期统计对齐重置时间。
- 修复已购一次性推荐礼包重复请求时的扣费与发奖处理。

### 运行与构建环境

| 项目 | 版本与说明 |
| --- | --- |
| Python | `>=3.11`，见 [pyproject.toml](pyproject.toml) |
| PC Unity | `6000.3.8f1` |
| PC BepInEx | `6.0.0-be.791+b782da4`，IL2CPP Windows x64（[下载 ZIP](https://builds.bepinex.dev/projects/bepinex_be/791/BepInEx-Unity.IL2CPP-win-x64-6.0.0-be.791%2Bb782da4.zip) · [构建列表](https://builds.bepinex.dev/projects/bepinex_be)） |
| PC Il2CppInterop | `1.5.3.0` |
| PC 加载器自带 .NET 运行时 | `6.0.7` |
| PC 插件目标框架 | `net6.0`，直接引用客户端自身的 core 与 interop 编译 |
| 兼容库构建 SDK | `8.0.0`（`rollForward=latestFeature`），见 [global.json](third_party/Il2CppInterop/global.json) |
| 兼容库输出目录 | `third_party/Il2CppInterop/bin/Il2CppInterop.Runtime/net6.0/`、`third_party/Il2CppInterop/bin/Il2CppInterop.HarmonySupport/net6.0/` |
| catalog 格式 | Addressables 二进制 catalog v2（基于 [Unity Addressables 2.7.4](https://download.packages.unity.com/com.unity.addressables/-/com.unity.addressables-2.7.4.tgz)） |
| Android 诊断环境 | LemonLoader / MelonLoader `0.7.4`，构建目标 `net10.0` |

### 维护命令参数

日常首次安装直接运行 `setup-pc.ps1` 即可。以下变量供文档中的独立维护命令使用（在仓库根目录 PowerShell 中执行）：

```powershell
$releaseManifest = Get-Content -LiteralPath '.\pc\releases\manifest.json' -Raw | ConvertFrom-Json
$releaseProfile = $releaseManifest.releases.PSObject.Properties[$releaseManifest.default_release].Value
$dataDirectory = Join-Path $PWD.Path $releaseProfile.paths.data_directory
$schemaPath = Join-Path $PWD.Path $releaseProfile.build.schema.path
$catalogRelativePath = $releaseProfile.build.transport.catalog_path
$catalogHashRelativePath = $releaseProfile.build.transport.catalog_hash_path
```

默认本机 release 配置为 `pc/releases/pc-1.15.0.json`，未生成时读取同目录的 `.example.json`。资源索引和缺失报告保存在数据目录的 `setup/` 下。

### 兼容库指纹

上游基线为 [BepInEx/Il2CppInterop](https://github.com/BepInEx/Il2CppInterop) 提交 `dbda1cb353b0f4253345dc45136d170b9e50a5a0`。替换步骤见 [兼容说明](third_party/Il2CppInterop/COMPATIBILITY.md)，清单见 [manifest.json](third_party/Il2CppInterop/manifest.json)。

| 文件 | 状态 | SHA-256 |
| --- | --- | --- |
| `Il2CppInterop.Runtime.dll` | 原版 | `65ab051a681c2c1e52df7596ff738be401aae72cff882ff18241cf54a3ea38a4` |
| `Il2CppInterop.Runtime.dll` | 修补版 | `9bd74dc51718bfb4ba7b92d36db6104d651d7083adca9d6dd378847eb74f0bcb` |
| `Il2CppInterop.HarmonySupport.dll` | 原版 | `f7612ea2e5a4d473b771f34ee3b20cf32dc0c4ecea0185416474999a17fbcc07` |
| `Il2CppInterop.HarmonySupport.dll` | 修补版 | `bd77755f1525cb46fc408e2f2ac3df962e657c82dd01feac6a48f08bf3c754d8` |

### 翻译基线

- [AbyssMod](https://github.com/s88037zz/AbyssMod)：`1.2.0`（提交 `88357b9757414cc2a07913be90a6f7b2c3f28d08`），提取上游发布包的 `Utility.dll` 和 `TTCuYuanJ` 字体。
- [繁体译文](https://github.com/s88037zz/dotabyss-translation)：基线提交 `028834fe5f6801cfde54270b1419355168ae5a52`，安装信息记录于 `artifacts/translation/installed.json`。
- 包含 1,029 个 JSON（1 份清单、1,028 份字典，含 887 份剧情字典），共 52,003 条记录。
- 通用补译覆盖 20 份教程资源中的 233 段文本，以及技能、菜单、任务、商店等界面词条。

### 内容快照

| 常驻模式 | 主表记录 |
| --- | --- |
| 深渊 | 1 个地图、150 层、706 个格子模板、157 个战斗定义 |
| 厄灾 | 36 个等级、11 个 Boss、269 个战斗定义 |
| 训练中心 | 9 个教学、15 个回想挑战、1 个试打 |
| 普通遭遇战 | 527 个关卡定义、31,129 行掉落记录 |
| 势力战 | 5 个阵营，各 70 关 |
| 常驻外传 | 1 篇《白き焔の継承者》，8 个剧情节点、4 场战斗 |

| 活动类型 | 主表记录 |
| --- | --- |
| 采矿 | 5 期、35 关 |
| 凶化厄灾 | 2 期、10 关 |
| 剧情活动 | 6 期、144 节点（96 场战斗） |
| 寻宝棋盘 | 1 期、12 种 25 格模板 |
| 狩猎 | 4 期、56 关 |
| 箱池 | 3 期、32 个箱模板 |
| 委托 | 5 期、50 关 |
| 养成 | 3 期、13 节点（10 场战斗） |
| 竞速 | 1 期、9 关 |

合计 30 个活动配置，另有 18 期遭遇活动及 67 个奖励关战场定义。活动任务共 236 条（208 条限时任务、28 条限时日任务）。
