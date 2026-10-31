import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import msgpack

from pc import setup as pc_setup
from pc.prepare_client import prepare
from test_pc_setup import inspect as inspect_setup, save_state, setup_case, state_rows


spec = importlib.util.spec_from_file_location("pc_setup_client", Path(__file__).parents[1] / "pc/setup_client.py")
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def seeds(tmp_path):
    cache = tmp_path / "cache"
    catalog = write(cache / "com.unity.addressables/local-number.bin", b"matching catalog")
    master = write(cache / "DownloadCache/master.dat", b"matching master")
    release = {"profile_seeds": [
        {"relative": "com.unity.addressables/expected-number.bin", "source": "original/path", "sha256": setup._digest(catalog)},
        {"relative": "DownloadCache/master.dat", "source": "another/path", "sha256": setup._digest(master)}]}
    return SimpleNamespace(cache=cache, release=release, catalog=catalog, master=master)


def test_seed_resolution_accepts_local_numbering_without_mutating_release(seeds):
    c = seeds
    original = copy.deepcopy(c.release)
    result = setup.resolve_seeds(c.release, c.cache)
    assert c.release == original and result is not c.release
    assert [item["source"] for item in result["profile_seeds"]] == [str(c.catalog), str(c.master)]
    assert result["profile_seeds"][0]["relative"] == "com.unity.addressables/expected-number.bin"


def test_seed_resolution_prefers_declared_filename(seeds, monkeypatch):
    preferred = seeds.catalog.with_name("expected-number.bin")
    preferred.write_bytes(seeds.catalog.read_bytes())
    monkeypatch.setattr(setup, "MAX_CACHE_FILES", 0)
    assert setup.resolve_seeds(seeds.release, seeds.cache)["profile_seeds"][0]["source"] == str(preferred)


@pytest.mark.parametrize("location", ["nested/local-number.bin", "other.hash", "wrong.bin"])
def test_seed_resolution_rejects_wrong_suffix_directory_and_version(seeds, location):
    payload = seeds.catalog.read_bytes()
    seeds.catalog.unlink()
    write(seeds.catalog.parent / location, payload if location != "wrong.bin" else b"wrong version")
    with pytest.raises(ValueError, match="missing or belongs to another version"):
        setup.resolve_seeds(seeds.release, seeds.cache)


def test_seed_resolution_bounds_directory_scan(seeds, monkeypatch):
    monkeypatch.setattr(setup, "MAX_CACHE_FILES", 1)
    write(seeds.catalog.parent / "another.bin", b"another catalog")
    with pytest.raises(ValueError, match="too many files"):
        setup.resolve_seeds(seeds.release, seeds.cache)


@pytest.mark.parametrize("relative", ["../outside.bin", "com.unity.addressables/../../outside.bin", "C:/outside.bin"])
def test_seed_resolution_rejects_paths_outside_cache(seeds, relative):
    seeds.release["profile_seeds"][0]["relative"] = relative
    with pytest.raises(ValueError, match="relative path"):
        setup.resolve_seeds(seeds.release, seeds.cache)


def test_seed_resolution_rejects_directory_in_place_of_file(seeds):
    (seeds.catalog.parent / "expected-number.bin").mkdir()
    with pytest.raises(ValueError, match="regular file"):
        setup.resolve_seeds(seeds.release, seeds.cache)


@pytest.fixture
def plugin(setup_case, monkeypatch):
    case = setup_case
    project, client = case.root, case.client
    prepare(case.source, client, inspect_setup(case)["release"], case.profile)
    write(project / "pc/DotAbyss.Local.Pc.csproj",
          b'<Project><PropertyGroup><TargetFramework>net6.0</TargetFramework></PropertyGroup></Project>')
    source = write(project / "pc/src/Plugin.cs", b"class Plugin {}")
    executable = client / "game.exe"
    write(client / "BepInEx/core/runtime.dll", b"runtime")
    interop = write(client / "BepInEx/interop/Project.dll", b"interop")
    target = write(client / "BepInEx/plugins/DotAbyss.Local.Pc/DotAbyss.Local.Pc.dll", b"old plugin")
    output = project / "pc/bin/Release/net6.0/DotAbyss.Local.Pc.dll"
    config = write(target.with_name("pc-local.json"), b"keep configuration")
    calls, processes = [], []
    monkeypatch.setattr(setup, "game_processes", lambda _: list(processes))
    def run(command, **kwargs):
        calls.append((command, kwargs))
        write(output, b"new plugin")
        return SimpleNamespace(returncode=0, stdout="build succeeded", stderr="")
    monkeypatch.setattr(setup.subprocess, "run", run)
    return SimpleNamespace(project=project, client=client, target=target, output=output, config=config,
                           executable=executable, interop=interop, calls=calls, processes=processes, source=source, case=case)


