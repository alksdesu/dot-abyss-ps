from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path


RECOVERY_FILE = ".dotabyss-profile-context.json"


def _regular(path: Path, *, directory: bool = False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ValueError("Profile storage must contain regular files and directories: " + str(path))
    return info


def _storage_path(value, profile: Path) -> Path:
    if not isinstance(value, str):
        raise ValueError("The Windows profile storage context is invalid")
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or path != path.absolute():
        raise ValueError("The Windows profile storage context is invalid")
    user = profile.parents[3]
    packages = user / "AppData/Local/Packages"
    if path == profile:
        return path
    try:
        relative = path.relative_to(packages)
    except ValueError:
        raise ValueError("The Windows profile storage context leaves the local Unity identity") from None
    if (len(relative.parts) != 5 or relative.parts[1:] != ("LocalCache", "LocalLow", *profile.parts[-2:])
            or any(":" in part for part in relative.parts)):
        raise ValueError("The Windows profile storage context leaves the local Unity identity")
    return path


def _relative_path(value) -> Path:
    if not isinstance(value, str):
        raise ValueError("The Windows cache storage context is invalid")
    path = Path(value)
    if (not path.parts or path.is_absolute() or path.drive or ".." in path.parts
            or any(":" in part for part in path.parts)):
        raise ValueError("The Windows cache storage context is invalid")
    return path


def storage_contexts(manifest: dict, profile: Path) -> list[dict]:
    additional = manifest.get("profile_storage_contexts", [])
    if not isinstance(additional, list):
        raise ValueError("The Windows profile storage contexts are invalid")
    contexts = [{key: manifest.get(key) for key in ("profile_physical_path", "profile_seed_paths")}, *additional]
    seen = set()
    seed_names = None
    for context in contexts:
        if not isinstance(context, dict):
            raise ValueError("The Windows profile storage context is invalid")
        physical = _storage_path(context.get("profile_physical_path"), profile)
        if physical in seen:
            raise ValueError("The Windows profile storage context is duplicated")
        seen.add(physical)
        seeds = context.get("profile_seed_paths")
        if not isinstance(seeds, dict):
            raise ValueError("The Windows cache storage context changed")
        if seed_names is not None and seeds.keys() != seed_names:
            raise ValueError("The Windows cache storage context changed")
        seed_names = seeds.keys()
        for relative, recorded in seeds.items():
            if str(physical / _relative_path(relative)) != recorded:
                raise ValueError("The Windows cache storage context changed")
    return contexts


def verify_profile_context(manifest: dict, profile: Path) -> dict:
    contexts = storage_contexts(manifest, profile)
    physical = profile.resolve(strict=True)
    _regular(physical, directory=True)
    context = next((item for item in contexts if Path(item["profile_physical_path"]) == physical), None)
    if context is None:
        raise ValueError("The Windows profile storage context changed; run --repair-profile in the game launcher's environment")
    for relative, recorded in context["profile_seed_paths"].items():
        if str((physical / relative).resolve()) != recorded:
            raise ValueError("The Windows cache storage context changed")
    return context


def _ancestors(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.exists() or candidate.is_symlink():
            _regular(candidate, directory=True)
            if candidate.resolve(strict=True) != candidate:
                raise ValueError("The Windows profile storage path was redirected: " + str(candidate))


def _recovery(manifest: dict, physical: Path, source: Path) -> dict:
    return {"format_version": 1, "client_root": manifest["root"], "release": manifest["release"],
            "profile": manifest["profile"], "physical_path": str(physical), "source_physical_path": str(source)}


def _check_recovery(root: Path, manifest: dict, contexts: list[dict]) -> bool:
    marker = root / RECOVERY_FILE
    if not marker.exists() and not marker.is_symlink():
        return False
    record = _read_record(marker)
    if not any(record == _recovery(manifest, root, Path(item["profile_physical_path"])) for item in contexts):
        raise ValueError("Profile repair recovery record belongs to another directory or client: " + str(marker))
    return True


def _read_record(marker: Path):
    if _regular(marker).st_size > 65536:
        raise ValueError("Profile repair recovery record is invalid: " + str(marker))
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        raise ValueError("Profile repair recovery record is invalid: " + str(marker)) from None


def _write_record(root: Path, record: dict) -> None:
    marker = root / RECOVERY_FILE
    temporary = marker.with_suffix(marker.suffix + ".partial")
    if temporary.exists() or temporary.is_symlink():
        _regular(temporary)
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(marker)


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _tree_state(root: Path, *, hashes: bool = False) -> dict:
    _regular(root, directory=True)
    if root.resolve(strict=True) != root:
        raise ValueError("The Windows profile storage path was redirected: " + str(root))
    result = {}
    pending = [root]
    while pending:
        directory = pending.pop()
        for path in directory.iterdir():
            if path == root / RECOVERY_FILE:
                _regular(path)
                continue
            info = path.lstat()
            is_directory = stat.S_ISDIR(info.st_mode)
            _regular(path, directory=is_directory)
            if path.resolve(strict=True) != path or not path.is_relative_to(root):
                raise ValueError("Profile storage path leaves its bound directory: " + str(path))
            value = None if is_directory else (info.st_size, info.st_mtime_ns)
            if hashes and value is not None:
                value += (_digest(path),)
            result[path.relative_to(root)] = value
            if is_directory:
                pending.append(path)
    return result


def _bind(manifest: dict, physical: Path, source_context: dict) -> dict:
    updated = copy.deepcopy(manifest)
    updated.setdefault("profile_storage_contexts", []).append({
        "profile_physical_path": str(physical),
        "profile_seed_paths": {relative: str(physical / relative) for relative in source_context["profile_seed_paths"]},
    })
    return updated


def _discard_stage(stage: Path, physical: Path) -> None:
    if stage.resolve(strict=True).parent != physical.parent or not stage.name.startswith(physical.name + ".profile-repair-"):
        raise ValueError("Profile repair temporary directory changed unexpectedly: " + str(stage))
    _tree_state(stage)
    def writable_retry(function, path, error):
        if not isinstance(error[1], PermissionError):
            raise error[1]
        candidate = Path(path)
        if not candidate.resolve().is_relative_to(stage):
            raise ValueError("Profile repair temporary path leaves its directory: " + str(candidate))
        _regular(candidate, directory=candidate.is_dir())
        candidate.chmod(candidate.stat().st_mode | stat.S_IWRITE)
        function(path)

    shutil.rmtree(stage, onerror=writable_retry)


def _initialize_stage(stage: Path, record: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=stage.parent,
                                         prefix=stage.name + ".", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(record, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        stage.mkdir(exist_ok=True)
        temporary.rename(stage / RECOVERY_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _copy_stage(manifest: dict, physical: Path, source: Path, before: dict) -> Path:
    owner = hashlib.sha256((manifest["root"] + "\0" + str(physical)).encode("utf-8")).hexdigest()[:24]
    stage = physical.with_name(physical.name + ".profile-repair-" + owner)
    recovery = _recovery(manifest, physical, source)
    snapshot = json.dumps(sorted((str(relative), state) for relative, state in before.items()), separators=(",", ":"))
    copying = {**recovery, "copy_snapshot": hashlib.sha256(snapshot.encode("utf-8")).hexdigest()}
    if stage.exists() or stage.is_symlink():
        _ancestors(stage)
        marker = stage / RECOVERY_FILE
        temporary = marker.with_suffix(marker.suffix + ".partial")
        if not marker.exists() and temporary.exists():
            if _read_record(temporary) != copying:
                raise ValueError("Incomplete profile repair record; move this temporary directory aside and retry --repair-profile: " + str(stage))
            temporary.replace(marker)
        if marker.exists() or marker.is_symlink():
            recorded = _read_record(marker)
            if not isinstance(recorded, dict) or {key: value for key, value in recorded.items() if key != "copy_snapshot"} != recovery:
                raise ValueError("Profile repair temporary directory belongs to another client: " + str(stage))
            if recorded not in (recovery, copying):
                _discard_stage(stage, physical)
        elif any(stage.iterdir()):
            raise ValueError("Profile repair temporary directory has no valid recovery record: " + str(stage))
    if stage.exists() and (stage / RECOVERY_FILE).exists():
        _write_record(stage, copying)
    else:
        _initialize_stage(stage, copying)
    staged = _tree_state(stage)
    if any(relative not in before or (state is None) != (before[relative] is None) for relative, state in staged.items()):
        raise ValueError("Profile repair temporary directory contains unrelated data: " + str(stage))
    return stage


def repair_storage_context(manifest: dict, profile: Path, manifest_path: Path, write_manifest) -> dict:
    contexts = storage_contexts(manifest, profile)
    physical = _storage_path(str(profile.resolve()), profile)
    matching = next((item for item in contexts if Path(item["profile_physical_path"]) == physical), None)
    if matching is not None and physical.is_dir():
        verify_profile_context(manifest, profile)
        return manifest
    _ancestors(physical)
    if physical.exists():
        _regular(physical, directory=True)
        if not _check_recovery(physical, manifest, contexts):
            raise ValueError("The current Windows profile directory already exists and is not bound to this client; "
                             "back it up and reconcile it before running --repair-profile: " + str(physical))
        _tree_state(physical)
        record = json.loads((physical / RECOVERY_FILE).read_text(encoding="utf-8"))
        source_context = next(item for item in contexts if item["profile_physical_path"] == record["source_physical_path"])
        updated = manifest if matching is not None else _bind(manifest, physical, source_context)
        verify_profile_context(updated, profile)
        write_manifest(manifest_path, updated)
        return updated
    source_context = None
    for context in contexts:
        candidate = Path(context["profile_physical_path"])
        if candidate != physical and candidate.is_dir() and candidate.resolve(strict=True) == candidate:
            source_context = context
            break
    if source_context is None:
        raise ValueError("The bound Windows profile cache is unavailable; run --repair-profile from the original "
                         "storage environment or restore the recorded directory before launching")
    source = Path(source_context["profile_physical_path"])
    _ancestors(source)
    reserved = source / (RECOVERY_FILE + ".partial")
    if reserved.exists() or reserved.is_symlink():
        raise ValueError("Profile data uses a reserved repair filename; preserve it under another name before retrying: " + str(reserved))
    _check_recovery(source, manifest, contexts)
    before = _tree_state(source, hashes=True)
    physical.parent.mkdir(parents=True, exist_ok=True)
    _ancestors(physical.parent)
    stage = _copy_stage(manifest, physical, source, before)
    try:
        for relative, state in before.items():
            origin, target = source / relative, stage / relative
            if state is None:
                target.mkdir(parents=True, exist_ok=True)
            else:
                _regular(origin)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and (_regular(target).st_size, target.stat().st_mtime_ns, _digest(target)) == state:
                    continue
                shutil.copy2(origin, target)
        if _tree_state(source, hashes=True) != before or _tree_state(stage, hashes=True) != before:
            raise ValueError("Profile data changed or its copy was incomplete; close the game and retry --repair-profile")
        _write_record(stage, _recovery(manifest, physical, source))
        _ancestors(physical.parent)
        if physical.exists() or physical.is_symlink():
            raise ValueError("The current Windows profile directory appeared during repair; close the game and retry")
        stage.rename(physical)
        updated = manifest if matching is not None else _bind(manifest, physical, source_context)
        verify_profile_context(updated, profile)
        write_manifest(manifest_path, updated)
        return updated
    finally:
        if stage.exists():
            _discard_stage(stage, physical)
