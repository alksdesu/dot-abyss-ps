import copy
import hashlib
import json

import pytest

from console.service_manager import ServiceManager
from dotabyss_ps import admin_launcher
from dotabyss_ps.gameplay_catalog import GameplayCatalog, MasterDataError
from dotabyss_ps.masterdata import canonical_json
from dotabyss_ps.release_manifest import default_data_dir, default_schema_path, load_manifest
from dotabyss_ps.server_master_bindings import SERVER_TABLES, bound_fields
from dotabyss_ps.storage import Store
from test_assets import asset_setup


def release_workspace(root):
    manifest = load_manifest()
    profile = manifest["releases"][manifest["default_release"]]
    profile["paths"]["data_directory"] = "state/chosen"
    profile["paths"]["local_release"] = "pc/releases/chosen.json"
    schema = {"tables": {}, "client": manifest["supported_clients"][-1]}
    schema_path = root / "layouts/chosen.json"
    schema_path.parent.mkdir(parents=True)
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    profile["build"]["schema"] = {"path": "layouts/chosen.json", "sha256": hashlib.sha256(canonical_json(schema)).hexdigest()}
    path = root / "pc/releases/manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return profile, schema_path


def test_service_and_launcher_resolve_the_same_release_paths(tmp_path):
    profile, schema = release_workspace(tmp_path)
    data = default_data_dir(tmp_path)
    data.mkdir(parents=True)
    store = Store(data / "local.sqlite3")
    interpreter = tmp_path / ".venv/Scripts/python.exe"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_bytes(b"test interpreter; never executed")
    manager = ServiceManager("http://127.0.0.1:18083", data, project_root=tmp_path)
    assert manager._validate() == (interpreter, schema)
    launcher = admin_launcher.GameLauncher(store, None, project_root=tmp_path)
    assert launcher.release_path == tmp_path / "pc/releases/chosen.json"
    assert launcher.release_profile["build"]["schema"]["path"] == "layouts/chosen.json"
    assert default_schema_path(tmp_path) == schema
    assert data == tmp_path / "state/chosen"


def test_asset_status_exposes_only_verified_content_descriptors(asset_setup):
    context = asset_setup
    staged = context.stage()
    context.assets.activate(staged["revision"])
    active = context.assets.status()["active"]
    for key in ("catalog", "catalog_hash"):
        assert set(active[key]) == {"relative_path", "sha256", "bytes"}
        assert active[key]["sha256"] == staged[key]["sha256"]
    assert active["catalog_hash_value"] == "c" * 32
    assert "entries" not in active and "source" not in active


def test_reviewed_server_layout_accepts_content_changes_and_new_rows():
    name = "m_home_greeting_rewards"
    values = [[1, 2, 10, 0, 50]]
    original = copy.deepcopy(values)
    assert bound_fields(name, values) == ["id", "group_id", "content_type", "content_id", "amount"]
    values[0][-1] += 10
    values.append([2, 3, 10, 0, 20])
    catalog = GameplayCatalog({name: values}, {"tables": {}})
    assert catalog.get(name, 1)["amount"] == 60
    assert catalog.get(name, 2)["amount"] == 20
    assert original == [[1, 2, 10, 0, 50]]


@pytest.mark.parametrize("value", [True, None, "10", 1.5, 2 ** 63, -(2 ** 63) - 1])
def test_server_layout_rejects_wrong_types_and_overflow(value):
    with pytest.raises(MasterDataError, match="reviewed type"):
        bound_fields("m_home_greeting_rewards", [[1, 2, 10, 0, value]])


@pytest.mark.parametrize("values", [None, {}, [[1, 2]], [[1, 2, 10, 0, 10, 99]], ["invalid"]])
def test_server_layout_rejects_unreviewed_shape(values):
    with pytest.raises(MasterDataError):
        bound_fields("m_home_greeting_rewards", values)


def test_unknown_server_table_is_not_inferred():
    with pytest.raises(MasterDataError, match="requires review"):
        bound_fields("m_future_rewards", [[1, 2, 3]])


def test_enemy_lottery_keeps_reviewed_long_identifiers():
    row = [45000011010242, 450000010602, 10, 0, 0, 450000110247]
    fields = bound_fields("m_dungeon_floor_part_enemy_lotteries", [row])
    assert dict(zip(fields, row))["enemy_group_id"] == 450000110247
    row[-1] = 2 ** 63
    with pytest.raises(MasterDataError, match="reviewed type"):
        bound_fields("m_dungeon_floor_part_enemy_lotteries", [row])


@pytest.mark.parametrize("name", sorted(SERVER_TABLES))
def test_all_reviewed_server_tables_keep_type_checks(name):
    row = [0] * len(SERVER_TABLES[name]["fields"])
    assert bound_fields(name, [row])
    row[-1] = False
    with pytest.raises(MasterDataError, match="reviewed type"):
        bound_fields(name, [row])