def test_plugin_build_uses_client_assemblies_and_backups_old_plugin(plugin):
    c = plugin
    result = setup.install_plugin(c.project, c.client)
    assert c.target.read_bytes() == b"new plugin"
    assert Path(result["backup"]).read_bytes() == b"old plugin"
    assert Path(result["backup"]).is_relative_to(c.project / "artifacts/setup")
    assert result["sha256"] == hashlib.sha256(b"new plugin").hexdigest() and result["changed"]
    assert "-p:ClientDir=" + str(c.client) in c.calls[0][0]
    assert c.config.read_bytes() == b"keep configuration"
    assert not (c.client / "toolchain").exists()
    repeated = setup.install_plugin(c.project, c.client)
    assert repeated["changed"] is False and repeated["backup"] is None and repeated["built"] is False
    assert len(c.calls) == 1


def test_first_plugin_install_has_no_backup(plugin):
    c = plugin
    c.target.unlink()
    result = setup.install_plugin(c.project, c.client)
    assert result["changed"] and result["backup"] is None and c.target.read_bytes() == b"new plugin"


def test_failed_build_leaves_previous_plugin_and_configuration(plugin, monkeypatch):
    c = plugin
    monkeypatch.setattr(setup.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="compiler error", stderr=""))
    with pytest.raises(ValueError, match="compiler error"):
        setup.install_plugin(c.project, c.client)
    assert c.target.read_bytes() == b"old plugin" and c.config.read_bytes() == b"keep configuration"
    assert not (c.project / "artifacts/setup").exists()


def test_plugin_install_requires_interop_before_building(plugin):
    c = plugin
    c.interop.unlink()
    with pytest.raises(ValueError, match="Project.dll"):
        setup.install_plugin(c.project, c.client)
    assert not c.calls and c.target.read_bytes() == b"old plugin"


@pytest.mark.parametrize("starts_during_build", [False, True])
def test_plugin_install_does_not_modify_running_game(plugin, monkeypatch, starts_during_build):
    c = plugin
    if starts_during_build:
        run = setup.subprocess.run
        def start_game(*args, **kwargs):
            result = run(*args, **kwargs)
            c.processes.append(SimpleNamespace(pid=123))
            return result
        monkeypatch.setattr(setup.subprocess, "run", start_game)
    else:
        c.processes.append(SimpleNamespace(pid=123))
    with pytest.raises(ValueError, match="Exit the local game"):
        setup.install_plugin(c.project, c.client)
    assert c.target.read_bytes() == b"old plugin"
    assert len(c.calls) == int(starts_during_build)


def test_plugin_atomic_deploy_failure_preserves_previous_plugin(plugin, monkeypatch):
    c = plugin
    atomic = setup.atomic_bytes
    def fail_target(path, payload):
        if path == c.target:
            raise OSError("destination locked")
        return atomic(path, payload)
    monkeypatch.setattr(setup, "atomic_bytes", fail_target)
    with pytest.raises(OSError, match="locked"):
        setup.install_plugin(c.project, c.client)
    assert c.target.read_bytes() == b"old plugin"
    assert next((c.project / "artifacts/setup").rglob("*.dll")).read_bytes() == b"old plugin"


