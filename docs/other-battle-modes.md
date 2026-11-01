# 其他常驻战斗模式

涵盖深渊、独立厄灾、训练中心、普通遭遇战、势力战与常驻外传。主线见 [主线战斗与教程](main-story-battle.md)，活动玩法见 [活动与本地复刻](events-and-reruns.md)，各模式关卡数量见 [内容快照](../changelog.md#内容快照)。

[返回文档目录](README.md)

## 已实现模式与流程

| 模式 | 支持流程 |
| --- | --- |
| 深渊 | 入场、队伍快照冻结、移动、战斗、代码选择、事件、商店、保管、跳层、球盘、归还与结算 |
| 厄灾 | 四槽刷新、巡逻、召唤、设施布阵、燃料消耗、战斗、当日扫荡、普通与特殊 Boss 推进 |
| 训练中心 | 解锁、已读标记、进入、胜利或退出、首通奖励、达标免打领取、最高伤害记录 |
| 普通遭遇战 | 随派遣时间触发、到期管理、补给与购买、开战、结算、已通关类型扫荡 |
| 势力战 | 按星期轮换开放、每日挑战次数、逐关推进、首通奖励、已通关层周回 |
| 常驻外传 | 剧情顺序阅读与战斗、回看、首领奖励、重复挑战与扫荡、通关次数统计 |

## 核心机制说明

- **深渊（Nether）**：
  - 角色技能通过 `m_abilities` 与突破觉醒层解析；代码的战斗效果与分类技能由客户端应用，侵蚀、结算与球盘解锁由服务端处理。
  - 检查点入场校验历史通关层数与研究树节点；每段按投入门票数计算积分倍率，秘密藏宝格在满足路径与侵蚀条件时揭示。
- **宝箱遭遇层**：
  - 采用三档计时标准：`S`（120 秒，`BoxGold`）、`A`（180 秒，`BoxSilver`）、`B`（无时限，`BoxBronze`），扫荡默认按最高档结算。
- **势力战与常驻外传**：
  - 势力战同阵营 3/5/10 人编队增益由客户端自动应用；每日开放按自然日星期判定（`0` 为周日）。
  - 常驻外传（`quest_type=8`）前 11 节为剧情与首通战斗，第 12 节为终章周回关（首次通关后支持扫荡，单次消耗 40 体力）。
- **刷新时间**：每日补给与厄灾刷新统一按日本时间 **05:00**（北京时间 04:00）结算。

## 可配置本地规则

可在数据目录的 `gameplay-rules.json` 中调整各模式数值参数：

| 配置项 | 默认值 | 说明 |
| --- | ---: | --- |
| `nether_free_entries_per_day` | 1 | 深渊每日免费入场次数 |
| `nether_initial_code_limit` | 8 | 深渊初始代码容量 |
| `nether_initial_code_reloads` | 1 | 深渊初始代码重抽次数 |
| `nether_starting_gold` | 100 | 深渊初始局内金币 |
| `nether_score_per_floor` | 100 | 深渊每层基础结算分数 |
| `nether_score_multiplier_per_extra_ticket` | 1 | 每张额外门票增加的本段积分倍率（`0` 为关闭） |
| `nether_points_per_code` | 1 | 每个代码结算点数 |
| `nether_random_drop_probability_per_mille` | 300 | 深渊素材掉落概率（千分比） |
| `encounter_daily_supply` | 3 | 每日遭遇战挑战补给次数 |
| `encounter_daily_recoveries` | 3 | 每日遭遇补给可购买次数 |
| `encounter_recovery_cost` | 50 | 每次购买遭遇补给消耗的钻石 |
| `union_daily_attempts` | 3 | 势力战每阵营每日挑战次数 |
| `disaster_free_summons_per_day` | 5 | 厄灾每日免费召唤额度 |
| `disaster_patrol_default_level` | 1 | 默认巡逻等级 |
| `battle_treasure_s_seconds` / `battle_treasure_a_seconds` | 120 / 180 | 宝箱遭遇 S / A 档计时秒数 |
| `battle_treasure_b_drops` / `battle_treasure_a_drops` / `battle_treasure_s_drops` | 1 / 2 / 3 | 宝箱遭遇 B / A / S 各档掉落数量 |
