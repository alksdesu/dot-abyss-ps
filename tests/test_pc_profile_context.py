import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dotabyss_ps import profile_context
from test_pc_prepare import pc_prepare, prepared_case, seeded_case


@pytest.fixture
def moved_case(seeded_case):
    _, destination, release, profile = seeded_case
    manifest = pc_prepare.prepare(*seeded_case)
    (profile / "preferences.json").write_bytes(b'{"volume":0.25}')
    (profile / "saves").mkdir()
    (profile / "saves/player.dat").write_bytes(b"local progress")
    (profile / "empty-cache").mkdir()
    physical = profile.parents[3] / "AppData/Local/Packages/Fixture.Game_123/LocalCache/LocalLow" / profile.parent.name / profile.name
    physical.parent.mkdir(parents=True)
    profile.rename(physical)
    manifest["profile_physical_path"] = str(physical)
    manifest["profile_seed_paths"] = {relative: str(physical / relative) for relative in manifest["profile_seed_paths"]}
    pc_prepare.write_json(destination / "local-client.json", manifest)
    return destination, release, profile, physical, manifest


def files(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and path.name != profile_context.RECOVERY_FILE}


def test_repair_copies_current_cache_preferences_and_saves_without_changing_source(moved_case):
    destination, release, profile, physical, original = moved_case
    seeds = release["profile_seeds"]
    (physical / seeds[0]["relative"]).write_bytes(b"new runtime content")
    (physical / seeds[1]["relative"]).unlink()
    before = files(physical)
    original_payload = (destination / "local-client.json").read_bytes()
    with pytest.raises(FileNotFoundError):
        pc_prepare.verify_client(destination, release)
    assert not profile.exists()
    updated = pc_prepare.repair_profile_context(destination, release)
    assert files(physical) == before == files(profile)
    assert (profile / "empty-cache").is_dir()
    assert updated["profile_physical_path"] == original["profile_physical_path"]
    assert updated["profile_seed_paths"] == original["profile_seed_paths"]
    assert updated["profile_storage_contexts"][0]["profile_physical_path"] == str(profile)
    assert pc_prepare.verify_client(destination, release) == updated
    backup = destination / "profile-context-backups" / (hashlib.sha256(original_payload).hexdigest() + ".json")
    assert backup.read_bytes() == original_payload


def test_repaired_contexts_reuse_their_own_mutable_data_without_copying(moved_case, monkeypatch):
    destination, release, profile, physical, _ = moved_case
    manifest = pc_prepare.repair_profile_context(destination, release)
    (profile / "preferences.json").write_bytes(b"native preferences")
    (physical / "preferences.json").write_bytes(b"packaged preferences")
    before = (files(profile), files(physical), (destination / "local-client.json").read_bytes())

    def forbidden_copy(*args, **kwargs):
        pytest.fail("A previously repaired context must not copy profile data again")

    monkeypatch.setattr(profile_context.shutil, "copy2", forbidden_copy)
    assert pc_prepare.repair_profile_context(destination, release) == manifest
    resolve = Path.resolve

    def packaged_resolve(path, strict=False):
        return resolve(physical if path == profile else path, strict=strict)

    monkeypatch.setattr(Path, "resolve", packaged_resolve)
    assert pc_prepare.verify_client(destination, release) == manifest
    assert pc_prepare.repair_profile_context(destination, release) == manifest
    assert (files(profile), files(physical), (destination / "local-client.json").read_bytes()) == before


@pytest.mark.parametrize("occupied", [False, True])
def test_unbound_existing_target_is_never_overwritten(moved_case, occupied):
    destination, release, profile, physical, _ = moved_case
    profile.mkdir()
    if occupied:
        (profile / "existing-save").write_bytes(b"unrelated progress")
    before = (files(profile), files(physical), (destination / "local-client.json").read_bytes())
    with pytest.raises(ValueError, match="already exists and is not bound"):
        pc_prepare.repair_profile_context(destination, release)
    assert (files(profile), files(physical), (destination / "local-client.json").read_bytes()) == before


@pytest.mark.parametrize("change", ["physical", "seed", "duplicate", "identity"])
def test_repair_rejects_tampered_bindings_before_creating_profile(moved_case, change):
    destination, release, profile, physical, manifest = moved_case
    modified = copy.deepcopy(manifest)
    if change == "physical":
        modified["profile_physical_path"] = str(physical.parents[3] / "unrelated")
    elif change == "seed":
        modified["profile_seed_paths"]["../unrelated"] = str(physical.parent / "unrelated")
    elif change == "duplicate":
        modified["profile_storage_contexts"] = [{key: modified[key] for key in ("profile_physical_path", "profile_seed_paths")}]
    else:
        modified["identity"]["product"] = "OfficialPlayer"
    pc_prepare.write_json(destination / "local-client.json", modified)
    with pytest.raises(ValueError):
        pc_prepare.repair_profile_context(destination, release)
    assert not profile.exists()
    assert json.loads((destination / "local-client.json").read_text(encoding="utf-8")) == modified