def test_content_update_reuses_plugin_and_does_not_overwrite_old_saves(plugin, monkeypatch):
    c, case = plugin, plugin.case
    monkeypatch.setattr(pc_setup, "install_plugin", setup.install_plugin)
    first = pc_setup.initialize(case.root, source=case.source, progress=lambda _: None)
    store = save_state(case, first["master_revision"])
    before = state_rows(store)
    plugin_before = c.target.read_bytes()
    assert first["plugin"]["built"] and len(c.calls) == 1

    case.master.write_bytes(msgpack.packb({"m_items": [[1], [2]]}))
    case.catalog.write_bytes(case.catalog.read_bytes() + b"content-only-update")
    case.catalog_hash.write_bytes(b"d" * 32)
    contents = case.release_profile["content"]
    contents["catalog_version_hash"] = "d" * 32
    updated = {".bin": case.catalog, ".hash": case.catalog_hash, ".dat": case.master}
    for seed in contents["profile_seeds"]:
        seed["sha256"] = hashlib.sha256(updated[Path(seed["relative"]).suffix].read_bytes()).hexdigest()
    case.manifest_path.write_text(json.dumps(case.manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="another master revision"):
        pc_setup.initialize(case.root, progress=lambda _: None)
    assert state_rows(store) == before and c.target.read_bytes() == plugin_before and len(c.calls) == 1

    second = pc_setup.initialize(case.root, data_dir=case.root / "data-content-b", progress=lambda _: None)
    assert second["master_revision"] != first["master_revision"]
    assert second["plugin"]["built"] is False and second["plugin"]["changed"] is False
    assert len(c.calls) == 1 and c.target.read_bytes() == plugin_before and state_rows(store) == before


@pytest.mark.parametrize("changed", ["source", "interop", "core", "generator", "targets", "binding"])
def test_changed_build_inputs_require_recompilation(plugin, changed):
    c = plugin
    setup.install_plugin(c.project, c.client)
    paths = {"source": c.source, "interop": c.interop, "core": c.client / "BepInEx/core/runtime.dll",
             "generator": c.project / "tools/generate_release_bindings.py",
             "targets": c.project / "pc/ClientBuildProfile.targets"}
    if changed == "binding":
        c.case.release_profile["build"]["proxy"]["entry_rva"] += 1
        c.case.manifest_path.write_text(json.dumps(c.case.manifest), encoding="utf-8")
    else:
        write(paths[changed], b"changed build input")
    result = setup.install_plugin(c.project, c.client)
    assert result["built"] and len(c.calls) == 2


def test_modified_installed_plugin_cannot_reuse_build_stamp(plugin):
    c = plugin
    setup.install_plugin(c.project, c.client)
    c.target.write_bytes(b"modified plugin")
    result = setup.install_plugin(c.project, c.client)
    assert result["built"] and len(c.calls) == 2 and c.target.read_bytes() == b"new plugin"


def test_schema_formatting_does_not_change_compilation_inputs(plugin):
    c = plugin
    setup.install_plugin(c.project, c.client)
    c.case.schema_path.write_text(json.dumps(c.case.schema, indent=4), encoding="utf-8")
    result = setup.install_plugin(c.project, c.client)
    assert not result["built"] and len(c.calls) == 1


def test_build_input_change_during_compilation_preserves_installed_plugin(plugin, monkeypatch):
    c = plugin
    run = setup.subprocess.run

    def changed_input(*args, **kwargs):
        result = run(*args, **kwargs)
        c.source.write_bytes(b"changed during compilation")
        return result

    monkeypatch.setattr(setup.subprocess, "run", changed_input)
    with pytest.raises(ValueError, match="inputs changed during compilation"):
        setup.install_plugin(c.project, c.client)
    assert c.target.read_bytes() == b"old plugin"
    assert not c.target.with_name("build-inputs.json").exists()


def test_changed_native_client_is_rejected_before_reusing_plugin(plugin):
    c = plugin
    setup.install_plugin(c.project, c.client)
    (c.client / "GameAssembly.dll").write_bytes(b"changed native client")
    with pytest.raises(ValueError, match="fingerprint changed"):
        setup.install_plugin(c.project, c.client)
    assert len(c.calls) == 1 and c.target.read_bytes() == b"new plugin"


@pytest.mark.parametrize("existing", [False, True])
def test_failed_build_stamp_write_restores_previous_plugin(plugin, monkeypatch, existing):
    c = plugin
    if not existing:
        c.target.unlink()
    atomic = setup.atomic_bytes

    def fail_stamp(path, payload):
        if path.name == "build-inputs.json":
            raise OSError("stamp write failed")
        return atomic(path, payload)

    monkeypatch.setattr(setup, "atomic_bytes", fail_stamp)
    with pytest.raises(OSError, match="stamp write failed"):
        setup.install_plugin(c.project, c.client)
    assert c.target.read_bytes() == b"old plugin" if existing else not c.target.exists()
    assert not c.target.with_name("build-inputs.json").exists()
