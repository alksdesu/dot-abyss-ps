from __future__ import annotations

import copy
from datetime import date, timedelta
import re

from .gameplay_catalog import GameplayError, JST, parse_timestamp


def reset_day(now):
    local = now.replace(tzinfo=JST) if now.tzinfo is None else now.astimezone(JST)
    return (local - timedelta(hours=5)).date()


def week_start(now):
    today = reset_day(now)
    return today - timedelta(days=today.weekday())


def elapsed_days(start_at, now):
    start = parse_timestamp(start_at) if isinstance(start_at, str) else start_at
    return max(1, (reset_day(now) - reset_day(start)).days + 1)


def claim_period(mission, now):
    kind = mission["mission_type"]
    if kind in (2, 8):
        return reset_day(now).isoformat()
    if kind in (3, 6):
        return week_start(now).strftime("%G-W%V")
    return "once"


def _calendar(progress, now):
    missions = progress["features"].setdefault("missions", {"version": 1, "data": {}})["data"]
    if "calendar" not in missions:
        today = now.astimezone(JST).date().isoformat()
        history = [day for day in progress.get("login_days", []) if day != today]
        missions["calendar"] = {"version": 1, "started_at": now.isoformat(), "login_days": history,
                                "legacy_claim_keys": list(progress.get("mission_claims", {}))}
    data = missions["calendar"]
    if (not isinstance(data, dict) or set(data) != {"version", "started_at", "login_days", "legacy_claim_keys"}
            or type(data["version"]) is not int or data["version"] != 1
            or not isinstance(data["login_days"], list) or len(data["login_days"]) > 10000
            or not isinstance(data["legacy_claim_keys"], list) or len(data["legacy_claim_keys"]) > 10000):
        raise GameplayError("Stored mission calendar is invalid")
    try:
        parse_timestamp(data["started_at"])
        if (len(set(data["login_days"])) != len(data["login_days"])
                or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in data["login_days"])):
            raise ValueError()
    except (TypeError, ValueError, AttributeError):
        raise GameplayError("Stored mission calendar dates are invalid") from None
    if (any(not isinstance(key, str) or not re.fullmatch(r"(?:once|\d{4}-\d{2}-\d{2}|\d{4}-W\d{2}):[1-9]\d{0,18}", key)
            for key in data["legacy_claim_keys"])
            or len(set(data["legacy_claim_keys"])) != len(data["legacy_claim_keys"])):
        raise GameplayError("Stored mission calendar receipt keys are invalid")
    return data


def login_days(progress, now):
    days = _calendar(progress, now)["login_days"]
    today = reset_day(now).isoformat()
    if today not in days:
        if len(days) >= 10000:
            raise GameplayError("Stored mission login history exceeds its limit")
        days.append(today)
    return [day for day in days if day <= today]


def prepare(game):
    data = _calendar(game.progress, game.now)
    login_days(game.progress, game.now)
    statistics = game.progress["features"].get("statistics", {}).get("data")
    if statistics:
        statistics_days(statistics, game.now)
    game._legacy_mission_claim_keys = data, frozenset(data["legacy_claim_keys"])


def resolve_claim_key(game, mission, proposed):
    claims = game.progress["mission_claims"]
    if proposed in claims or mission.get("m_mission_pass_id"):
        return proposed
    data = game.progress.get("features", {}).get("missions", {}).get("data", {}).get("calendar")
    cached = getattr(game, "_legacy_mission_claim_keys", None)
    if cached is None or cached[0] is not data:
        prepare(game)
        cached = game._legacy_mission_claim_keys
    kind = mission["mission_type"]
    if kind in (2, 8):
        adjacent = (reset_day(game.now) + timedelta(days=1)).isoformat()
    elif kind in (3, 6):
        adjacent = (week_start(game.now) + timedelta(days=7)).strftime("%G-W%V")
    else:
        return proposed
    legacy = f"{adjacent}:{mission['id']}"
    # The old midnight receipt also covers the preceding 05:00 period.
    return legacy if legacy in cached[1] and legacy in claims else proposed


def statistics_days(data, now):
    if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
        raise GameplayError("Stored mission daily statistics are invalid")
    present = {key for key in ("reset_days", "reset_started_at") if key in data}
    if present and len(present) != 2:
        raise GameplayError("Stored mission reset statistics are incomplete")
    if not present:
        days = copy.deepcopy(data["days"])
        today, current = now.astimezone(JST).date().isoformat(), reset_day(now).isoformat()
        if today != current:
            # Preserve the visible legacy day's progress without duplicating an ambiguous day.
            days[current] = copy.deepcopy(days.get(today, {}))
            days.pop(today, None)
        data.update(reset_days=days, reset_started_at=now.isoformat())
    return data["reset_days"]


def validate_statistics_days(data, limit):
    present = {key for key in ("reset_days", "reset_started_at") if key in data}
    if not present:
        return
    if len(present) != 2 or not isinstance(data["reset_days"], dict) or len(data["reset_days"]) > 400:
        raise GameplayError("Stored mission reset statistics are invalid")
    try:
        parse_timestamp(data["reset_started_at"])
        for day, values in data["reset_days"].items():
            if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or not isinstance(values, dict) or len(values) > 10000:
                raise ValueError()
            for identity, amount in values.items():
                if (not isinstance(identity, str) or not re.fullmatch(r"[1-9][0-9]{0,8}:[0-9]{1,19}:[0-9]{1,19}", identity)
                        or type(amount) is not int or not 0 <= amount <= limit):
                    raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise GameplayError("Stored mission reset statistic values are invalid") from None
