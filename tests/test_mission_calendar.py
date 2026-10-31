import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from dotabyss_ps.gameplay_catalog import GameplayError, JST
from dotabyss_ps.gameplay_event_missions import add_statistic, validate_statistics
from dotabyss_ps.gameplay_mission_calendar import (
    claim_period, elapsed_days, login_days, prepare, reset_day, resolve_claim_key, statistics_days, week_start,
)
from dotabyss_ps.gameplay_nether_missions import NetherMissions
from dotabyss_ps.gameplay_statistics import bucket, record, value


def at(text):
    return datetime.fromisoformat(text).replace(tzinfo=JST)


def game(now, missions=(), *, claims=None, days=None):
    catalog = SimpleNamespace(rows=lambda name: list(missions) if name == "m_missions" else [])
    return SimpleNamespace(now=at(now), catalog=catalog,
                           progress={"features": {}, "mission_claims": claims or {}, "login_days": days or []})


@pytest.mark.parametrize("moment,day,count", [
    ("2026-11-01T23:59:59", "2026-11-01", 1),
    ("2026-11-02T00:00:00", "2026-11-01", 1),
    ("2026-11-02T04:59:59", "2026-11-01", 1),
    ("2026-11-02T05:00:00", "2026-11-02", 2),
    ("2026-11-07T05:00:00", "2026-11-07", 7),
])
def test_special_days_advance_at_the_native_reset(moment, day, count):
    assert reset_day(at(moment)).isoformat() == day
    assert elapsed_days("2026-11-01T06:24:59+09:00", at(moment)) == count


def test_reset_boundary_uses_japan_time_independent_of_caller_timezone():
    moment = datetime(2026, 11, 2, 4, 0, tzinfo=timezone(timedelta(hours=8)))
    assert reset_day(moment).isoformat() == "2026-11-02"
    assert elapsed_days("2026-11-01T04:59:59+09:00", at("2026-11-01T05:00:00")) == 2
    assert elapsed_days("2026-11-02T12:00:00+09:00", at("2026-11-01T05:00:00")) == 1


def test_claim_period_and_weekday_stay_in_old_period_until_five():
    before, after = at("2026-11-02T04:59:59"), at("2026-11-02T05:00:00")
    assert week_start(before).isoformat() == "2026-10-26"
    assert week_start(after).isoformat() == "2026-11-02"
    for kind in (2, 8):
        assert claim_period({"mission_type": kind}, before) == "2026-11-01"
        assert claim_period({"mission_type": kind}, after) == "2026-11-02"
    assert claim_period({"mission_type": 3}, before) == "2026-W44"
    assert claim_period({"mission_type": 3}, after) == "2026-W45"
    assert claim_period({"mission_type": 7}, after) == "once"


def test_legacy_claims_cover_both_overlapping_periods_without_regrant():
    rewards = [{"content_type": 30, "content_id": 1, "amount": 2}]
    claims = {"2026-11-02:1": rewards, "2026-W45:2": rewards, "2026-W45:3": rewards, "once:4": rewards}
    missions = [{"id": 1, "mission_type": 2}, {"id": 2, "mission_type": 3},
                {"id": 3, "mission_type": 6, "m_mission_pass_id": 10}, {"id": 4, "mission_type": 7}]
    g = game("2026-11-02T04:00:00", missions, claims=copy.deepcopy(claims))
    prepare(g)
    stored = g.progress["mission_claims"]
    assert stored == claims
    assert resolve_claim_key(g, missions[0], "2026-11-01:1") == "2026-11-02:1"
    assert resolve_claim_key(g, missions[1], "2026-W44:2") == "2026-W45:2"
    assert resolve_claim_key(g, missions[2], "2026-W44:3") == "2026-W44:3"
    before = copy.deepcopy(g.progress)
    prepare(g)
    assert g.progress == before
    g.progress = json.loads(json.dumps(g.progress))
    g.now = at("2026-11-03T04:00:00")
    stored = g.progress["mission_claims"]
    stored["2026-11-03:1"] = rewards
    prepare(g)
    assert "2026-10-31:1" not in stored
    assert len(stored) == len(claims) + 1


def test_full_legacy_receipt_ledger_does_not_expand_during_calendar_migration():
    claims = {f"2026-11-02:{identifier}": [] for identifier in range(1, 10001)}
    g = game("2026-11-02T04:00:00", claims=copy.deepcopy(claims))
    prepare(g)
    assert g.progress["mission_claims"] == claims
    assert resolve_claim_key(g, {"id": 10000, "mission_type": 2}, "2026-11-01:10000") == "2026-11-02:10000"


