# 更新与适配记录

这里集中记录客户端版本、验证环境、内容快照和适配日期。日期指本项目的记录日期，不是游戏官方发布日期；玩法范围与使用方法见 [文档目录](docs/README.md)。

## 2026-11-01

### 客户端支持

| 客户端 | 版本 | 支持范围 | 结构描述 |
| --- | --- | --- | --- |
| Windows x64 PC，`dotabyss_x_cl` | **1.15.0** | 主要适配目标；常驻养成、主线与教程、战斗模式、活动、启动器和管理功能；仍需持续实机验收 | [PC schema](artifacts/master-schema-pc-1.15.0.json) |
| Android Google Play，`com.exnoa.abyss` | 1.15.0 | 历史基础协议与主数据兼容，不代表完整游戏流程可用 | [Play schema](artifacts/master-schema-play-1.15.0.json) |
| Android FANZA MOD，`jp.co.fanzagames.dotabyss_x_a.mod` | 1.14.4 | 历史协议诊断；资源、自然登录及主页流程未完成 | [FANZA schema](artifacts/master-schema-fanza-1.14.4.json) |

PC release 标识为 `pc-1.15.0-d38f026a`，定义在 [统一版本清单](pc/releases/manifest.json)；[release 示例](pc/releases/pc-1.15.0.example.json) 是自动生成的旧格式投影。对应 metadata SHA-256 为 `d38f026a769e522b136830785ad2789f834c47127be764f89ab294b4d91f056d`。版本字符串相同仍需通过文件、schema 和主数据指纹校验。

### 更新内容

- 集中适配版本、运行环境和维护命令参数，使用文档不再重复固定版本值。
- 统一版本清单分开保存客户端结构与内容快照；Python 直接解析，旧格式投影与 C# 结构常量自动生成。
- 插件不再固定主数据或 catalog 内容哈希，改为校验运行时内容关联及固定结构契约；安装器复用匹配的构建输入记录，内容更新可跳过编译。
- 安装、启动器、翻译准备和资源导入统一读取路径与隔离身份；旧存档跨主数据仍需另行处理，不自动迁移。
- 内容选择器单选立即回填并关闭，多选保留确认操作，短窗口下底部按钮可见。
- 内置条款与版本启动接口，修复干净安装缺少 fixtures 时的 `terms/fetch` 等 4040。
- 首装自动准备配置、catalog 索引和资源映射；角色收藏保存完整选择。
- 任务开放天数、批量完成和领奖分别操作；日常与周期统计对齐重置时间。
- 已购一次性推荐礼包重复请求不再重复扣费、发奖或返回购买次数错误。

以上为本次更新与归档摘要，不代表所有功能首次在这一天完成，也不包含本地尚未提交的背景兼容草稿。

### 运行与构建环境

