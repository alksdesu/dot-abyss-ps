# 新档与教程策略

新建存档使用本地初始化规则并保存在数据目录的 SQLite 数据库中。PC 新档默认从序章教程开始；已有存档保留进度。首次环境配置见 [PC 首次启动](first-start.md)，日常玩法规则见 [养成、奖励与解锁](progression-and-rewards.md)。

## 客户端与版本绑定

支持项同时绑定包名、版本与元数据 SHA-256（定义于 [newgame.py](../server/dotabyss_ps/newgame.py) 的 `SUPPORTED_CLIENTS`）。主数据、结构描述与存档按客户端类型（PC / Google Play / FANZA）隔离，不同客户端使用各自独立的数据目录与服务端口。

## 新档与序章引导

在控制台新建 PC 存档时，基础记录、玩法进度、显示名称与创建回执在同一事务中写入。新档默认启用 `guided` 引导模式：

- 序章状态从 `0` 开始，按原生流程推进至 `13` 后转为完成状态 `99`。
- 初始关闭常驻功能自动解锁、探索队自动派遣和全地图自动开放；主线编队与探索队各从 1 支开始（仅作用于该存档的规则配置，不影响全局 `gameplay-rules.json`）。
- 两场序章教学战使用固定队伍且不扣体力，教学抽卡确认后继续推进。
- 功能教程奖励读取 `m_tutorial_rewards`：直接奖励写入库存，间接奖励发往礼物箱。

## 初始数据基线

`build_initial_state` 读取 12 张基础主表生成初始存档数据：

| 内容 | 初始化规则 |
| --- | --- |
| 角色 | 按 `m_initial_contents` 类型 `40` 创建（初始 1 级，支持 `intimacy_point` 种子配置） |
| 角色服装 | 发放每位初始角色的默认战斗服装与酒馆服装 |
| 武器外观 | 发放各武器类型对应的免费默认外观 |
| 魔晶石、称号 | 按初始内容类型 `60`、`190` 创建 |
| 开发计划 | 类型 `131`；`t_plans.step` 记录已完成步数（初始为 `0`） |
| 设施 | 创建 `100`、`200`、`300`、`500`、`1000` 设施（初始 1 级） |
| 玩家资料 | 初始 1 级，默认展示第一位角色与第一枚称号 |
| 容量 | 初始装备容量 `100`，基础最大编队数 `1` |
| 酒馆 | 创建初始每日卡片空记录 |
| 探索队 | 创建初始未派遣状态（等级 `1`、积分 `0`、基础探索上限 `43200` 秒） |

开档首次补给由 `gameplay-rules.json` 中的 `starting_gold`、`starting_character_exp`、`starting_soul`、`starting_free_currency` 等配置决定（常规补给发往礼物箱，Soul 直接结算入账）。

## 登录与主页同步

PC 登录与进主页请求通过 `Gameplay.visit` 同步体力、有效规则、解锁状态与奖励回执：

- `/api/user`：返回持有记录与背包容量。
- `/api/home`：返回主页看板问候、访客、推荐商品与待领奖标记。
- `/api/mypage/login`：结算每日登录奖励、订阅奖励、好友点、限时道具到期转换与商店刷新。

## 旧编队空位清理

若早期存档在 `t_exploration_party_characters` 中残留了角色 ID 为 `0` 的空占位行，可执行以下命令预览并清理（先加载 [维护命令参数](../changelog.md#维护命令参数) 变量块）：

```powershell
.\.venv\Scripts\python.exe -m dotabyss_ps.party_migration --data-dir $dataDirectory --profile '<内部存档标识>'
.\.venv\Scripts\python.exe -m dotabyss_ps.party_migration --data-dir $dataDirectory --profile '<内部存档标识>' --apply
```

源码入口：[初始化与校验](../server/dotabyss_ps/newgame.py)、[教程规则](../server/dotabyss_ps/gameplay_tutorial.py)、[编队清理](../server/dotabyss_ps/party_migration.py)。返回 [文档目录](README.md)。
