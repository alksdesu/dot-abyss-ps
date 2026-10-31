import copy
from datetime import timedelta

import pytest

from dotabyss_ps.admin_actions_common import arguments
from dotabyss_ps.admin_actions_missions import ACTIONS, mission_scope
from dotabyss_ps.gameplay import Gameplay
from dotabyss_ps.gameplay_catalog import GameplayCatalog, GameplayError, available
from dotabyss_ps.gameplay_mission_controls import open_days
from dotabyss_ps.gameplay_missions import Missions
from dotabyss_ps.gameplay_records import find, put, rows
from dotabyss_ps.gameplay_rules import load_rules
from dotabyss_ps.newgame import build_initial_state
from test_gameplay import NOW, gameplay_master


@pytest.fixture
def game(gameplay_master):
    schema, tables = gameplay_master
    state = build_initial_state(tables, schema, 7, "Mission editor", "2026-10-31 00:00:00", start_tutorial=False)
    current = Gameplay(state, {}, GameplayCatalog(tables, schema), 7, NOW, load_rules())
    current.prepare()
    return current


def action(game, name, **values):
    definition, handler = next(row for row in ACTIONS if row[0]["id"] == name)
    return handler(game, arguments(definition, values))


def evaluator(game):
    return Missions(game.state, game.progress, game.catalog, game.now, game.user_id, game.rules)


def ordinary(game, identifier, *, kind=1, previous=0):
    row = copy.deepcopy(next(row for row in game.catalog.rows("m_missions")
                             if row["mission_type"] == 1 and not row["m_mission_pass_id"] and row["m_mission_reward_group_id"]))
    row.update(id=identifier, mission_type=kind, situation_type=40000, target_id=0, sub_target_id=0,
               require_value=9999, require_mission_id=previous, m_mission_pass_id=0, m_mission_term_id=0)
    game.catalog.tables["m_missions"][identifier] = row
    return row


def test_actions_are_independent_and_have_dynamic_group_sources():
    assert [spec["id"] for spec, _ in ACTIONS] == ["mission.open_days", "mission.complete", "mission.claim"]
    for spec, _ in ACTIONS[1:]:
        group = next(field for field in spec["fields"] if field["name"] == "group_id")
        assert group["source_by"]["field"] == "scope"
        assert group["source_by"]["values"]["special"] == "m_special_missions"


def test_special_days_completion_and_receiving_are_separate(game):
    current = evaluator(game)
    record, days = current.special(101)
    start = record["start_at"]
    last = next(row["m_mission_id"] for row in days if row["day"] == 7)
    with pytest.raises(GameplayError, match="未开放"):
        action(game, "mission.complete", scope="special", group_id=101, ids=[last])
    before = copy.deepcopy(game.state["records"])
    action(game, "mission.open_days", ids=[101])
    assert record["start_at"] == start and open_days(current, 101, record) == 7
    assert game.state["records"] == before
    result = action(game, "mission.complete", scope="special", group_id=101, all=True)
    assert result["changed_count"] == 59
    assert game.state["records"] == before and not game.progress["mission_claims"]
    assert all(current.completed(game.catalog.get("m_missions", row["m_mission_id"])) for row in days)
    result = action(game, "mission.claim", scope="special", group_id=101, all=True)
    assert result["changed_count"] == 59 and not record["completed_at"]
    after = copy.deepcopy(game.state["records"])
    assert action(game, "mission.claim", scope="special", group_id=101, all=True)["changed_count"] == 0
    assert game.state["records"] == after


def test_open_all_skips_unqualified_comeback_and_can_restore_days(game):
    result = action(game, "mission.open_days", all=True)
    assert result["changed_count"] == 1 and result["skipped"]["未开放或没有回归资格"] == 2
    assert find(game.state, "t_special_missions", m_special_mission_id=103) is None
    with pytest.raises(GameplayError, match="回归资格"):
        action(game, "mission.open_days", ids=[103])
    action(game, "mission.open_days", ids=[101], all_days=False, days=0)
    assert open_days(evaluator(game), 101) == 1