| 项目 | 记录值与用途 |
| --- | --- |
| Python | `>=3.11`，以 [pyproject.toml](pyproject.toml) 为准 |
| PC Unity | `6000.3.8f1` |
| PC BepInEx | `6.0.0-be.791+b782da4`，IL2CPP Windows x64；[对应构建下载](https://builds.bepinex.dev/projects/bepinex_be/791) |
| PC Il2CppInterop | `1.5.3.0`；还须核对下方文件指纹 |
| 随 PC 加载器的 .NET 运行时 | `6.0.7`，与开发用 SDK 不是同一项 |
| PC 插件目标框架 | `net6.0`；引用目标客户端自身的 core 与 interop 编译 |
| 兼容库构建 SDK | `8.0.0`，`rollForward=latestFeature`；以 [global.json](third_party/Il2CppInterop/global.json) 为准 |
| 兼容库输出目录 | `third_party/Il2CppInterop/bin/Il2CppInterop.Runtime/net6.0/`、`third_party/Il2CppInterop/bin/Il2CppInterop.HarmonySupport/net6.0/` |
| catalog 格式 | Addressables 二进制 catalog v2；解析依据为 [Unity Addressables 2.7.4 源包](https://download.packages.unity.com/com.unity.addressables/-/com.unity.addressables-2.7.4.tgz) |
| 历史 Android 环境 | LemonLoader / MelonLoader `0.7.4`；原环境记录为 .NET `10/11`，当前适配器构建目标为 `net10.0`；仅限诊断 |

### 维护命令参数

普通首装使用 `setup-pc.ps1`，不需要手工复制这些值。下方变量用于文档中的独立维护命令：在仓库根目录的 PowerShell 中执行，并继续使用同一个窗口。已有自定义安装应把 `$dataDirectory` 换成自己的数据目录；更换 schema 或客户端前必须先完成匹配验证，不能只改版本字符串。

```powershell
$releaseManifest = Get-Content -LiteralPath '.\pc\releases\manifest.json' -Raw | ConvertFrom-Json
$releaseProfile = $releaseManifest.releases.PSObject.Properties[$releaseManifest.default_release].Value
$dataDirectory = Join-Path $PWD.Path $releaseProfile.paths.data_directory
$schemaPath = Join-Path $PWD.Path $releaseProfile.build.schema.path
$catalogRelativePath = $releaseProfile.build.transport.catalog_path
$catalogHashRelativePath = $releaseProfile.build.transport.catalog_hash_path
```

默认本机 release 配置是 `pc/releases/pc-1.15.0.json`，未生成时使用同目录的 `.example.json`。资源索引和缺失报告位于数据目录的 `setup/`。上面的 catalog 路径是客户端固定请求路径；本地缓存可能叫 `1791059991.bin` 或 `catalogcached.bin`，文件名不同不代表应修改请求路径。

### 兼容库指纹

上游基线为 [BepInEx/Il2CppInterop](https://github.com/BepInEx/Il2CppInterop) 的提交 `dbda1cb353b0f4253345dc45136d170b9e50a5a0`。替换步骤见 [兼容说明](third_party/Il2CppInterop/COMPATIBILITY.md)，机器可读记录见 [manifest.json](third_party/Il2CppInterop/manifest.json)。

| 文件 | 状态 | SHA-256 |
| --- | --- | --- |
| `Il2CppInterop.Runtime.dll` | 原版 | `65ab051a681c2c1e52df7596ff738be401aae72cff882ff18241cf54a3ea38a4` |
| `Il2CppInterop.Runtime.dll` | 修补版 | `9bd74dc51718bfb4ba7b92d36db6104d651d7083adca9d6dd378847eb74f0bcb` |
| `Il2CppInterop.HarmonySupport.dll` | 原版 | `f7612ea2e5a4d473b771f34ee3b20cf32dc0c4ecea0185416474999a17fbcc07` |
| `Il2CppInterop.HarmonySupport.dll` | 修补版 | `bd77755f1525cb46fc408e2f2ac3df962e657c82dd01feac6a48f08bf3c754d8` |

### 翻译基线

- [AbyssMod](https://github.com/s88037zz/AbyssMod)：`1.2.0`，源码提交 `88357b9757414cc2a07913be90a6f7b2c3f28d08`。Utility.dll 和 TTCuYuanJ 字体取自上游 `v1.2.0` 发布包并校验 SHA-256。
- [繁体译文](https://github.com/s88037zz/dotabyss-translation)：本次归档基线提交 `028834fe5f6801cfde54270b1419355168ae5a52`。启动器更新译文后，实际批次以 `artifacts/translation/installed.json` 为准。
- 基线含 1,029 个 JSON：1 份清单、1,028 份字典，其中 887 份剧情字典；共 52,003 条记录，52,001 条非空，50,557 条与原文不同。统计不等同于翻译准确率或全游戏覆盖率。
- 通用补译包括 20 份教程资源中的 233 段文字，以及技能、菜单、任务、商店等文本。另有 21 套共 68 页帮助图片，需要单独重绘。
- 曾实机确认字体、主表翻译和剧情本地缓存加载；通用补译有合并、格式及构建检查，尚不能替代逐页面验收。

### 内容快照

下列数量归档自此次适配的主表检查记录，只描述当前快照，不是玩法代码应写死的上限。

| 常驻模式 | 主表记录 |
| --- | --- |
| 深渊 | 1 个地图、150 层、706 个格子模板、157 个战斗定义 |
| 厄灾 | 36 个等级、11 个 Boss、269 个战斗定义 |
| 训练中心 | 9 个教学、15 个回想挑战、1 个试打 |
| 普通遭遇战 | 527 个关卡定义；31,129 行掉落记录按关卡与行 ID 组合保留 |
| 势力战 | 5 个阵营，各 70 关 |
| 常驻外传 | 1 篇《白き焔の継承者》，8 个剧情节点、4 场战斗 |

| 活动类型 | 主表记录 |
| --- | --- |
| 采矿 | 5 期、35 关 |
| 凶化厄灾 | 2 期、10 关 |
| 剧情活动 | 6 期、144 节点，其中 96 场战斗 |
| 寻宝棋盘 | 1 期、12 种 25 格模板 |
| 狩猎 | 4 期、56 关 |
| 箱池 | 3 期、32 个箱模板 |
| 委托 | 5 期、50 关 |
| 养成 | 3 期、13 节点，其中 10 场战斗 |
| 竞速 | 1 期、9 关 |

合计 30 个活动配置，另有 18 期遭遇活动及 67 个奖励关战场定义。活动任务共 236 条：208 条限时任务、28 条限时日任务。本快照的遭遇活动混入普通地图概率、奖励关编队限制组均为零；未来出现非零规则仍需核对。活动 `600002` 的示例倍率为 `750`，消耗 40 体力时产生 30 枚基础活动币。

本机资源抽查记录：30 个活动背景配置中有 10 个预制体包缺失，对应同名图片已下载并通过大小与哈希验证；另有 7 处 `SE_DUMMY` 音效引用待确认原生容错。缺失预制体为 `abg11101a`、`abg20200b`、`abg14200a`、`abg20400a`、`abg20300a`、`abg11500a`、`Functionbg012`、`abg11200a`、`abg10100a`、`abg14900a`。这不是所有用户的必然缺失清单，也不表示本地背景兼容草稿已发布；以各自资源 manifest 和所安装代码为准。

### 存档策略记录

当前 `policy_version=5`，数据库 `game_states.schema_version=1`；前者是初始化与兼容策略，后者是记录格式。

| 策略迁移 | 处理内容 |
| --- | --- |
| `1 → 2` | 缺少序章记录时补入完成状态 `99`，保留有效原进度 |
| `2 → 3` | 仅在缺失时补入未开始的酒馆记录 |
| `3 → 4` | 仅在缺失时补入未派遣的探索队记录 |
| `4 → 5` | 按连续计划奖励回执，将“下一步”改为“已完成步数”，同步修正缓存响应 |

迁移默认目标是策略 `5`；`--to-policy` 还支持较早目标 `2`、`3`、`4`。跨入策略 `5` 必须提供匹配的 schema。这些是存档策略迁移，不是通用跨主数据版本迁移；命令与备份行为见 [新档与旧档兼容](docs/newgame-policy.md)。

### 历史诊断记录

Android 记录的 `app_version_code=1`、`bundle_version=0.1.0`、`Application.version=1.14.4` 是不同字段，客户端版本数组匹配最后一项。MuMu 中部分路由与平台初始化钩子已验证，原生 ARM64 真机未测试，完整登录与主页未通过。

最后的原生登录诊断仍为 `tuple_matches=false`、`passed=false`。后续 `(source:null, token:0)` 加结果字段复制的构建只通过 Release/Debug 各 55 项托管检查，未部署到设备；其 DLL SHA-256 为 `19AE81011D58797ED898E0BA7B5F2D9DD2F785424743677DA5D07180A5A2D452`。不能将构建成功写成原生登录成功。
