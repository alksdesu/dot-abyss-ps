from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .admin_actions_common import changed, choice, field, no_battle, selection_fields, spec
from .gameplay_catalog import GameplayError, available, identifiers, number
from .gameplay_mission_controls import clear_complete, mark_complete, open_days, set_open_days
from .gameplay_missions import Missions


@dataclass
class MissionScope:
    evaluator: object
    definitions: list
    receive: object
    eligible: object = lambda mission: True
    ready: object = lambda mission: True


def mission_scope(game, kind, group_id):
    from .gameplay_access import require_feature
    from .gameplay_campaign_missions import CampaignMissions
    from .gameplay_encounter_campaign import campaign_data
    from .gameplay_event_missions import EventMissions
    from .gameplay_events import require_event
    from .gameplay_nether_missions import NetherMissions, definitions as nether_definitions, mission_receive as nether_receive
    from .gameplay_pass import active_pass, mission_receive as pass_receive
    from .gameplay_plans import plan_receive, plan_steps, visitor_missions, visitor_receive

    evaluator = Missions(game.state, game.progress, game.catalog, game.now, game.user_id, game.rules)
    definitions = game.catalog.rows("m_missions")
    if kind in ("ordinary", "daily", "weekly", "achievement"):
        if group_id:
            raise GameplayError("普通任务的分组编号应为 0", 400, 4007)
        kinds = {"ordinary": {1, 2, 3}, "daily": {2}, "weekly": {3}, "achievement": {1}}[kind]
        nether = {row["id"] for row in nether_definitions(game)}
        selected = [row for row in definitions if row["mission_type"] in kinds and not row["m_mission_pass_id"] and row["id"] not in nether]
        return MissionScope(evaluator, selected, lambda ids: evaluator.receive(ids))
    if kind == "special":
        record, days = evaluator.special(number(group_id))
        by_mission = {row["m_mission_id"]: row["day"] for row in days}
        selected = [game.catalog.get("m_missions", identifier) for identifier in sorted(by_mission)]
        return MissionScope(evaluator, selected, lambda ids: evaluator.receive(ids, group_id),
                            lambda row: available(record, game.now) and by_mission[row["id"]] <= open_days(evaluator, group_id, record))
    if kind == "pass":
        active_pass(game, number(group_id))
        selected = [row for row in definitions if row["m_mission_pass_id"] == group_id]
        return MissionScope(evaluator, selected, lambda ids: pass_receive(game, {"m_mission_pass_id": group_id, "m_mission_ids": ids}))
    if kind == "event":
        evaluator = EventMissions(game, require_event(game, number(group_id), allow_closed=True))
        return MissionScope(evaluator, evaluator.definitions, lambda ids: evaluator.receive(ids, allowed_ids=evaluator.allowed_ids))
    if kind == "campaign":
        campaign = game.catalog.get("m_encounter_campaigns", number(group_id))
        if campaign_data(game)["current_id"] != group_id:
            raise GameplayError("请先在控制台选择并参加这个遭遇活动", 409, 4092)
        evaluator = CampaignMissions(game, campaign)
        return MissionScope(evaluator, evaluator.definitions, lambda ids: evaluator.receive(ids, allowed_ids=evaluator.allowed_ids))
    if kind == "nether":
        if group_id:
            raise GameplayError("深渊任务使用当前赛季，分组编号应为 0", 400, 4007)
        require_feature(game, 5)
        evaluator = NetherMissions(game)
        return MissionScope(evaluator, nether_definitions(game), lambda ids: nether_receive(game, {"m_mission_ids": ids}))
    if kind == "plan":
        record, steps = plan_steps(game, number(group_id))
        by_mission = {row["m_mission_id"]: row["step"] for row in steps}
        selected = [game.catalog.get("m_missions", identifier) for identifier in sorted(by_mission)]
        return MissionScope(evaluator, selected, lambda ids: plan_receive(game, {"m_plan_id": group_id, "m_mission_ids": ids}),
                            ready=lambda row: by_mission[row["id"]] <= record["step"] + 1)
    if kind == "visitor":
        allowed = visitor_missions(game, number(group_id))
        selected = [game.catalog.get("m_missions", identifier) for identifier in sorted(allowed)]
        return MissionScope(evaluator, selected, lambda ids: visitor_receive(game, {"m_visitor_id": group_id, "m_mission_ids": ids}))
    raise GameplayError("不支持的任务类别", 400, 4007)


def _selection(scope, args):
    by_id = {row["id"]: row for row in scope.definitions}
    requested = identifiers(args["ids"], 10000)
    if args["all"]:
        if requested:
            raise GameplayError("全选与指定任务不能同时使用", 400, 4007)
        requested = sorted(by_id)
    if not requested:
        raise GameplayError("请选择任务；当前分组可能没有任务", 400, 4007)
    if set(requested) - by_id.keys():
        raise GameplayError("所选任务不属于当前类别或分组", 400, 4007)
    selected, skipped = [], Counter()
    for identifier in requested:
        row = by_id[identifier]
        if not scope.evaluator.active(row) or not scope.eligible(row):
            if not args["all"]:
                raise GameplayError("所选任务未开放、已到期或尚未取得资格：" + str(identifier), 409, 4092)
            skipped["未开放或已到期"] += 1
        else:
            selected.append(row)
    return selected, skipped


def _received(scope, mission):
    if mission["mission_type"] == 9 and mission["situation_type"] == 130000:
        return False
    return scope.evaluator.key(mission) in scope.evaluator.progress["mission_claims"]


