import copy
import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from dotabyss_ps import gameplay_missions, gameplay_plans
from dotabyss_ps.gameplay_catalog import GameplayError, JST
from dotabyss_ps.gameplay_campaign_missions import CampaignMissions
from dotabyss_ps.gameplay_event_missions import EventMissions
from dotabyss_ps.gameplay_mission_calendar import elapsed_days
from dotabyss_ps.gameplay_mission_controls import (
    clear_complete, mark_complete, open_days, project_special_records, set_open_days, validate_controls,
)
from dotabyss_ps.gameplay_missions import Missions


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=JST)


def mission(identifier=1, kind=1, **values):
    return {"id": identifier, "mission_type": kind, "situation_type": 40000, "require_value": 3,
            "require_mission_id": 0, "m_mission_pass_id": 0, "m_mission_term_id": 0,
            "target_id": 0, "sub_target_id": 0, "mission_group_id": 0, "display_order": identifier,
            "m_mission_reward_group_id": identifier, **values}


@pytest.fixture
def context():
    missions = [mission(1010 + day, 7) for day in range(1, 8)]
    tables = {
        "m_missions": missions,
        "m_special_missions": [{"id": 101, "start_at": "2020-01-01 00:00:00", "end_at": "2030-01-01 00:00:00", "valid_day": 0}],
        "m_special_mission_days": [{"id": day, "day": day, "m_special_mission_id": 101, "m_mission_id": 1010 + day} for day in range(1, 8)],
        "m_mission_rewards": [{"id": item["id"], "group_id": item["id"], "content_type": 50, "content_id": 0, "amount": 10} for item in missions],
        "m_mission_terms": [],
    }
    catalog = SimpleNamespace(tables=tables, rows=lambda name: tables.get(name, []),
                              get=lambda name, identifier: next(row for row in tables[name] if row["id"] == identifier))
    state = {"records": {"t_special_missions": {"up": [], "down": []}, "t_characters": {"up": [{"id": 1}], "down": []}}}
    progress = {"features": {}, "mission_claims": {}, "login_days": []}
    return SimpleNamespace(state=state, progress=progress, catalog=catalog, now=stamp("2026-11-01T06:00:00"),
                           user_id=4, rules={"event_open_all": 1}, tables=tables)


def evaluator(game):
    return Missions(game.state, game.progress, game.catalog, game.now, game.user_id, game.rules)


def ordinary(context, **values):
    item = mission(**values)
    context.tables["m_missions"] = [item]
    return item


def test_special_days_follow_five_am_and_receive_agrees(context, monkeypatch):
    g = context
    start = evaluator(g)
    record, _ = start.special(101)
    second = g.tables["m_missions"][1]
    assert mark_complete(start, second)
    g.now = stamp("2026-11-02T04:59:59")
    current = evaluator(g)
    assert open_days(current, 101) == 1
    with pytest.raises(GameplayError, match="day is locked"):
        current.receive([second["id"]], 101)
    g.now += timedelta(seconds=1)
    current = evaluator(g)
    assert open_days(current, 101) == 2
    given = []
    monkeypatch.setattr(gameplay_missions, "deliver", lambda _, rewards: given.extend(rewards))
    current.receive([second["id"]], 101)
    current.receive([second["id"]], 101)
    assert given == [{"content_type": 50, "content_id": 0, "amount": 10}]
    assert record["start_at"] == "2026-11-01T06:00:00+09:00"


def test_open_days_project_only_client_start_and_leave_rewards_untouched(context):
    e = evaluator(context)
    record, _ = e.special(101)
    before = copy.deepcopy(context.state)
    assert set_open_days(e, 101, 7) == 7
    assert context.state == before and not context.progress["mission_claims"]
    assert not e.completed(context.tables["m_missions"][0])
    original = {"t_special_missions": {"up": [], "down": []}}
    result = project_special_records(e, original)
    view = result["t_special_missions"]["up"][0]
    assert elapsed_days(view["start_at"], e.now) == 7
    assert view["end_at"] == record["end_at"]
    assert original == {"t_special_missions": {"up": [], "down": []}}
    assert set_open_days(e, 101, 0) == 1
    assert project_special_records(e, original)["t_special_missions"]["up"][0] == record


def test_open_day_offset_survives_restart_and_advances_naturally(context):
    e = evaluator(context)
    e.special(101)
    assert set_open_days(e, 101, 3) == 3
    context.progress = json.loads(json.dumps(context.progress))
    context.now += timedelta(days=1)
    assert open_days(evaluator(context), 101) == 4
    context.now += timedelta(days=10)
    assert open_days(evaluator(context), 101) == 7


