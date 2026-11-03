from __future__ import annotations

from .gameplay_catalog import available, number
from .gameplay_effects import boosted

DISASTER_TARGET = 2
DISASTER_COIN = 52


def additional_extra_drop(game, target):
    if not {"m_campaigns", "m_campaign_additional_extra_drops"} <= game.catalog.tables.keys():
        return 0
    active = {row["id"] for row in game.catalog.rows("m_campaigns") if available(row, game.now, "begin_at")}
    return sum(number(row["additional_probability"], 0, 1000000)
               for row in game.catalog.rows("m_campaign_additional_extra_drops")
               if row["m_campaign_id"] in active and row["effective_target"] == target)


def boost_disaster_rewards(game, rewards):
    bonus = additional_extra_drop(game, DISASTER_TARGET)
    return [{**reward, "amount": boosted(reward["amount"], bonus) if reward["content_type"] == DISASTER_COIN
             else reward["amount"]} for reward in rewards]
