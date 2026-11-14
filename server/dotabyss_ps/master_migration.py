from __future__ import annotations

import argparse
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import msgpack

from .masterdata import MAX_PAYLOAD_BYTES, MasterCatalog, MasterDataError, inspect_payload, unique_map
from .newgame import SUPPORTED_CLIENTS
from .protocol import decode_json
from .release_manifest import default_data_dir, default_schema_path
from .storage import Store

BOUND_TABLES = ("game_states", "gameplay_progress")
PLURALS = (lambda stem: stem + "s", lambda stem: stem + "es", lambda stem: stem[:-1] + "ies" if stem.endswith("y") else None)


class MasterMigrationError(ValueError):
    pass


def _tables(payload: bytes) -> dict:
    return msgpack.unpackb(payload, raw=False, strict_map_key=True, object_pairs_hook=unique_map,
                           max_map_len=2000, max_array_len=500000, max_str_len=16 * 1024 * 1024,
                           max_bin_len=MAX_PAYLOAD_BYTES, max_ext_len=0)


def _ids(tables: dict, schema: dict, name: str) -> set:
    columns = [column["name"] for column in schema["tables"][name]]
    if "id" not in columns or name not in tables:
        return set()
    index = columns.index("id")
    return {row[index] for row in tables[name] if len(row) > index}


def removed_rows(source: dict, target: dict, schema: dict) -> dict[str, set]:
    removed = {}
    for name in schema["tables"]:
        if name not in source:
            continue
        if name not in target:
            raise MasterMigrationError("Target master dropped a required table: " + name)
        gone = _ids(source, schema, name) - _ids(target, schema, name)
        if gone:
            removed[name] = gone
    return removed


def table_for(field: str, names) -> str | None:
    if not field.startswith("m_") or not field.endswith("_id"):
        return None
    stem = field[:-3]
    for plural in PLURALS:
        candidate = plural(stem)
        if candidate in names:
            return candidate
    return None


def dangling_references(states: list[tuple[int, dict]], removed: dict[str, set]) -> list[dict]:
    if not removed:
        return []
    dangling = []
    for profile_id, state in states:
        for table, container in state.get("records", {}).items():
            for row in container.get("up", []):
                for field, value in row.items():
                    target = table_for(field, removed)
                    if target is not None and value in removed[target]:
                        dangling.append({"profile_id": profile_id, "table": table, "field": field, "value": value, "master_table": target})
    return dangling


def _bound_rows(db: sqlite3.Connection, revision: str) -> dict[str, list[sqlite3.Row]]:
    return {name: db.execute(f"SELECT * FROM {name} WHERE master_revision=?", (revision,)).fetchall() for name in BOUND_TABLES}


def _state(row: sqlite3.Row) -> dict:
    state = decode_json(row["contents"])
    if not isinstance(state, dict) or not isinstance(state.get("records"), dict):
        raise MasterMigrationError("Stored game state is not a record map")
    return state


def _backup(database: Path, source: str, target: str) -> Path:
    directory = database.parent / "migration-backups"
    directory.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = directory / f"master-{stamp}-{source.split('-')[1][:8]}-to-{target.split('-')[1][:8]}.sqlite3"
    if path.exists():
        raise MasterMigrationError("A migration backup already exists at " + str(path))
    with closing(sqlite3.connect(database, timeout=10)) as live, closing(sqlite3.connect(path)) as copy:
        live.backup(copy)
    return path


def migrate(data_dir: Path, target: str, *, schema_path: Path, apply: bool = False) -> dict:
    data_dir = Path(data_dir).resolve()
    database = data_dir / "local.sqlite3"
    if not database.is_file():
        raise MasterMigrationError("A local state database is required")
    store = Store(database)
    catalog = MasterCatalog(data_dir, store)
    active = store.master()
    if active is None:
        raise MasterMigrationError("No master is active; use setup for a fresh data directory")
    result = {"data_dir": str(data_dir), "from": active["revision"], "to": target}
    if active["revision"] == target:
        return {**result, "status": "unchanged"}
    try:
        target_record, target_payload = catalog.read(target)
        _, source_payload = catalog.read(active["revision"])
    except MasterDataError as error:
        raise MasterMigrationError(str(error)) from error
    if target_record["client"] not in SUPPORTED_CLIENTS or target_record["client"]["package"] != active["client"]["package"]:
        raise MasterMigrationError("The target master does not belong to a supported client of the same platform")
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    try:
        if inspect_payload(target_payload, schema)["revision"] != target:
            raise MasterMigrationError("The schema file does not describe the target master")
        inspect_payload(source_payload, schema)
    except MasterDataError as error:
        raise MasterMigrationError("The target master uses another table layout; a schema migration is required: " + str(error)) from error
    removed = removed_rows(_tables(source_payload), _tables(target_payload), schema)
    with store.connection() as db:
        bound = _bound_rows(db, active["revision"])
        other = {name: db.execute(f"SELECT COUNT(*) FROM {name} WHERE master_revision<>?", (active["revision"],)).fetchone()[0]
                 for name in BOUND_TABLES}
    if any(other.values()):
        raise MasterMigrationError("Some saves are not bound to the active master: " + json.dumps(other))
    states = [(row["profile_id"], _state(row)) for row in bound["game_states"]]
    dangling = dangling_references(states, removed)
    result.update(status="ready", bound={name: len(rows) for name, rows in bound.items()},
                  removed_rows={name: len(ids) for name, ids in sorted(removed.items())}, dangling=dangling[:20],
                  application_version=target_record["client"]["version"])
    if dangling:
        raise MasterMigrationError("Saves reference master rows the target dropped: " + json.dumps(dangling[:5], ensure_ascii=False))
    if not apply:
        return result
    backup = _backup(database, active["revision"], target)
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        current = db.execute("SELECT value FROM settings WHERE name='active_master'").fetchone()
        if current is None or current["value"] != active["revision"]:
            raise MasterMigrationError("The active master changed while the migration was being prepared")
        for name, rows in bound.items():
            updated = db.execute(f"UPDATE {name} SET master_revision=? WHERE master_revision=?", (target, active["revision"]))
            if updated.rowcount != len(rows):
                raise MasterMigrationError(f"{name} changed while the migration was being prepared")
        row = db.execute("SELECT value FROM settings WHERE name='runtime'").fetchone()
        runtime = decode_json(row["value"]) if row else {}
        if not isinstance(runtime, dict):
            raise MasterMigrationError("Stored runtime settings are invalid")
        runtime.update(resource_version=target, application_version=target_record["client"]["version"])
        db.execute("INSERT INTO settings VALUES ('active_master',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (target,))
        db.execute("INSERT INTO settings VALUES ('runtime',?) ON CONFLICT(name) DO UPDATE SET value=excluded.value", (json.dumps(runtime),))
    return {**result, "status": "applied", "backup": str(backup)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebind every local save from the active master revision to a staged one")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--to", required=True, help="staged master revision to activate")
    parser.add_argument("--schema", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir if args.data_dir is not None else default_data_dir(), args.to,
                         schema_path=args.schema if args.schema is not None else default_schema_path(), apply=args.apply)
    except (MasterMigrationError, OSError, sqlite3.Error, ValueError) as error:
        parser.exit(1, "Master migration failed: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
