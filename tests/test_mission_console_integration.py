import copy
import json
from datetime import timedelta

import pytest

from dotabyss_ps.admin_actions import action_specs, apply_action
from dotabyss_ps.admin_service import TIME_SENSITIVE_ACTIONS
from dotabyss_ps.admin_validation import validate_import
from dotabyss_ps.gameplay import Gameplay
from dotabyss_ps.gameplay_catalog import GameplayCatalog, GameplayError
from dotabyss_ps.gameplay_missions import COUNTER_SITUATIONS, Missions
from dotabyss_ps.gameplay_records import find
from test_admin_console import apply, endpoint, get, headers, preview
from test_gameplay import NOW, call, gameplay_master, setup_gameplay, snapshot


def player(context):
    state, progress = map(json.loads, snapshot(context))
    return Gameplay(state, progress, GameplayCatalog(context.tables, context.schema), context.identity["user_id"], NOW)


def special_record(records):
    return next(row for row in records["t_special_missions"]["up"] if row["m_special_mission_id"] == 101)


def test_time_sensitive_actions_are_registered():
    assert TIME_SENSITIVE_ACTIONS <= {row["id"] for row in action_specs()}


def test_console_special_dates_sync_and_login_preserve_stored_dates(setup_gameplay):
    c = setup_gameplay
    call(c, "api/special-mission/top", {"m_special_mission_id": 101})
    before = get(c)
    original = special_record(before["state"]["records"])["start_at"]
    proposal = preview(c, "mission.open_days", {"ids": [101], "all_days": True})
    assert get(c)["state"] == before["state"]
    saved = apply(c, proposal["ticket"])
    assert special_record(get(c)["state"]["records"])["start_at"] == original
    expected = (NOW - timedelta(days=6)).isoformat()
    sync = c.client.get("/local/admin-sync?client_id=mission-test&after=0", headers=c.headers)
    assert sync.status_code == 200, sync.text
    assert special_record(sync.json()["records"])["start_at"] == expected
    assert special_record(call(c, "api/user")["records"])["start_at"] == expected
    assert special_record(call(c, "api/special-mission/top", {"m_special_mission_id": 101})["records"])["start_at"] == expected
    restored = preview(c, "mission.open_days", {"ids": [101], "all_days": False, "days": 0})
    apply(c, restored["ticket"])
    sync = c.client.get(f"/local/admin-sync?client_id=mission-test&after={saved['revision']}", headers=c.headers).json()
    assert special_record(sync["records"])["start_at"] == original


def test_complete_preview_and_separate_claim_use_native_mission_views(setup_gameplay):
    c = setup_gameplay
    call(c, "api/special-mission/top", {"m_special_mission_id": 101})
    proposal = preview(c, "mission.open_days", {"ids": [101]})
    apply(c, proposal["ticket"])
    game = player(c)
    eligible = [row["m_mission_id"] for row in game.catalog.rows("m_special_mission_days")
                if row["m_special_mission_id"] == 101 and row["day"] == 7]
    mission = next(game.catalog.get("m_missions", identifier) for identifier in eligible
                   if not game.catalog.get("m_missions", identifier)["require_mission_id"])
    args = {"scope": "special", "group_id": 101, "ids": [mission["id"]]}
    before = get(c)
    proposal = preview(c, "mission.complete", args)
    assert get(c)["progress"] == before["progress"]
    apply(c, proposal["ticket"])
    assert get(c)["state"]["records"] == before["state"]["records"]
    assert not get(c)["progress"]["mission_claims"]
    values = call(c, "api/special-mission/top", {"m_special_mission_id": 101})
    view = next(row for row in values["missions"]["special"] if row["m_mission_id"] == mission["id"])
    assert view["value"] == mission["require_value"] and view["is_received"] == 0
    claim = preview(c, "mission.claim", args)
    first = apply(c, claim["ticket"])
    after = get(c)
    assert f"once:{mission['id']}" in after["progress"]["mission_claims"]
    assert apply(c, claim["ticket"])["revision"] == first["revision"]
    assert get(c)["state"] == after["state"]


def test_mission_controls_and_pass_statistics_can_be_imported_without_mutation(setup_gameplay):
    c = setup_gameplay
    call(c, "api/user")
    game = player(c)
    apply_action(game, "mission.open_days", {"ids": [101]})
    apply_action(game, "mission.complete", {"scope": "special", "group_id": 101, "all": True})
    before = copy.deepcopy((game.state, game.progress))
    validate_import(game)
    assert (game.state, game.progress) == before
    control = game.progress["features"]["missions"]["data"]["controls"]
    next(iter(control["completed"].values()))["mission_id"] = 999999999999
    with pytest.raises(GameplayError):
        validate_import(game)