def _summary(label, count, skipped):
    warnings = ["跳过" + "、".join(f"{reason} {amount} 项" for reason, amount in skipped.items()) + "。"] if skipped else []
    return {**changed(label, count, timing="page", warnings=warnings), "changed_count": count, "skipped": dict(skipped)}


def open_special_days(game, args):
    no_battle(game)
    selected = identifiers(args["ids"], 10000)
    if args["all"]:
        if selected:
            raise GameplayError("全选与指定任务组不能同时使用", 400, 4007)
        selected = sorted(row["id"] for row in game.catalog.rows("m_special_missions"))
    if not selected:
        raise GameplayError("请选择特殊任务组", 400, 4007)
    evaluator = Missions(game.state, game.progress, game.catalog, game.now, game.user_id, game.rules)
    prepared, skipped = [], Counter()
    from .gameplay_comeback import special_window

    for identifier in selected:
        definition = game.catalog.get("m_special_missions", identifier)
        if not available(definition, game.now) or not special_window(evaluator, identifier)[0]:
            if not args["all"]:
                raise GameplayError("任务组未开放或没有回归资格：" + str(identifier), 409, 4092)
            skipped["未开放或没有回归资格"] += 1
            continue
        record, days = evaluator.special(identifier)
        if not available(record, game.now):
            if not args["all"]:
                raise GameplayError("任务组领取期限已结束：" + str(identifier), 409, 4092)
            skipped["领取期限已结束"] += 1
            continue
        maximum = max((row["day"] for row in days), default=0)
        target = maximum if args["all_days"] else number(args["days"], 0, maximum)
        prepared.append((identifier, target))
    for identifier, target in prepared:
        set_open_days(evaluator, identifier, target)
    return _summary("已调整任务开放天数，任务条件和已领奖励保留", len(prepared), skipped)


def complete_missions(game, args):
    no_battle(game)
    scope = mission_scope(game, args["scope"], args["group_id"])
    selected, skipped = _selection(scope, args)
    count = 0
    for mission in selected:
        if _received(scope, mission):
            skipped["已经领取"] += 1
            continue
        changed_value = mark_complete(scope.evaluator, mission) if args["completed"] else clear_complete(scope.evaluator, mission)
        count += int(changed_value)
        if not changed_value:
            skipped["无需修改"] += 1
    return _summary("已设置任务完成状态，未发放奖励" if args["completed"] else "已恢复任务的正常完成判定", count, skipped)


def claim_missions(game, args):
    no_battle(game)
    scope = mission_scope(game, args["scope"], args["group_id"])
    selected, skipped = _selection(scope, args)
    pending = []
    for mission in selected:
        if _received(scope, mission):
            skipped["已经领取"] += 1
        else:
            pending.append(mission)
    count = 0
    while pending:
        advanced = False
        for mission in list(pending):
            if not scope.ready(mission) or not scope.evaluator.prerequisites(mission) or not scope.evaluator.completed(mission):
                continue
            scope.receive([mission["id"]])
            pending.remove(mission)
            count += 1
            advanced = True
        if not advanced:
            if not args["all"]:
                raise GameplayError("所选任务或领奖前置尚未完成：" + ",".join(str(row["id"]) for row in pending[:20]), 409, 4092)
            skipped["条件或领奖前置未完成"] += len(pending)
            break
    return _summary("已领取可领取的任务奖励", count, skipped)


SCOPE_CHOICES = [("ordinary", "普通任务（全部）"), ("daily", "每日任务"), ("weekly", "每周任务"),
                 ("achievement", "成就任务"), ("special", "新手／游戏祭／回归任务"), ("pass", "通行证任务"),
                 ("event", "活动任务"), ("campaign", "遭遇活动任务"), ("nether", "深渊任务"),
                 ("plan", "开发计划任务"), ("visitor", "访客任务")]
GROUP_SOURCES = {"special": "m_special_missions", "pass": "m_mission_passes", "event": "m_events",
                 "campaign": "m_encounter_campaigns", "plan": "m_plans", "visitor": "m_visitors"}


def _mission_fields():
    return [choice("scope", "任务类别", SCOPE_CHOICES, default="special"),
            field("group_id", "任务组（普通／深渊填 0）", default=0, source_by={"field": "scope", "values": GROUP_SOURCES}),
            field("ids", "选择任务", "ids", required=False, default=[], source="m_missions"),
            field("all", "选择本类别和分组全部有效任务", "boolean", default=False)]


ACTIONS = [
    (spec("mission.open_days", "mission", "开放特殊任务天数", [*selection_fields("m_special_missions"),
          field("all_days", "开放全部天数", "boolean", default=True), field("days", "开放至第几天（0 恢复自然）", default=0, max=3650)],
          description="保留原七日分页、任务要求与领奖凭证；没有回归资格的任务组不会开放。", timing="page"), open_special_days),
    (spec("mission.complete", "mission", "批量设置任务完成状态", [*_mission_fields(), field("completed", "标记为可领取", "boolean", default=True)],
          description="仅作用于当前有效周期，不改角色或关卡数值、不发奖；关闭开关恢复自然判定。领奖前置仍需完成。", timing="page"), complete_missions),
    (spec("mission.claim", "mission", "领取所选或本组全部可领任务奖励", _mission_fields(),
          description="按正常资格与前置领取，已领不重发；全选会跳过未完成项。特殊任务总奖励仍使用独立总奖励操作。", timing="page"), claim_missions),
]