def test_new_special_participation_does_not_reuse_old_controls(context):
    e = evaluator(context)
    record, _ = e.special(101)
    set_open_days(e, 101, 7)
    item = context.tables["m_missions"][0]
    mark_complete(e, item)
    context.now += timedelta(days=3)
    record["start_at"] = context.now.isoformat()
    current = evaluator(context)
    assert open_days(current, 101) == 1
    assert not current.completed(item)
    assert project_special_records(current, {}) == {}


def test_special_completion_reward_still_waits_for_manual_claims(context, monkeypatch):
    context.tables["m_special_missions"][0]["complete_m_mission_reward_group_id"] = 999
    context.tables["m_mission_rewards"].append({"group_id": 999, "content_type": 50, "content_id": 0, "amount": 100})
    e = evaluator(context)
    record, _ = e.special(101)
    set_open_days(e, 101, 7)
    for item in context.tables["m_missions"]:
        mark_complete(e, item)
    with pytest.raises(GameplayError, match="must be claimed"):
        gameplay_plans.special_complete(context, {"m_special_mission_id": 101})
    assert record["completed_at"] == ""
    granted = []
    monkeypatch.setattr(gameplay_missions, "deliver", lambda _, rewards: granted.extend(rewards))
    monkeypatch.setattr(gameplay_plans, "deliver", lambda _, rewards: granted.extend(rewards))
    e.receive([item["id"] for item in context.tables["m_missions"]], 101)
    assert sum(reward["amount"] for reward in granted) == 70
    gameplay_plans.special_complete(context, {"m_special_mission_id": 101})
    gameplay_plans.special_complete(context, {"m_special_mission_id": 101})
    assert sum(reward["amount"] for reward in granted) == 170


def test_comeback_qualification_is_not_created_by_mission_controls(context):
    e = evaluator(context)
    e.special(101)
    set_open_days(e, 101, 7)
    context.tables["m_come_back_special_missions"] = [{"m_special_mission_id": 101, "m_come_back_id": 1}]
    context.tables["m_come_backs"] = [{"id": 1, "begin_at": "2020-01-01 00:00:00", "end_at": "2030-01-01 00:00:00"}]
    context.state["records"]["t_come_backs"] = {"up": [], "down": []}
    before = copy.deepcopy(context.progress)
    with pytest.raises(GameplayError, match="comeback"):
        set_open_days(e, 101, 7)
    with pytest.raises(GameplayError, match="participation"):
        mark_complete(e, context.tables["m_missions"][0])
    assert project_special_records(e, {}) == {}
    assert context.progress == before


@pytest.mark.parametrize("days", [-1, True, 8])
def test_invalid_open_day_does_not_modify_state(context, days):
    e = evaluator(context)
    e.special(101)
    before = copy.deepcopy(context.progress)
    with pytest.raises(GameplayError):
        set_open_days(e, 101, days)
    assert context.progress == before


def test_completion_changes_task_view_not_character_state_or_claims(context):
    item = ordinary(context)
    e = evaluator(context)
    before = copy.deepcopy(context.state)
    assert e.value(item) == 1 and not e.completed(item)
    assert mark_complete(e, item)
    assert e.value(item) == 1 and e.effective_value(item) == 3 and e.completed(item)
    assert e.view(item)["value"] == 3 and e.view(item)["is_received"] == 0
    assert context.state == before and not context.progress["mission_claims"]
    assert not mark_complete(e, item)
    assert clear_complete(e, item)
    assert not e.completed(item)


@pytest.mark.parametrize("kind,before,after", [
    (2, "2026-11-02T04:59:59", "2026-11-02T05:00:00"),
    (3, "2026-11-02T04:59:59", "2026-11-02T05:00:00"),
])
def test_completion_is_limited_to_current_day_or_week(context, kind, before, after):
    item = ordinary(context, kind=kind)
    e = evaluator(context)
    mark_complete(e, item)
    context.progress = json.loads(json.dumps(context.progress))
    context.now = stamp(before)
    assert evaluator(context).completed(item)
    context.now = stamp(after)
    assert not evaluator(context).completed(item)


def test_already_claimed_mission_is_not_reopened(context):
    item = ordinary(context)
    e = evaluator(context)
    context.progress["mission_claims"][e.key(item)] = [{"content_type": 50, "content_id": 0, "amount": 10}]
    before = copy.deepcopy(context.progress)
    assert not mark_complete(e, item)
    assert context.progress == before and e.view(item)["is_received"] == 1


def test_time_mission_and_changed_master_threshold(context):
    item = ordinary(context, situation_type=110200, require_value=10000)
    e = evaluator(context)
    assert not e.completed(item)
    mark_complete(e, item)
    assert e.view(item)["value"] == 10000 and e.completed(item)
    item["require_value"] = 5000
    assert not e.completed(item)