def test_admin_today_counter_uses_the_same_reset_day_as_missions(setup_gameplay):
    c = setup_gameplay
    call(c, "api/user")
    game = player(c)
    game.now = NOW.replace(hour=3)
    daily = next(row for row in game.catalog.rows("m_missions")
                 if row["mission_type"] == 2 and row["situation_type"] == 60000)
    apply_action(game, "mission.statistic", {"situation": daily["situation_type"], "target": daily["target_id"],
                                          "sub_target": daily["sub_target_id"], "period": "today", "value": 7})
    evaluator = Missions(game.state, game.progress, game.catalog, game.now, game.user_id, game.rules)
    assert evaluator.value(daily) == 7
    game.now = game.now.replace(hour=5)
    evaluator = Missions(game.state, game.progress, game.catalog, game.now, game.user_id, game.rules)
    assert evaluator.value(daily) == 0


def test_cached_special_view_refreshes_completion_without_caching_projected_dates(setup_gameplay):
    c = setup_gameplay
    call(c, "api/user")
    game = player(c)
    body = {"m_special_mission_id": 101}
    game.execute("api/special-mission/top", "POST", body, "special-view")
    original = find(game.state, "t_special_missions", m_special_mission_id=101)["start_at"]
    apply_action(game, "mission.open_days", {"ids": [101]})
    apply_action(game, "mission.complete", {"scope": "special", "group_id": 101, "all": True})
    response = game.execute("api/special-mission/top", "POST", body, "special-view")
    for view in response["missions"]["special"]:
        assert view["value"] == game.catalog.get("m_missions", view["m_mission_id"])["require_value"]
    assert special_record(response["records"])["start_at"] != original
    saved = game.progress["operation_receipts"]["special-view"]["response"]
    assert special_record(saved["records"])["start_at"] == original


def test_reward_preview_cannot_claim_the_next_day(setup_gameplay, monkeypatch):
    import dotabyss_ps.gameplay as module

    c = setup_gameplay
    call(c, "api/user")
    game = player(c)
    evaluator = game._missions()
    daily = next(row for row in game.catalog.rows("m_missions")
                 if row["mission_type"] == 2 and row["situation_type"] in COUNTER_SITUATIONS
                 and evaluator.active(row) and not row["require_mission_id"] and not evaluator.completed(row))
    args = {"scope": "daily", "ids": [daily["id"]]}
    apply(c, preview(c, "mission.complete", args)["ticket"])
    claim = preview(c, "mission.claim", args)
    before = snapshot(c)

    class Tomorrow(type(NOW)):
        @classmethod
        def now(cls, tz=None):
            return (NOW + timedelta(days=1)).astimezone(tz)

    monkeypatch.setattr(module, "datetime", Tomorrow)
    response = c.client.post(f"/admin/profiles/{c.identity['user_id']}/apply", headers=headers(c), json={"ticket": claim["ticket"]})
    assert response.status_code in (400, 409), response.text
    assert snapshot(c) == before


def test_mixed_batch_claim_failure_keeps_rewards_and_receipts_unchanged(setup_gameplay):
    c = setup_gameplay
    call(c, "api/special-mission/top", {"m_special_mission_id": 101})
    game = player(c)
    evaluator = game._missions()
    day_one = {row["m_mission_id"] for row in game.catalog.rows("m_special_mission_days")
               if row["m_special_mission_id"] == 101 and row["day"] == 1}
    selected = [row for row in game.catalog.rows("m_missions")
                if row["id"] in day_one and not row["require_mission_id"] and not evaluator.completed(row)][:2]
    assert len(selected) == 2
    args = {"scope": "special", "group_id": 101, "ids": [selected[0]["id"]]}
    apply(c, preview(c, "mission.complete", args)["ticket"])
    before = snapshot(c)
    args["ids"].append(selected[1]["id"])
    response = c.client.post(endpoint(c) + "/preview", headers=headers(c),
                             json={"operation": "mission.claim", "args": args, "expected_version": get(c)["version"]})
    assert response.status_code in (400, 409), response.text
    assert snapshot(c) == before
