import copy
import hashlib
import json

import pytest

from dotabyss_ps import release_manifest as releases
from tools.generate_release_bindings import build_fingerprint, generate, render_client_profile


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def manifest_case(tmp_path):
    root = tmp_path / "project"
    manifest = releases.load_manifest()
    profile = manifest["releases"][manifest["default_release"]]
    schema = {"schema_version": 1, "tables": {"m_items": [{"name": "id", "type": "long"}]}}
    profile["build"]["schema"]["sha256"] = hashlib.sha256(releases.canonical_json(schema)).hexdigest()
    write_json(root / profile["build"]["schema"]["path"], schema)
    write_json(root / releases.MANIFEST_PATH, manifest)
    return root, manifest, profile


def save_manifest(case):
    root, manifest, _ = case
    write_json(root / releases.MANIFEST_PATH, manifest)


def test_default_selection_and_paths_use_selected_root(manifest_case):
    root, manifest, profile = manifest_case
    assert releases.default_release(root) == profile
    assert releases.default_data_dir(root) == root / profile["paths"]["data_directory"]
    assert releases.default_client_dir(root) == (root / profile["paths"]["client_directory"]).resolve()
    assert releases.local_release_path(root) == root / profile["paths"]["local_release"]
    assert releases.default_schema_path(root) == root / profile["build"]["schema"]["path"]
    loaded = releases.default_release(root)
    loaded["build"]["application_version"] = "changed"
    assert releases.default_release(root) == profile


def test_explicit_root_never_falls_back_to_checkout(tmp_path):
    with pytest.raises(releases.ReleaseManifestError, match="missing"):
        releases.default_release(tmp_path)


def test_default_root_is_independent_of_working_directory(tmp_path, monkeypatch):
    expected = releases.default_release()
    monkeypatch.chdir(tmp_path)
    assert releases.default_release() == expected


def test_manifest_loading_does_not_open_schema(manifest_case):
    root, _, profile = manifest_case
    (root / profile["build"]["schema"]["path"]).unlink()
    assert releases.default_release(root) == profile
    with pytest.raises(releases.ReleaseManifestError, match="missing"):
        releases.default_schema_path(root)