def test_ordinary_claims_follow_prerequisites_and_do_not_change_characters(game):
    first = ordinary(game, 990000001)
    second = ordinary(game, 990000002, previous=first["id"])
    before = copy.deepcopy(rows(game.state, "t_characters"))
    action(game, "mission.complete", scope="achievement", ids=[second["id"], first["id"]])
    assert rows(game.state, "t_characters") == before
    assert not game.progress["mission_claims"]
    result = action(game, "mission.claim", scope="achievement", ids=[second["id"], first["id"]])
    assert result["changed_count"] == 2
    assert evaluator(game).key(first) in game.progress["mission_claims"]
    assert evaluator(game).key(second) in game.progress["mission_claims"]


def test_completion_clear_and_daily_reset_do_not_touch_receipts(game):
    mission = ordinary(game, 990000003, kind=2)
    action(game, "mission.complete", scope="daily", ids=[mission["id"]])
    assert evaluator(game).completed(mission)
    action(game, "mission.complete", scope="daily", ids=[mission["id"]], completed=False)
    assert not evaluator(game).completed(mission)
    action(game, "mission.complete", scope="daily", ids=[mission["id"]])
    game.now += timedelta(days=1)
    assert not evaluator(game).completed(mission)
    assert not game.progress["mission_claims"]


def test_explicit_wrong_scope_and_expired_task_are_rejected(game):
    mission = ordinary(game, 990000004)
    with pytest.raises(GameplayError, match="不属于"):
        action(game, "mission.complete", scope="daily", ids=[mission["id"]])
    with pytest.raises(GameplayError, match="不能同时"):
        action(game, "mission.complete", scope="ordinary", ids=[mission["id"]], all=True)
    with pytest.raises(GameplayError, match="分组编号"):
        action(game, "mission.complete", scope="ordinary", group_id=101, ids=[mission["id"]])


def test_pass_completion_uses_independent_period_and_normal_point_award(game):
    definitions = [row for row in game.catalog.rows("m_mission_passes") if available(row, game.now)]
    identifier = definitions[0]["id"]
    scope = mission_scope(game, "pass", identifier)
    mission = next(row for row in scope.definitions if not row["require_mission_id"] and scope.evaluator.active(row))
    from dotabyss_ps.gameplay_pass_state import pass_state

    points = pass_state(game.progress, identifier)["points"]
    action(game, "mission.complete", scope="pass", group_id=identifier, ids=[mission["id"]])
    assert scope.evaluator.completed(mission)
    assert pass_state(game.progress, identifier)["points"] == points
    action(game, "mission.claim", scope="pass", group_id=identifier, ids=[mission["id"]])
    assert pass_state(game.progress, identifier)["points"] > points


def test_event_requires_participation_and_reset_does_not_reuse_completion(game):
    from dotabyss_ps.gameplay_events import event_data, join

    with pytest.raises(GameplayError, match="Join"):
        action(game, "mission.complete", scope="event", group_id=300001, all=True)
    event = game.catalog.get("m_events", 300001)
    put(game.state, "t_feature_locks", {"m_feature_lock_id": 1000 + event["type"]}, {"is_unlocked": 1})
    join(game, {"m_event_id": 300001})
    scope = mission_scope(game, "event", 300001)
    mission = next(row for row in scope.definitions if row["situation_type"] in (110000, 110001, 110002, 110003, 110004))
    action(game, "mission.complete", scope="event", group_id=300001, ids=[mission["id"]])
    assert scope.evaluator.completed(mission)
    event_data(game, 300001)["epoch"] += 1
    assert not scope.evaluator.completed(mission)


def test_campaign_requires_current_participation(game):
    definition = game.catalog.rows("m_encounter_campaigns")[0]
    with pytest.raises(GameplayError, match="选择并参加"):
        action(game, "mission.complete", scope="campaign", group_id=definition["id"], all=True)


