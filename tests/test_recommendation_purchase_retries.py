import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from dotabyss_ps.app import create_app
from dotabyss_ps.gameplay import Gameplay
from dotabyss_ps.gameplay_catalog import GameplayCatalog, GameplayError, JST
from dotabyss_ps.gameplay_records import rows
from dotabyss_ps.gameplay_shop import listing, purchase, recommend_view, shop_data, validate_purchase
from dotabyss_ps.newgame import build_initial_state
from test_gameplay import NOW, call, gameplay_master, setup_gameplay, snapshot


@pytest.fixture
def game(gameplay_master):
    schema, tables = gameplay_master
    state = build_initial_state(tables, schema, 7, "Sale retry", "2026-10-31 00:00:00", start_tutorial=False)
    current = Gameplay(state, {}, GameplayCatalog(tables, schema), 7, NOW)
    current.prepare()
    return current


def release(game, identifier):
    shop_data(game)["released"][str(identifier)] = (game.now + timedelta(hours=2)).isoformat()


@pytest.mark.parametrize("identifier", [200002, 200007])
def test_paid_sale_retry_is_empty_and_preserves_every_reward_counter(game, identifier):
    release(game, identifier)
    assert game.catalog.get("m_payments", identifier)["is_free"] == 0
    first = purchase(game, identifier)
    assert first["received_items"]
    before = copy.deepcopy((game.state, game.progress))
    assert purchase(game, identifier) == {"received_items": [], "exec_response": None}
    assert (game.state, game.progress) == before
    assert shop_data(game)["counts"][str(identifier)]["count"] == 1
    assert not any(row["m_payment_recommend_id"] == identifier for row in recommend_view(game))
    assert not any(row["m_payment_recommend_id"] == identifier for row in listing(game, {})["categories"]["recommends"])
    with pytest.raises(GameplayError, match="already been purchased"):
        validate_purchase(game, identifier)


def test_completed_sale_can_finish_a_stale_click_after_its_timer_expires(game):
    release(game, 200002)
    purchase(game, 200002)
    game.now += timedelta(hours=3)
    before = copy.deepcopy((game.state, game.progress))
    assert purchase(game, 200002) == {"received_items": [], "exec_response": None}
    assert (game.state, game.progress) == before


def test_unavailable_or_unknown_sale_is_not_treated_as_a_completed_purchase(game):
    with pytest.raises(GameplayError, match="not available"):
        purchase(game, 200002)
    with pytest.raises(GameplayError):
        purchase(game, 999999999)
    release(game, 200002)
    game.catalog.tables["m_payments"][200002] = {**game.catalog.get("m_payments", 200002), "m_payment_dmm_product_id": 0}
    shop_data(game)["counts"]["200002"] = {"period": "once", "count": 1}
    with pytest.raises(GameplayError, match="not available on the local DMM"):
        purchase(game, 200002)


def test_other_purchase_limits_and_step_sequences_remain_strict(game):
    purchase(game, 70001)
    with pytest.raises(GameplayError, match="limit reached"):
        purchase(game, 70001)
    purchase(game, 20001)
    with pytest.raises(GameplayError, match="already active"):
        purchase(game, 20001)
    game.now = datetime(2026, 9, 22, 14, tzinfo=JST)
    purchase(game, 120001)
    with pytest.raises(GameplayError, match="current step"):
        purchase(game, 120001)
    assert shop_data(game)["steps"]["120001"] == 2


def test_type_two_recommendations_keep_their_existing_purchase_behavior(game):
    release(game, 300001)
    assert game.catalog.get("m_payment_recommends", 300001)["recommend_type"] == 2
    assert purchase(game, 300001)["received_items"]
    assert purchase(game, 300001)["received_items"]
    assert shop_data(game)["counts"]["300001"]["count"] == 2
    assert any(row["m_payment_recommend_id"] == 300001 for row in recommend_view(game))


def release_in_store(context, identifier):
    call(context, "api/user")

    def update(state, progress):
        game = Gameplay(state, progress, GameplayCatalog(context.tables, context.schema), context.identity["user_id"], NOW)
        release(game, identifier)
        return {}

    context.store.game_state(context.identity["user_id"], context.record["revision"], lambda *_: None, update)


def test_sale_operation_retry_and_new_request_survive_restart(setup_gameplay):
    c = setup_gameplay
    identifier = 200007
    release_in_store(c, identifier)
    body = {"m_payment_id": identifier}
    headers = {**c.headers, "x-request-id": "sale-first"}
    first = call(c, "api/payment/grant/free", body, headers=headers)
    assert first["received_items"]
    before = snapshot(c)
    assert call(c, "api/payment/grant/free", body, headers=headers) == first
    assert snapshot(c) == before
    second = call(c, "api/payment/grant/free", body, headers={**c.headers, "x-request-id": "sale-repeat"})
    assert second["received_items"] == [] and second["exec_response"] is None
    state, progress = map(json.loads, snapshot(c))
    assert state == json.loads(before[0])
    assert progress["features"]["shop"]["data"]["counts"][str(identifier)]["count"] == 1
    with TestClient(create_app(c.settings)) as restarted:
        response = restarted.post("/api/payment/grant/free", json=body, headers=c.headers)
        assert response.status_code == 200, response.text
        assert response.json()["contents"]["received_items"] == []
        home = restarted.post("/api/home", json={}, headers=c.headers).json()["contents"]
        assert not any(row["m_payment_recommend_id"] == identifier for row in home["available_recommends"])
        lineup = restarted.post("/api/payment/lineup", json={}, headers=c.headers).json()["contents"]
        assert not any(row["m_payment_recommend_id"] == identifier for row in lineup["categories"]["recommends"])


def test_concurrent_sale_clicks_grant_one_purchase(setup_gameplay):
    c = setup_gameplay
    release_in_store(c, 200002)

    def buy(index):
        return call(c, "api/payment/grant/free", {"m_payment_id": 200002},
                    headers={**c.headers, "x-request-id": "sale-concurrent-" + str(index)})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(buy, range(4)))
    assert sum(bool(response["received_items"]) for response in responses) == 1
    state, progress = map(json.loads, snapshot(c))
    assert progress["features"]["shop"]["data"]["counts"]["200002"]["count"] == 1
    assert len([row for row in rows(state, "t_payment_dmm_currencies") if row["store_product_id"] == "local.200002"]) == 1