def test_missing_source_gives_recovery_action_without_creating_profile(moved_case):
    destination, release, profile, physical, _ = moved_case
    physical.rename(physical.with_name(physical.name + "-backup"))
    before = (destination / "local-client.json").read_bytes()
    with pytest.raises(ValueError, match="original storage environment"):
        pc_prepare.repair_profile_context(destination, release)
    assert not profile.exists()
    assert (destination / "local-client.json").read_bytes() == before


@pytest.mark.parametrize("relative", ["saves", "preferences.json"])
def test_profile_reparse_directories_and_files_are_rejected(moved_case, monkeypatch, relative):
    destination, release, profile, physical, _ = moved_case
    path = physical / relative
    lstat = Path.lstat

    def reparse_lstat(current):
        info = lstat(current)
        if current != path:
            return info
        return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size, st_mtime_ns=info.st_mtime_ns,
                               st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)

    monkeypatch.setattr(Path, "lstat", reparse_lstat)
    before = (destination / "local-client.json").read_bytes()
    with pytest.raises(ValueError, match="regular files and directories"):
        pc_prepare.repair_profile_context(destination, release)
    assert not profile.exists()
    assert (destination / "local-client.json").read_bytes() == before


@pytest.mark.parametrize("failure", ["copy", "source-change", "same-metadata"])
def test_failed_copy_never_publishes_partial_profile(moved_case, monkeypatch, failure):
    destination, release, profile, physical, _ = moved_case
    before = (destination / "local-client.json").read_bytes()
    copy2 = profile_context.shutil.copy2

    def damaged_copy(source, target):
        result = copy2(source, target)
        if source.name == "preferences.json":
            if failure == "same-metadata":
                info = target.stat()
                target.write_bytes(b"x" * info.st_size)
                os.utime(target, ns=(info.st_atime_ns, info.st_mtime_ns))
            else:
                (target if failure == "copy" else source).write_bytes(b"changed during copying")
        return result

    monkeypatch.setattr(profile_context.shutil, "copy2", damaged_copy)
    with pytest.raises(ValueError, match="changed or its copy was incomplete"):
        pc_prepare.repair_profile_context(destination, release)
    assert not profile.exists()
    assert (destination / "local-client.json").read_bytes() == before
    assert not list(profile.parent.glob(profile.name + ".profile-repair-*"))


def test_manifest_commit_failure_can_resume_without_copying_or_overwriting_data(moved_case, monkeypatch):
    destination, release, profile, physical, _ = moved_case
    before = (destination / "local-client.json").read_bytes()
    replace = pc_prepare.os.replace

    def failed_replace(source, target, **kwargs):
        if Path(target) == destination / "local-client.json":
            raise OSError("disk full")
        return replace(source, target, **kwargs)

    monkeypatch.setattr(pc_prepare.os, "replace", failed_replace)
    with pytest.raises(OSError, match="disk full"):
        pc_prepare.repair_profile_context(destination, release)
    assert (destination / "local-client.json").read_bytes() == before
    assert files(profile) == files(physical)
    (profile / "preferences.json").write_bytes(b"preserved after failed commit")
    monkeypatch.setattr(pc_prepare.os, "replace", replace)

    def forbidden_copy(*args, **kwargs):
        pytest.fail("A completed copy must survive a failed manifest commit")

    monkeypatch.setattr(profile_context.shutil, "copy2", forbidden_copy)
    result = pc_prepare.repair_profile_context(destination, release)
    assert pc_prepare.verify_client(destination, release) == result
    assert (profile / "preferences.json").read_bytes() == b"preserved after failed commit"
    assert not (destination / "local-client.json.partial").exists()


def test_hard_interruption_reuses_completed_staged_files(moved_case, monkeypatch):
    destination, release, profile, physical, _ = moved_case
    release_path = destination.parent / "interrupted-release.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    script = """
import json
import os
import sys
from pathlib import Path
from pc.prepare_client import repair_profile_context
from dotabyss_ps import profile_context

copy2 = profile_context.shutil.copy2
def interrupted_copy(source, target):
    copy2(source, target)
    os._exit(77)