def test_mission_prerequisites_still_require_rewards_to_be_claimed(context, monkeypatch):
    first, second = mission(), mission(2, require_mission_id=1)
    context.tables["m_missions"] = [first, second]
    context.tables["m_mission_rewards"] = [{"group_id": item["id"], "content_type": 50, "content_id": 0, "amount": 10} for item in (first, second)]
    e = evaluator(context)
    mark_complete(e, first)
    mark_complete(e, second)
    assert not e.receivable(second)
    given = []
    monkeypatch.setattr(gameplay_missions, "deliver", lambda _, rewards: given.extend(rewards))
    e.receive([2, 1])
    assert len(given) == 2
    e.receive([2, 1])
    assert len(given) == 2


def test_event_subclass_uses_override_and_reset_epoch_invalidates_it(context):
    item = ordinary(context, kind=4, situation_type=110000, m_mission_term_id=10)
    context.tables["m_mission_terms"] = [{"id": 10, "category_group": 5}]
    context.tables["m_event_commission_missions"] = []
    event = {"id": 100, "m_mission_term_category_group": 5}
    current = EventMissions(context, event)
    assert current.value(item) == 0
    assert mark_complete(current, item) and current.completed(item)
    assert current.listing()["limited"][0]["value"] == 3
    context.progress["features"]["events"]["data"]["instances"]["100"]["epoch"] = 2
    assert not EventMissions(context, event).completed(item)


def test_campaign_subclass_does_not_share_completion_across_campaigns(context):
    item = ordinary(context, kind=4, situation_type=150100, m_mission_term_id=10)
    context.tables["m_mission_terms"] = [{"id": 10, "category_group": 5}]
    entry = {"join_at": context.now.isoformat(), "bonus_progress": 0, "pending_bonus": None, "clear_counts": {}}
    campaigns = {"current_id": 200, "entries": {"200": copy.deepcopy(entry), "201": copy.deepcopy(entry)}, "origins": {}}
    context.progress["features"]["encounter"] = {"version": 1, "data": {"next_id": 1, "campaigns": campaigns}}
    first = CampaignMissions(context, {"id": 200, "m_mission_term_id": 10})
    second = CampaignMissions(context, {"id": 201, "m_mission_term_id": 10})
    assert mark_complete(first, item)
    assert first.completed(item) and not second.completed(item)
    assert first.listing()["limited"][0]["value"] == 3


def test_pass_override_expires_on_its_own_weekday(context):
    item = ordinary(context, kind=6, m_mission_pass_id=202611, situation_type=150100)
    context.tables["m_mission_passes"] = [{"id": 202611, "start_at": "2026-10-31 10:00:00", "end_at": "2026-11-30 04:59:59"}]
    e = evaluator(context)
    assert mark_complete(e, item)
    context.now = stamp("2026-11-07T04:59:59")
    assert evaluator(context).completed(item)
    context.now += timedelta(seconds=1)
    assert not evaluator(context).completed(item)


def test_repeatable_nether_mission_override_completes_one_claim(context):
    item = ordinary(context, kind=9, situation_type=130000)
    context.progress["features"]["nether"] = {"version": 1, "data": {"ticket_claims": {}}}

    class LoopMissions(Missions):
        def value(self, mission):
            return 0

    e = LoopMissions(context.state, context.progress, context.catalog, context.now, context.user_id, context.rules)
    assert mark_complete(e, item) and e.completed(item)
    context.progress["features"]["nether"]["data"]["ticket_claims"][str(item["id"])] = 1
    assert not e.completed(item)


@pytest.mark.parametrize("changed", [{"special_days": [], "completed": {}}, {"special_days": {}, "completed": {"bad": {}}}])
def test_invalid_stored_controls_are_rejected(context, changed):
    item = ordinary(context)
    e = evaluator(context)
    context.progress["features"]["missions"]["data"]["controls"] = changed
    with pytest.raises(GameplayError):
        e.completed(item)


def test_validation_does_not_create_controls_and_preserves_known_data(context):
    before = copy.deepcopy(context.progress)
    validate_controls(context)
    assert context.progress == before
    e = evaluator(context)
    e.special(101)
    set_open_days(e, 101, 7)
    mark_complete(e, context.tables["m_missions"][0])
    before = copy.deepcopy(context.progress)
    validate_controls(e)
    assert context.progress == before


@pytest.mark.parametrize("kind", ["special", "mission", "shape"])
def test_validation_rechecks_cached_shape_and_master_references(context, kind):
    e = evaluator(context)
    e.special(101)
    set_open_days(e, 101, 7)
    mark_complete(e, context.tables["m_missions"][0])
    data = context.progress["features"]["missions"]["data"]["controls"]
    if kind == "special":
        data["special_days"]["999"] = data["special_days"].pop("101")
    elif kind == "mission":
        next(iter(data["completed"].values()))["mission_id"] = 999
    else:
        next(iter(data["completed"].values()))["unknown"] = 1
    with pytest.raises((GameplayError, StopIteration)):
        validate_controls(e)