def test_reset_login_history_keeps_raw_history_and_filters_clock_rollback():
    g = game("2026-11-02T04:00:00", days=["2026-10-31", "2026-11-01", "2026-11-02"])
    prepare(g)
    assert login_days(g.progress, g.now) == ["2026-10-31", "2026-11-01"]
    assert g.progress["login_days"] == ["2026-10-31", "2026-11-01", "2026-11-02"]
    g.now = at("2026-11-02T05:00:00")
    assert login_days(g.progress, g.now) == ["2026-10-31", "2026-11-01", "2026-11-02"]
    assert login_days(g.progress, at("2026-11-01T12:00:00")) == ["2026-10-31", "2026-11-01"]


def test_statistics_keep_one_total_and_cross_midnight_without_reset():
    progress = {"features": {}}
    mission = {"mission_type": 2, "situation_type": 60000}
    record(progress, at("2026-11-01T23:59:59"), 60000, 2)
    record(progress, at("2026-11-02T00:00:00"), 60000, 3)
    assert value(progress, at("2026-11-02T04:59:59"), mission) == 5
    assert bucket(progress)["totals"]["60000:0:0"] == 5
    assert value(progress, at("2026-11-02T05:00:00"), mission) is None
    record(progress, at("2026-11-02T05:00:00"), 60000, 4)
    assert value(progress, at("2026-11-02T05:00:00"), mission) == 4
    assert bucket(progress)["days"] == {"2026-11-01": {"60000:0:0": 2}, "2026-11-02": {"60000:0:0": 7}}


def test_weekly_statistics_exclude_the_new_week_until_five():
    progress = {"features": {}}
    mission = {"mission_type": 3, "situation_type": 60000}
    record(progress, at("2026-11-01T23:59:59"), 60000, 2)
    record(progress, at("2026-11-02T04:59:59"), 60000, 3)
    assert value(progress, at("2026-11-02T04:59:59"), mission) == 5
    assert value(progress, at("2026-11-02T05:00:00"), mission) is None


@pytest.mark.parametrize("mode,expected", [("add", 7), ("max", 5), ("min", 2)])
def test_event_statistics_use_same_boundary_and_preserve_aggregation(mode, expected):
    data = {"totals": {}, "days": {}}
    g = SimpleNamespace(now=at("2026-11-01T23:59:59"))
    add_statistic(g, data, 110000, 5, mode=mode)
    g.now = at("2026-11-02T04:59:59")
    add_statistic(g, data, 110000, 2, mode=mode)
    assert statistics_days(data, g.now)["2026-11-01"]["110000:0:0"] == expected
    assert data["totals"]["110000:0:0"] == expected
    assert validate_statistics(data) is data


def test_legacy_statistics_migration_preserves_original_and_current_visible_value():
    raw = {"2026-11-01": {"60000:0:0": 5}, "2026-11-02": {"60000:0:0": 2}}
    data = {"initialized": True, "totals": {"60000:0:0": 7}, "days": copy.deepcopy(raw)}
    progress = {"features": {"statistics": {"version": 1, "data": data}}}
    assert value(progress, at("2026-11-02T04:59:59"), {"mission_type": 2, "situation_type": 60000}) == 2
    assert data["days"] == raw and data["totals"]["60000:0:0"] == 7
    assert value(progress, at("2026-11-02T05:00:00"), {"mission_type": 2, "situation_type": 60000}) is None


def test_nether_distinct_characters_use_reset_days():
    progress = {"features": {}}
    record(progress, at("2026-11-01T23:00:00"), 120001, 1, 10, 100)
    record(progress, at("2026-11-02T01:00:00"), 120001, 1, 10, 101)
    evaluator = object.__new__(NetherMissions)
    evaluator.statistics = bucket(progress)
    evaluator.now = at("2026-11-02T04:59:59")
    mission = {"situation_type": 120001, "mission_type": 2, "target_id": 10, "sub_target_id": 0}
    assert evaluator.value(mission) == 2
    evaluator.now = at("2026-11-02T05:00:00")
    assert evaluator.value(mission) == 0


@pytest.mark.parametrize("key,bad", [("reset_days", {"bad-date": {}}), ("reset_started_at", "bad-date")])
def test_invalid_reset_statistics_fail_validation(key, bad):
    progress = {"features": {}}
    record(progress, at("2026-11-01T12:00:00"), 60000)
    bucket(progress)[key] = bad
    with pytest.raises(GameplayError):
        bucket(progress)