profile_context.shutil.copy2 = interrupted_copy
repair_profile_context(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")))
"""
    result = subprocess.run([sys.executable, "-c", script, str(destination), str(release_path)],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=20)
    assert result.returncode == 77, result.stderr.decode(errors="replace")
    stages = list(profile.parent.glob(profile.name + ".profile-repair-*"))
    assert len(stages) == 1
    completed = files(stages[0])
    assert completed
    copy2 = profile_context.shutil.copy2

    def resumed_copy(source, target):
        assert source.relative_to(physical) not in completed
        return copy2(source, target)

    monkeypatch.setattr(profile_context.shutil, "copy2", resumed_copy)
    manifest = pc_prepare.repair_profile_context(destination, release)
    assert pc_prepare.verify_client(destination, release) == manifest
    assert files(profile) == files(physical)
    assert not stages[0].exists()


def test_immutable_client_is_checked_before_any_profile_repair(moved_case):
    destination, release, profile, physical, _ = moved_case
    before = files(physical)
    (destination / "settings").write_bytes(b"changed executable settings")
    with pytest.raises(ValueError, match="Prepared client fingerprint changed"):
        pc_prepare.repair_profile_context(destination, release)
    assert not profile.exists()
    assert files(physical) == before


def test_noop_repair_does_not_create_manifest_backups(seeded_case):
    _, destination, release, _ = seeded_case
    manifest = pc_prepare.prepare(*seeded_case)
    assert pc_prepare.repair_profile_context(destination, release) == manifest
    assert not (destination / "profile-context-backups").exists()


def test_changed_manifest_backup_is_not_replaced(moved_case):
    destination, release, profile, _, _ = moved_case
    original = (destination / "local-client.json").read_bytes()
    backup = destination / "profile-context-backups" / (hashlib.sha256(original).hexdigest() + ".json")
    backup.parent.mkdir()
    backup.write_bytes(b"preserve this changed record")
    with pytest.raises(ValueError, match="manifest backup changed"):
        pc_prepare.repair_profile_context(destination, release)
    assert backup.read_bytes() == b"preserve this changed record"
    assert (destination / "local-client.json").read_bytes() == original
    assert (profile / profile_context.RECOVERY_FILE).is_file()


@pytest.mark.parametrize("invalid", ["oversized", "reparse"])
def test_manifest_limits_are_checked_before_any_repair(moved_case, monkeypatch, invalid):
    destination, release, profile, _, _ = moved_case
    manifest = destination / "local-client.json"
    if invalid == "oversized":
        manifest.write_bytes(b" " * (2 * 1024 * 1024 + 1))
    else:
        lstat = Path.lstat

        def reparse_lstat(path):
            info = lstat(path)
            return SimpleNamespace(st_mode=info.st_mode, st_size=info.st_size,
                                   st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT) if path == manifest else info

        monkeypatch.setattr(Path, "lstat", reparse_lstat)
    with pytest.raises(ValueError, match="regular file no larger"):
        pc_prepare.repair_profile_context(destination, release)
    assert not profile.exists()


def test_reserved_partial_filename_is_not_overwritten(moved_case):
    destination, release, profile, physical, _ = moved_case
    reserved = physical / (profile_context.RECOVERY_FILE + ".partial")
    reserved.write_bytes(b"unrelated user data")
    with pytest.raises(ValueError, match="reserved repair filename"):
        pc_prepare.repair_profile_context(destination, release)
    assert reserved.read_bytes() == b"unrelated user data"
    assert not profile.exists()


@pytest.mark.parametrize("running", [False, True])
def test_explicit_repair_cli_checks_game_idle_under_launcher_lock(moved_case, monkeypatch, capsys, running):
    from dotabyss_ps import admin_launcher

    destination, release, profile, _, _ = moved_case
    release_path = destination.parent / "release.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["prepare_client.py", "--repair-profile", "--release", str(release_path),
                                    "--destination", str(destination)])
    checked = []

    def processes(executable):
        checked.append(executable)
        assert (destination / ".local-launcher.lock").is_file()
        return [object()] if running else []

    monkeypatch.setattr(admin_launcher, "game_processes", processes)
    if running:
        with pytest.raises(SystemExit):
            pc_prepare.main()
        assert not profile.exists()
    else:
        pc_prepare.main()
        assert json.loads(capsys.readouterr().out)["profile"] == str(profile)
        assert pc_prepare.verify_client(destination, release)["profile_storage_contexts"]
    assert checked == [destination / release["executable"]]