def test_campaign_and_visitor_rewards_use_their_normal_scopes(game):
    from dotabyss_ps.gameplay_encounter_campaign import join

    for feature in (2, 1009):
        put(game.state, "t_feature_locks", {"m_feature_lock_id": feature}, {"is_unlocked": 1})
    join(game, {"m_encounter_campaign_id": 10000})
    scope = mission_scope(game, "campaign", 10000)
    mission = scope.definitions[0]
    action(game, "mission.complete", scope="campaign", group_id=10000, ids=[mission["id"]])
    assert scope.evaluator.completed(mission)
    action(game, "mission.claim", scope="campaign", group_id=10000, ids=[mission["id"]])
    assert scope.evaluator.key(mission) in game.progress["mission_claims"]
    relation = game.catalog.rows("m_visitor_missions")[0]
    visitor = relation["m_visitor_id"]
    put(game.state, "t_visitors", {"m_visitor_id": visitor}, {"is_temporary": 0}, game.user_id)
    mission_id = relation["m_mission_id"]
    for entry in game.catalog.rows("m_visitor_missions"):
        if entry["m_visitor_id"] == visitor and entry["m_mission_id"] not in game.catalog.tables["m_missions"]:
            ordinary(game, entry["m_mission_id"])
    action(game, "mission.complete", scope="visitor", group_id=visitor, ids=[mission_id])
    action(game, "mission.claim", scope="visitor", group_id=visitor, ids=[mission_id])
    assert evaluator(game).key(game.catalog.get("m_missions", mission_id)) in game.progress["mission_claims"]


def test_all_claims_skip_unfinished_missions_without_granting_them(game):
    mission = ordinary(game, 990000005, kind=3)
    result = action(game, "mission.claim", scope="weekly", all=True)
    assert result["skipped"]["条件或领奖前置未完成"]
    assert evaluator(game).key(mission) not in game.progress["mission_claims"]


def test_plan_claiming_advances_each_step_and_visitor_requires_entry(game):
    from dotabyss_ps.gameplay_plans import plan_steps

    groups = {}
    for step in game.catalog.rows("m_plan_steps"):
        groups.setdefault(step["m_plan_id"], []).append(step)
    identifier = next(key for key, values in groups.items() if len(values) >= 2)
    record = put(game.state, "t_plans", {"m_plan_id": identifier}, {"step": 0}, game.user_id)
    _, steps = plan_steps(game, identifier)
    selected = [row["m_mission_id"] for row in steps[:2]]
    previous = game.catalog.get("m_missions", selected[0])["require_mission_id"]
    if previous:
        game.progress["mission_claims"][evaluator(game).key(game.catalog.get("m_missions", previous))] = []
    action(game, "mission.complete", scope="plan", group_id=identifier, ids=selected)
    action(game, "mission.claim", scope="plan", group_id=identifier, ids=list(reversed(selected)))
    assert record["step"] == 2
    visitor = game.catalog.rows("m_visitors")[0]["id"]
    with pytest.raises(GameplayError, match="Visitor"):
        action(game, "mission.complete", scope="visitor", group_id=visitor, all=True)


def test_nether_loop_completion_only_claims_one_iteration(game):
    from dotabyss_ps.gameplay_nether_state import state

    put(game.state, "t_feature_locks", {"m_feature_lock_id": 5}, {"is_unlocked": 1})
    scope = mission_scope(game, "nether", 0)
    mission = next(row for row in scope.definitions if row["mission_type"] == 9 and row["situation_type"] == 130000)
    action(game, "mission.complete", scope="nether", ids=[mission["id"]])
    action(game, "mission.claim", scope="nether", ids=[mission["id"]])
    assert state(game)["ticket_claims"][str(mission["id"])] == 1
    with pytest.raises(GameplayError, match="未完成"):
        action(game, "mission.claim", scope="nether", ids=[mission["id"]])
    assert state(game)["ticket_claims"][str(mission["id"])] == 1
