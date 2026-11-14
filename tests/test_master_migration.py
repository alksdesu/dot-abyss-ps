import json
import sqlite3

import msgpack
import pytest

from dotabyss_ps import master_migration as module
from dotabyss_ps.master_migration import MasterMigrationError, migrate, table_for
from dotabyss_ps.masterdata import MasterCatalog
from dotabyss_ps.storage import Store

OLD_CLIENT = {"package": "test.game", "version": "1.14.4", "metadata_sha256": "a" * 64}
NEW_CLIENT = {"package": "test.game", "version": "1.15.0", "metadata_sha256": "b" * 64}


def layout(client):
    return {
        "schema_version": 1,
        "client": client,
        "tables": {
            "m_items": [{"name": "id", "type": "long"}, {"name": "name", "type": "string"}],
            "m_abilities": [{"name": "id", "type": "long"}],
        },
        "compatibility": {"skip_unknown_tables": True, "unknown_table_evidence": "Verified native Skip branch", "defaulted_tails": {}},
    }


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "SUPPORTED_CLIENTS", (OLD_CLIENT, NEW_CLIENT))
    data = tmp_path / "data"
    store = Store(data / "local.sqlite3")
    catalog = MasterCatalog(data, store)

    def stage(name, client, tables):
        payload = tmp_path / f"{name}.msgpack"
        payload.write_bytes(msgpack.packb(tables, use_bin_type=True))
        schema = tmp_path / f"{name}-schema.json"
        schema.write_text(json.dumps(layout(client)), encoding="utf-8")
        return catalog.stage(payload, schema, name), schema

    old, _ = stage("old", OLD_CLIENT, {"m_items": [[1, "Sword"], [2, "Shield"]], "m_abilities": [[10], [11]]})
    new, schema = stage("new", NEW_CLIENT, {"m_items": [[1, "Sword"], [2, "Shield"], [3, "Bow"]], "m_abilities": [[10]]})
    catalog.activate(old["revision"])
    store.set_runtime({"resource_version": old["revision"], "application_version": "1.14.4", "bundle_version": "0.1.0"})
    return {"data": data, "store": store, "old": old["revision"], "new": new["revision"], "schema": schema}


def save(case, name, records):
    player = case["store"].login(name)["user_id"]
    state = {"policy_version": 5, "records": {table: {"up": rows, "down": []} for table, rows in records.items()}}
    with case["store"].connection() as db:
        db.execute("INSERT INTO game_states VALUES(?,1,?,?,?)", (player, case["old"], json.dumps(state), "today"))
        db.execute("INSERT INTO gameplay_progress VALUES(?,?,?)", (player, case["old"], "{}"))
    return player


def bindings(case):
    with case["store"].connection() as db:
        return {name: sorted(row[0] for row in db.execute(f"SELECT master_revision FROM {name}")) for name in ("game_states", "gameplay_progress")}


def test_saves_are_rebound_and_the_target_becomes_active(case):
    player = save(case, "keeper", {"t_items": [{"id": 1, "user_id": 1, "m_item_id": 2}], "t_abilities": [{"id": 1, "user_id": 1, "m_ability_id": 10}]})
    preview = migrate(case["data"], case["new"], schema_path=case["schema"])
    assert preview["status"] == "ready" and preview["bound"] == {"game_states": 1, "gameplay_progress": 1}
    assert preview["removed_rows"] == {"m_abilities": 1} and preview["dangling"] == []
    assert case["store"].master()["revision"] == case["old"]
    result = migrate(case["data"], case["new"], schema_path=case["schema"], apply=True)
    assert result["status"] == "applied"
    assert bindings(case) == {"game_states": [case["new"]], "gameplay_progress": [case["new"]]}
    assert case["store"].master()["revision"] == case["new"]
    runtime = case["store"].runtime()
    assert runtime["resource_version"] == case["new"] and runtime["application_version"] == "1.15.0" and runtime["bundle_version"] == "0.1.0"
    with sqlite3.connect(result["backup"]) as backup:
        assert backup.execute("SELECT master_revision FROM game_states WHERE profile_id=?", (player,)).fetchone()[0] == case["old"]
    assert migrate(case["data"], case["new"], schema_path=case["schema"])["status"] == "unchanged"


def test_saves_referencing_dropped_rows_block_the_migration(case):
    save(case, "holder", {"t_abilities": [{"id": 1, "user_id": 1, "m_ability_id": 11}]})
    before = bindings(case)
    with pytest.raises(MasterMigrationError, match="dropped"):
        migrate(case["data"], case["new"], schema_path=case["schema"], apply=True)
    assert bindings(case) == before and case["store"].master()["revision"] == case["old"]
    assert not list((case["data"] / "migration-backups").glob("*.sqlite3")) if (case["data"] / "migration-backups").exists() else True


def test_layout_changes_require_a_schema_migration(case, tmp_path):
    save(case, "player", {})
    widened = layout(NEW_CLIENT)
    widened["tables"]["m_abilities"].append({"name": "power", "type": "int"})
    schema = tmp_path / "widened-schema.json"
    schema.write_text(json.dumps(widened), encoding="utf-8")
    with pytest.raises(MasterMigrationError, match="schema migration"):
        migrate(case["data"], case["new"], schema_path=schema)


def test_unknown_or_foreign_targets_are_refused(case, monkeypatch):
    save(case, "player", {})
    with pytest.raises(MasterMigrationError, match="Unknown master revision"):
        migrate(case["data"], "local-ffffffffffffffff-000000000000", schema_path=case["schema"])
    monkeypatch.setattr(module, "SUPPORTED_CLIENTS", (OLD_CLIENT,))
    with pytest.raises(MasterMigrationError, match="supported client"):
        migrate(case["data"], case["new"], schema_path=case["schema"])


def test_reference_fields_resolve_to_plural_tables():
    names = {"m_items", "m_abilities", "m_gacha_boxes", "t_items"}
    assert table_for("m_item_id", names) == "m_items"
    assert table_for("m_ability_id", names) == "m_abilities"
    assert table_for("m_gacha_box_id", names) == "m_gacha_boxes"
    assert table_for("m_unknown_id", names) is None
    assert table_for("item_count", names) is None
