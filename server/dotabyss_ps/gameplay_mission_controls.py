from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, time, timedelta

from .gameplay_catalog import GameplayError, JST, available, number, parse_timestamp
from .gameplay_comeback import special_window
from .gameplay_records import find, rows
from .gameplay_statistics import TIME_SITUATIONS

MAX_OVERRIDES = 10000


def _timestamp(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        raise GameplayError("Stored mission control date is invalid")
    try:
        return parse_timestamp(value)
    except (ValueError, TypeError) as error:
        raise GameplayError("Stored mission control date is invalid") from error


def _data(game, *, create=False, validate=False):
    missions = game.progress.get("features", {}).get("missions", {}).get("data", {})
    data = missions.get("controls")
    if data is None and create:
        missions = game.progress["features"].setdefault("missions", {"version": 1, "data": {}})["data"]
        data = missions.setdefault("controls", {"special_days": {}, "completed": {}})
    if data is None or not validate and getattr(game, "_mission_controls_validated", None) is data:
        return data
    if not isinstance(data, dict) or set(data) != {"special_days", "completed"}:
        raise GameplayError("Stored mission controls are invalid")
    if not all(isinstance(value, dict) and len(value) <= MAX_OVERRIDES for value in data.values()):
        raise GameplayError("Stored mission controls exceed their limit")
    for key, entry in data["special_days"].items():
        if not isinstance(key, str) or not re.fullmatch(r"[1-9][0-9]{0,18}", key):
            raise GameplayError("Stored special mission control identity is invalid")
        if not isinstance(entry, dict) or set(entry) != {"record_id", "start_at", "offset"}:
            raise GameplayError("Stored special mission control is invalid")
        number(entry["record_id"])
        number(entry["offset"], 0, 36500)
        _timestamp(entry["start_at"])
    for key, entry in data["completed"].items():
        if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
            raise GameplayError("Stored mission completion identity is invalid")
        if not isinstance(entry, dict) or set(entry) != {"mission_id", "created_at", "expires_at"}:
            raise GameplayError("Stored mission completion control is invalid")
        number(entry["mission_id"])
        _timestamp(entry["created_at"])
        if entry["expires_at"]:
            _timestamp(entry["expires_at"])
        elif entry["expires_at"] != "":
            raise GameplayError("Stored mission completion expiration is invalid")
    game._mission_controls_validated = data
    return data


def validate_controls(game):
    data = _data(game, validate=True)
    if data is None:
        return
    for identifier in data["special_days"]:
        game.catalog.get("m_special_missions", int(identifier))
    for entry in data["completed"].values():
        game.catalog.get("m_missions", entry["mission_id"])


def _maximum_day(game, identifier):
    days = [number(row["day"], 1, 36500) for row in game.catalog.rows("m_special_mission_days")
            if row["m_special_mission_id"] == identifier]
    if not days:
        raise GameplayError("Special mission has no configured days", 503, 5036)
    return max(days)


def _offset(game, identifier, record):
    data = _data(game)
    entry = data["special_days"].get(str(identifier)) if data is not None else None
    if entry is None or entry["record_id"] != record["id"] or entry["start_at"] != record["start_at"]:
        return 0
    return entry["offset"]


def open_days(game, special_id, record=None):
    from .gameplay_mission_calendar import elapsed_days

    identifier = number(special_id)
    record = record or find(game.state, "t_special_missions", m_special_mission_id=identifier)
    if record is None:
        return 0
    maximum = _maximum_day(game, identifier)
    return min(maximum, max(0, elapsed_days(record["start_at"], game.now) + _offset(game, identifier, record)))


def set_open_days(evaluator, special_id, days):
    from .gameplay_mission_calendar import elapsed_days

    identifier = number(special_id)
    maximum = _maximum_day(evaluator, identifier)
    number(days, 0, maximum)
    record, _ = evaluator.special(identifier)
    if not available(record, evaluator.now):
        raise GameplayError("Special mission reward period has ended")
    data = _data(evaluator, create=True)
    offset = max(0, days - elapsed_days(record["start_at"], evaluator.now)) if days else 0
    data["special_days"][str(identifier)] = {"record_id": record["id"], "start_at": record["start_at"], "offset": offset}
    return open_days(evaluator, identifier, record)


def _special_record(evaluator, mission):
    if mission["mission_type"] != 7:
        return None
    groups = {row["m_special_mission_id"] for row in evaluator.catalog.rows("m_special_mission_days")
              if row["m_mission_id"] == mission["id"]}
    if len(groups) != 1:
        raise GameplayError("Special mission group is ambiguous", 503, 5036)
    return find(evaluator.state, "t_special_missions", m_special_mission_id=next(iter(groups)))


def _context(evaluator, mission):
    from .gameplay_mission_calendar import reset_day, week_start

    condition = [mission.get(key, 0) for key in ("id", "mission_type", "situation_type", "target_id", "sub_target_id",
                                                "require_value", "require_mission_id", "m_mission_term_id", "m_mission_pass_id")]
    scope, expiry = [condition, evaluator.key(mission)], None
    if mission["mission_type"] in (2, 8):
        expiry = datetime.combine(reset_day(evaluator.now) + timedelta(days=1), time(5), JST)
    elif mission["mission_type"] in (3, 6):
        expiry = datetime.combine(week_start(evaluator.now) + timedelta(days=7), time(5), JST)
    if mission.get("m_mission_pass_id"):
        from .gameplay_pass_statistics import mission_window

        start, end = mission_window(evaluator, mission)
        scope.append(["pass", mission["m_mission_pass_id"], start.isoformat(), end.isoformat()])
        expiry = end + timedelta(microseconds=1)
    if mission.get("m_mission_term_id"):
        term = evaluator.catalog.get("m_mission_terms", mission["m_mission_term_id"])
        scope.append(["term", term.get("start_at", ""), term.get("end_at", "")])
        if term.get("end_at") and not getattr(evaluator, "event", None) and not getattr(evaluator, "campaign", None):
            end = parse_timestamp(term["end_at"]) + timedelta(microseconds=1)
            expiry = min(expiry, end) if expiry is not None else end
    if getattr(evaluator, "event", None) is not None:
        identifier = evaluator.event["id"]
        instance = evaluator.progress.get("features", {}).get("events", {}).get("data", {}).get("instances", {}).get(str(identifier), {})
        scope.append(["event", identifier, instance.get("epoch", 1)])
    if getattr(evaluator, "campaign", None) is not None:
        identifier = evaluator.campaign["id"]
        entry = evaluator.progress.get("features", {}).get("encounter", {}).get("data", {}).get("campaigns", {}).get("entries", {}).get(str(identifier), {})
        scope.append(["campaign", identifier, entry.get("join_at", "")])
    special = _special_record(evaluator, mission)
    if special is not None:
        scope.append(["special", special["m_special_mission_id"], special["id"], special["start_at"], special["end_at"]])
        if special["end_at"]:
            expiry = parse_timestamp(special["end_at"]) + timedelta(microseconds=1)
    if mission["mission_type"] == 9 and mission["situation_type"] == 130000:
        data = evaluator.progress.get("features", {}).get("nether", {}).get("data", {})
        scope.append(["nether_loop", data.get("ticket_claims", {}).get(str(mission["id"]), 0)])
    encoded = json.dumps(scope, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest(), expiry


def completion_value(evaluator, mission):
    data = _data(evaluator)
    if data is None or not data["completed"]:
        return None
    key, _ = _context(evaluator, mission)
    entry = data["completed"].get(key)
    if entry is None or entry["mission_id"] != mission["id"]:
        return None
    if entry["expires_at"] and evaluator.now >= parse_timestamp(entry["expires_at"]):
        return None
    return mission["require_value"]


def mark_complete(evaluator, mission):
    if not evaluator.active(mission):
        raise GameplayError("Mission is not available")
    if mission["mission_type"] == 7:
        special = _special_record(evaluator, mission)
        if special is None or not special_window(evaluator, special["m_special_mission_id"])[0] or not available(special, evaluator.now):
            raise GameplayError("Special mission requires an active participation record")
    loop = mission["mission_type"] == 9 and mission["situation_type"] == 130000
    if not loop and evaluator.key(mission) in evaluator.progress["mission_claims"]:
        return False
    required = number(mission["require_value"], 0, 2 ** 63 - 1)
    if mission["situation_type"] in TIME_SITUATIONS and required == 0:
        raise GameplayError("Time mission has an invalid completion threshold", 503, 5036)
    key, expiry = _context(evaluator, mission)
    if expiry is not None and evaluator.now >= expiry:
        raise GameplayError("Mission completion period has ended")
    data = _data(evaluator, create=True)
    data["completed"] = {identity: entry for identity, entry in data["completed"].items()
                         if not entry["expires_at"] or evaluator.now < parse_timestamp(entry["expires_at"])}
    if key in data["completed"]:
        return False
    if len(data["completed"]) >= MAX_OVERRIDES:
        raise GameplayError("Mission completion controls exceed their limit")
    data["completed"][key] = {"mission_id": mission["id"], "created_at": evaluator.now.isoformat(),
                              "expires_at": expiry.isoformat() if expiry is not None else ""}
    return True


def clear_complete(evaluator, mission):
    data = _data(evaluator)
    if data is None:
        return False
    key, _ = _context(evaluator, mission)
    return data["completed"].pop(key, None) is not None


def project_special_records(game, records):
    data = _data(game)
    if data is None or not data["special_days"]:
        return records
    replacements = {}
    for record in rows(game.state, "t_special_missions"):
        identifier = record["m_special_mission_id"]
        entry = data["special_days"].get(str(identifier))
        if entry is None or entry["record_id"] != record["id"] or entry["start_at"] != record["start_at"]:
            continue
        offset = _offset(game, identifier, record)
        if not special_window(game, identifier)[0] or not available(record, game.now):
            continue
        projected = copy.deepcopy(record)
        projected["start_at"] = (parse_timestamp(record["start_at"]) - timedelta(days=offset)).isoformat()
        replacements[record["id"]] = projected
    if not replacements:
        return records
    projected = copy.deepcopy(records)
    table = projected.setdefault("t_special_missions", {"up": [], "down": []})
    retained = {record["id"]: record for record in table["up"]}
    retained.update(replacements)
    table["up"] = list(retained.values())
    table["down"] = [identifier for identifier in table["down"] if identifier not in replacements]
    return projected
