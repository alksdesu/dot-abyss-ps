import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from dotabyss_ps.gameplay import Gameplay
from dotabyss_ps.gameplay_battle_session import battle_state
from dotabyss_ps.gameplay_campaign_effects import boost_disaster_rewards
from dotabyss_ps.gameplay_catalog import GameplayCatalog, JST
from dotabyss_ps.gameplay_records import put, rows
from test_battle_rewards import reward_game, reward_master
from test_disaster_mode import victory
from test_gameplay import party_body

BEGIN = datetime(2026, 11, 3, 5, tzinfo=JST)
END = datetime(2026, 11, 10, 4, 59, 59, tzinfo=JST)


@pytest.fixture
def campaign_game():
    schema = {"tables": {
        "m_campaigns": [{"name": field} for field in ("id", "name", "begin_at", "end_at")],
        "m_campaign_additional_extra_drops": [{"name": field} for field in
                                              ("id", "m_campaign_id", "effective_target", "additional_probability")],
    }}
    tables = {"m_campaigns": [[23, "Disaster campaign", "2026-11-03 5:00:00", "2026-11-10 4:59:59"]],
              "m_campaign_additional_extra_drops": [[22, 23, 2, 1000]]}
    return SimpleNamespace(catalog=GameplayCatalog(tables, schema), now=BEGIN)


@pytest.mark.parametrize("now,amount", [
    (BEGIN - timedelta(seconds=1), 50), (BEGIN, 100), (END, 100),
    (END + timedelta(seconds=1), 50), (BEGIN.astimezone(timezone(timedelta(hours=8))), 100),
])
def test_campaign_uses_official_jst_window(campaign_game, now, amount):
    campaign_game.now = now
    rewards = [{"content_type": 52, "content_id": 0, "amount": 50}]
    assert boost_disaster_rewards(campaign_game, rewards)[0]["amount"] == amount
    assert rewards[0]["amount"] == 50


@pytest.mark.parametrize("missing", ["m_campaigns", "m_campaign_additional_extra_drops", "both"])
def test_legacy_master_without_campaign_tables_keeps_base_rewards(campaign_game, missing):
    tables = campaign_game.catalog.tables
    if missing == "both":
        tables.clear()
    else:
        tables.pop(missing)
    rewards = [{"content_type": 52, "content_id": 0, "amount": 50}]
    assert boost_disaster_rewards(campaign_game, rewards) == rewards


def test_only_disaster_target_boosts_coins_and_preserves_master(campaign_game):
    tables = campaign_game.catalog.tables
    tables["m_campaign_additional_extra_drops"].update({
        30: {"id": 30, "m_campaign_id": 23, "effective_target": 3, "additional_probability": 9000},
        31: {"id": 31, "m_campaign_id": 999, "effective_target": 2, "additional_probability": 9000},
    })
    rewards = [{"content_type": kind, "content_id": 0, "amount": 50} for kind in (52, 50, 30, 110)]
    original = copy.deepcopy((tables, rewards))
    assert [reward["amount"] for reward in boost_disaster_rewards(campaign_game, rewards)] == [100, 50, 50, 50]
    assert (tables, rewards) == original


def disaster_game(source, now):
    game = Gameplay(source.state, {}, source.catalog, source.user_id, now, source.rules)
    game.execute("api/party/exploration/edit", "POST", party_body())
    put(game.state, "t_feature_locks", {"m_feature_lock_id": 3}, {"is_unlocked": True})
    game.execute("api/disaster/refresh", "POST", {})
    return game


def clear_disaster(game, slot):
    game.execute("api/disaster/start-quest", "POST", {"slot": slot, "party_no": 1})
    body = victory(battle_state(game)["active"])
    return game.execute("api/disaster/clear-quest", "POST", body), body


def test_official_master_doubles_normal_special_and_skip_rewards_once(reward_game):
    game = disaster_game(reward_game, BEGIN)
    campaign = game.catalog.get("m_campaigns", 23)
    assert campaign["begin_at"] == "2026-11-03 5:00:00"
    assert campaign["end_at"] == "2026-11-10 4:59:59"
    balance = rows(game.state, "t_statuses")[0]["disaster_coin"]
    normal, body = clear_disaster(game, 1)
    assert [(row["content_type"], row["content_id"], row["amount"]) for row in normal["clear_rewards"]] == [(52, 0, 100)]
    assert rows(game.state, "t_statuses")[0]["disaster_coin"] == balance + 100
    stable = copy.deepcopy((game.state, game.progress))
    assert game.execute("api/disaster/clear-quest", "POST", body)["clear_rewards"] == normal["clear_rewards"]
    assert (game.state, game.progress) == stable
    skipped = game.execute("api/disaster/skip-quest", "POST", {"slot": 2}, operation_id="campaign-skip")
    assert skipped["clear_rewards"] == normal["clear_rewards"]
    stable = copy.deepcopy((game.state, game.progress))
    assert game.execute("api/disaster/skip-quest", "POST", {"slot": 2}, operation_id="campaign-skip")["clear_rewards"] == skipped["clear_rewards"]
    assert (game.state, game.progress) == stable
    special, _ = clear_disaster(game, 0)
    assert special["clear_rewards"] == normal["clear_rewards"]
    assert rows(game.state, "t_statuses")[0]["disaster_coin"] == balance + 300


@pytest.mark.parametrize("finish_at,amount", [(END, 100), (END + timedelta(seconds=1), 50)])
def test_campaign_expiry_uses_settlement_time_and_retry_preserves_reward(reward_game, finish_at, amount):
    game = disaster_game(reward_game, END)
    game.execute("api/disaster/start-quest", "POST", {"slot": 1, "party_no": 1})
    pending = victory(battle_state(game)["active"])
    game.now = finish_at
    settled = game.execute("api/disaster/clear-quest", "POST", pending)
    assert settled["clear_rewards"][0]["amount"] == amount
    balance = rows(game.state, "t_statuses")[0]["disaster_coin"]
    game.now = END + timedelta(seconds=1)
    assert game.execute("api/disaster/clear-quest", "POST", pending)["clear_rewards"] == settled["clear_rewards"]
    assert rows(game.state, "t_statuses")[0]["disaster_coin"] == balance