def test_schema_hash_uses_canonical_json_and_detects_changes(manifest_case):
    root, _, profile = manifest_case
    path = root / profile["build"]["schema"]["path"]
    schema = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(schema, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    assert releases.default_schema_path(root) == path
    schema["tables"]["m_items"][0]["type"] = "string"
    write_json(path, schema)
    with pytest.raises(releases.ReleaseManifestError, match="Schema fingerprint"):
        releases.default_schema_path(root)


@pytest.mark.parametrize("key,value", [
    ("data_directory", "../outside"), ("local_release", "C:/outside.json"),
    ("legacy_projection", "pc/releases/../../outside.json"), ("client_directory", "../other-game/client"),
])
def test_release_paths_reject_escapes(manifest_case, key, value):
    manifest_case[2]["paths"][key] = value
    save_manifest(manifest_case)
    with pytest.raises(releases.ReleaseManifestError, match="relative"):
        releases.default_release(manifest_case[0])


def test_duplicate_keys_and_nonfinite_values_are_rejected(manifest_case):
    root, _, _ = manifest_case
    path = root / releases.MANIFEST_PATH
    for content in ('{"format_version":1,"format_version":1}', '{"format_version":NaN}'):
        path.write_text(content, encoding="utf-8")
        with pytest.raises(releases.ReleaseManifestError, match="Invalid release configuration"):
            releases.load_manifest(root)


@pytest.mark.parametrize("change", [
    lambda manifest, profile: manifest.update(default_release="missing"),
    lambda manifest, profile: profile["build"].update(release="different"),
    lambda manifest, profile: profile["build"]["proxy"].update(unity_player_sha256="f" * 64),
    lambda manifest, profile: profile["build"]["transport"].update(catalog_path="resources/elsewhere/catalog.bin"),
    lambda manifest, profile: profile["build"]["transport"].update(catalog_hash_path=profile["build"]["transport"]["catalog_path"]),
    lambda manifest, profile: profile["build"]["transport"].update(remote_base=profile["build"]["transport"]["remote_base"].replace("https:", "http:")),
    lambda manifest, profile: profile["content"]["profile_seeds"].append(copy.deepcopy(profile["content"]["profile_seeds"][0])),
    lambda manifest, profile: profile["paths"].update(legacy_projection="pc/releases/manifest.json"),
    lambda manifest, profile: profile["build"].update(executable="C:game.exe"),
])
def test_inconsistent_manifest_bindings_are_rejected(manifest_case, change):
    root, manifest, profile = manifest_case
    change(manifest, profile)
    save_manifest(manifest_case)
    with pytest.raises(releases.ReleaseManifestError):
        releases.load_manifest(root)


def test_local_release_only_overlays_matching_seed_sources(manifest_case):
    root, _, profile = manifest_case
    local = releases.legacy_release(profile)
    local["profile_seeds"][0]["source"] = "E:/my-cache/catalog.bin"
    local["profile_seeds"][1]["source"] = "E:/stale-cache/catalog.hash"
    local["profile_seeds"][1]["sha256"] = "0" * 64
    write_json(root / profile["paths"]["local_release"], local)
    loaded = releases.load_local_release(root)
    assert loaded["profile_seeds"][0]["source"] == "E:/my-cache/catalog.bin"
    assert loaded["profile_seeds"][1] == profile["content"]["profile_seeds"][1]
    assert releases.default_release(root) == profile


@pytest.mark.parametrize("field", ["application_version", "source_fingerprints", "settings"])
def test_local_release_cannot_override_client_structure(manifest_case, field):
    root, _, profile = manifest_case
    local = releases.legacy_release(profile)
    local[field] = "unreviewed"
    write_json(root / profile["paths"]["local_release"], local)
    with pytest.raises(releases.ReleaseManifestError, match="structure differs"):
        releases.load_local_release(root)


def test_content_updates_do_not_change_compiled_client_binding(manifest_case):
    _, _, profile = manifest_case
    original = render_client_profile(profile)
    original_fingerprint = build_fingerprint(profile)
    changed = copy.deepcopy(profile)
    changed["content"]["catalog_version_hash"] = "a" * 32
    for index, seed in enumerate(changed["content"]["profile_seeds"]):
        seed["sha256"] = str(index) * 64
        seed["source"] = "E:/new-content/seed.dat"
    assert render_client_profile(changed) == original
    assert build_fingerprint(changed) == original_fingerprint
    assert "MasterHash" not in original and "CatalogVersionHash" not in original
    assert profile["content"]["catalog_version_hash"] not in original
    for seed in profile["content"]["profile_seeds"]:
        assert seed["sha256"] not in original
    changed["build"]["transport"]["bundle_version"] = "new-bundle"
    assert build_fingerprint(changed) != original_fingerprint


def test_client_binding_includes_reviewed_isolated_identity(manifest_case):
    _, _, profile = manifest_case
    source = render_client_profile(profile)
    assert 'IdentityCompany = "' + profile["build"]["identity"]["company"] + '";' in source
    assert 'IdentityProduct = "' + profile["build"]["identity"]["product"] + '";' in source
    changed = copy.deepcopy(profile)
    changed["build"]["identity"]["company"] = "AlternateCompany"
    changed["build"]["identity"]["product"] = "AlternateProduct"
    changed_source = render_client_profile(changed)
    assert 'IdentityCompany = "AlternateCompany";' in changed_source
    assert 'IdentityProduct = "AlternateProduct";' in changed_source
    assert build_fingerprint(changed) != build_fingerprint(profile)


def test_generator_updates_projection_and_check_is_read_only(manifest_case):
    root, _, profile = manifest_case
    path = root / profile["paths"]["legacy_projection"]
    with pytest.raises(releases.ReleaseManifestError, match="missing or stale"):
        generate(root, check=True)
    assert not path.exists()
    assert generate(root)["changed"] == [str(path)]
    assert json.loads(path.read_text(encoding="utf-8")) == releases.legacy_release(profile)
    before = path.stat().st_mtime_ns
    assert generate(root, check=True) == {"changed": []}
    assert generate(root) == {"changed": []}
    assert path.stat().st_mtime_ns == before


def test_generator_writes_csharp_and_checks_staleness(manifest_case):
    root, _, profile = manifest_case
    path = root / "pc/obj/ClientBuildProfile.g.cs"
    assert generate(root, path)["changed"] is True
    source = path.read_text(encoding="utf-8")
    assert source == render_client_profile(profile)
    assert 'CatalogPath = "/' in source
    assert 'internal const int ProxyEntryRva = ' in source
    assert generate(root, path, check=True)["changed"] is False
    path.write_text(source + "stale", encoding="utf-8")
    with pytest.raises(releases.ReleaseManifestError, match="missing or stale"):
        generate(root, path, check=True)
    assert path.read_text(encoding="utf-8").endswith("stale")


def test_generator_rejects_unknown_profile_without_output(manifest_case):
    root, _, _ = manifest_case
    path = root / "pc/obj/unreviewed.cs"
    with pytest.raises(releases.ReleaseManifestError, match="Unknown"):
        generate(root, path, profile_id="unreviewed")
    assert not path.exists()


def test_server_only_bindings_record_column_contracts(manifest_case):
    root, manifest, _ = manifest_case
    binding = next(iter(manifest["server_master_bindings"].values()))
    binding["fields"][0]["type"] = "string"
    save_manifest(manifest_case)
    with pytest.raises(releases.ReleaseManifestError, match="field contract"):
        releases.load_manifest(root)


def test_supported_pc_identity_is_derived_and_round_trips(manifest_case):
    root, manifest, profile = manifest_case
    package = profile["build"]["launcher_product_id"]
    historical = [client for client in manifest["supported_clients"] if client["package"] != package]
    manifest["supported_clients"] = historical
    save_manifest(manifest_case)
    loaded = releases.load_manifest(root)
    assert loaded["supported_clients"][:-1] == historical
    expected = {"package": package, "version": profile["build"]["application_version"],
                "metadata_sha256": next(value for key, value in profile["build"]["source_fingerprints"].items()
                                        if key.endswith("/il2cpp_data/Metadata/global-metadata.dat"))}
    assert loaded["supported_clients"][-1] == expected
    loaded["supported_clients"].append(copy.deepcopy(expected))
    write_json(root / releases.MANIFEST_PATH, loaded)
    assert releases.load_manifest(root)["supported_clients"] == historical + [expected]


def test_conflicting_derived_pc_identity_is_rejected(manifest_case):
    root, manifest, profile = manifest_case
    pc = next(client for client in manifest["supported_clients"]
              if client["package"] == profile["build"]["launcher_product_id"])
    pc["metadata_sha256"] = "0" * 64
    save_manifest(manifest_case)
    with pytest.raises(releases.ReleaseManifestError, match="conflicts"):
        releases.load_manifest(root)


def test_changing_build_alone_updates_derived_pc_identity(manifest_case):
    root, manifest, profile = manifest_case
    package = profile["build"]["launcher_product_id"]
    manifest["supported_clients"] = [client for client in manifest["supported_clients"] if client["package"] != package]
    profile["build"]["application_version"] = "next-reviewed-build"
    metadata_path = next(key for key in profile["build"]["source_fingerprints"]
                         if key.endswith("/il2cpp_data/Metadata/global-metadata.dat"))
    profile["build"]["source_fingerprints"][metadata_path] = "f" * 64
    save_manifest(manifest_case)
    assert releases.load_manifest(root)["supported_clients"][-1] == {
        "package": package, "version": "next-reviewed-build", "metadata_sha256": "f" * 64,
    }


def test_explicit_generator_output_cannot_overwrite_inputs_or_source(manifest_case):
    root, _, profile = manifest_case
    source = root / "pc/src/ClientIdentity.cs"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("internal class ClientIdentity {}", encoding="utf-8")
    local = root / profile["paths"]["local_release"]
    write_json(local, releases.legacy_release(profile))
    paths = [root / releases.MANIFEST_PATH, root / profile["build"]["schema"]["path"], local, source]
    for path in paths:
        before = path.read_bytes()
        with pytest.raises(releases.ReleaseManifestError, match="overwrite"):
            generate(root, path)
        assert path.read_bytes() == before


def test_generator_checks_selected_nondefault_schema(manifest_case):
    root, manifest, profile = manifest_case
    alternate = copy.deepcopy(profile)
    alternate["build"]["release"] = "alternate-build"
    alternate["build"]["schema"]["path"] = "artifacts/alternate-schema.json"
    alternate["paths"]["local_release"] = "pc/releases/alternate.json"
    alternate["paths"]["legacy_projection"] = "pc/releases/alternate.example.json"
    manifest["releases"]["alternate-build"] = alternate
    wrong_schema = {"schema_version": 1, "tables": {"changed": []}}
    write_json(root / alternate["build"]["schema"]["path"], wrong_schema)
    save_manifest(manifest_case)
    output = root / "pc/obj/alternate.g.cs"
    with pytest.raises(releases.ReleaseManifestError, match="Schema fingerprint"):
        generate(root, output, profile_id="alternate-build")
    assert not output.exists()
    alternate["build"]["schema"]["sha256"] = hashlib.sha256(releases.canonical_json(wrong_schema)).hexdigest()
    save_manifest(manifest_case)
    assert generate(root, output, profile_id="alternate-build")["changed"] is True
