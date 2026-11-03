from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import struct
from pathlib import Path

from dotabyss_ps.profile_context import repair_storage_context, verify_profile_context
from dotabyss_ps.release_manifest import default_client_dir, load_local_release


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def within(root: Path, relative: str) -> Path:
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("File path leaves the selected directory")
    return path


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.is_symlink() or path.is_symlink():
        raise ValueError("Manifest paths must be regular files")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def patch_settings(payload: bytes, release: dict) -> bytes:
    if hashlib.sha256(payload).hexdigest() != release["settings"]["sha256"]:
        raise ValueError("PlayerSettings source fingerprint does not match this release")
    patched = bytearray(payload)
    ranges = []
    for change in release["settings"]["string_changes"]:
        offset = change["offset"]
        old, new = change["before"].encode("utf-8"), change["after"].encode("utf-8")
        if len(old) != len(new):
            raise ValueError("PlayerSettings replacement must preserve its serialized width")
        expected = struct.pack("<I", len(old)) + old
        if payload[offset:offset + len(expected)] != expected:
            raise ValueError("PlayerSettings named-field bytes differ from the reviewed release")
        patched[offset + 4:offset + 4 + len(new)] = new
        ranges.append((offset + 4, offset + 4 + len(new)))
    for change in release["settings"]["integer_changes"]:
        offset = change["offset"]
        if payload[offset:offset + 4] != struct.pack("<I", change["before"]):
            raise ValueError("PlayerSettings integer differs from the reviewed release")
        patched[offset:offset + 4] = struct.pack("<I", change["after"])
        ranges.append((offset, offset + 4))
    if any(a != b and not any(start <= i < end for start, end in ranges)
           for i, (a, b) in enumerate(zip(payload, patched))):
        raise ValueError("Unexpected PlayerSettings modification")
    return bytes(patched)


def _manifest_bytes(path: Path) -> bytes:
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT or info.st_size > 2 * 1024 * 1024):
        raise ValueError("Prepared client manifest must be a regular file no larger than 2 MiB")
    return path.read_bytes()


def _backup_manifest(destination: Path, payload: bytes) -> None:
    directory = destination / "profile-context-backups"
    directory.mkdir(exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
            or directory.resolve().parent != destination.resolve()):
        raise ValueError("Profile context backup directory must not redirect storage")
    path = directory / (hashlib.sha256(payload).hexdigest() + ".json")
    if path.exists() or path.is_symlink():
        if _manifest_bytes(path) != payload:
            raise ValueError("The original profile context manifest backup changed: " + str(path))
        return
    temporary = path.with_suffix(path.suffix + ".partial")
    if temporary.exists() or temporary.is_symlink():
        _manifest_bytes(temporary)
    with temporary.open("wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.rename(path)


def _client_manifest(destination: Path, release: dict) -> tuple[dict, Path, bytes]:
    payload = _manifest_bytes(destination / "local-client.json")
    manifest = json.loads(payload.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Prepared client manifest must contain an object")
    if manifest["release"] != release["release"] or manifest["source_fingerprints"] != release["source_fingerprints"]:
        raise ValueError("Prepared client belongs to a different release")
    if manifest["prepared_fingerprints"] != release["prepared_fingerprints"]:
        raise ValueError("Prepared fingerprints differ from the reviewed release")
    if manifest["root"] != str(destination):
        raise ValueError("Prepared client location changed; prepare a separate validated copy")
    identity = release["identity"]
    profile = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow" / identity["company"] / identity["product"]
    expected = {"format_version": 1, "identity": identity, "profile": str(profile.absolute()),
                "application_version": release["application_version"], "executable": release["executable"],
                "runtime_isolation_verified": False}
    if any(manifest.get(key) != value for key, value in expected.items()):
        raise ValueError("Prepared identity, executable or profile differs from the reviewed release")
    for relative, fingerprint in manifest["prepared_fingerprints"].items():
        if digest(within(destination, relative)) != fingerprint:
            raise ValueError("Prepared client fingerprint changed: " + relative)
    return manifest, profile, payload


def verify_client(destination: Path, release: dict, *, require_seeds: bool = False) -> dict:
    manifest, profile, _ = _client_manifest(destination, release)
    context = verify_profile_context(manifest, profile)
    seed_paths = context["profile_seed_paths"]
    if require_seeds:
        for item in release["profile_seeds"]:
            seed = within(profile, item["relative"])
            if str(seed) != seed_paths.get(item["relative"]):
                raise ValueError("The Windows cache storage context changed")
            if digest(seed) != item["sha256"]:
                raise ValueError("Prepared catalog or master seed changed")
    return manifest


def repair_profile_context(destination: Path, release: dict) -> dict:
    manifest, profile, payload = _client_manifest(destination, release)

    def commit(path, updated):
        if _manifest_bytes(path) != payload:
            raise ValueError("Prepared client manifest changed during profile repair; retry with stable configuration")
        _backup_manifest(destination, payload)
        write_json(path, updated)

    return repair_storage_context(manifest, profile, destination / "local-client.json", commit)


def prepare(source: Path, destination: Path, release: dict, profile: Path) -> dict:
    source, destination, profile = source.resolve(), destination.resolve(), profile.absolute()
    if source == destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError("Original and prepared clients must be separate directories")
    expected_profile = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow" / release["identity"]["company"] / release["identity"]["product"]
    if profile != expected_profile.absolute():
        raise ValueError("Profile does not match the prepared Unity identity")
    for relative, expected in release["source_fingerprints"].items():
        if digest(within(source, relative)) != expected:
            raise ValueError("Official source fingerprint changed: " + relative)
    if (destination / "local-client.json").is_file():
        return verify_client(destination, release)
    if destination.exists():
        for path in destination.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(destination).as_posix()
            if relative == "local-client.json.partial" and not path.is_symlink() and path.stat().st_size <= 1024 * 1024:
                continue
            permitted = {release["source_fingerprints"].get(relative), release["prepared_fingerprints"].get(relative)}
            if relative == release["app_info"] and hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest() in permitted:
                continue
            if path.is_symlink() or digest(path) not in permitted:
                raise ValueError("Unrecognized file in incomplete prepared client: " + relative)
    settings_path = within(source, release["settings"]["path"])
    patched = patch_settings(settings_path.read_bytes(), release)
    destination.mkdir(parents=True, exist_ok=True)
    for relative in release["source_fingerprints"]:
        origin, target = within(source, relative), within(destination, relative)
        if origin.is_symlink():
            raise ValueError("Client source must contain regular files")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)
    within(destination, release["settings"]["path"]).write_bytes(patched)
    identity = release["identity"]
    within(destination, release["app_info"]).write_bytes((identity["company"] + "\n" + identity["product"] + "\n").encode("utf-8"))
    profile.mkdir(parents=True, exist_ok=True)
    for item in release["profile_seeds"]:
        origin, target = Path(item["source"]), within(profile, item["relative"])
        if digest(origin) != item["sha256"]:
            raise ValueError("Catalog or master seed fingerprint changed")
        if target.exists():
            if digest(target) != item["sha256"]:
                raise ValueError("Local profile already has different seed data; explicit update is required")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
            if digest(target) != item["sha256"]:
                raise ValueError("Copied catalog or master seed fingerprint changed")
    fingerprints = {relative: digest(within(destination, relative)) for relative in release["source_fingerprints"]}
    manifest = {"format_version": 1, "release": release["release"], "root": str(destination),
                "profile": str(profile), "identity": identity, "application_version": release["application_version"],
                "executable": release["executable"], "source_root": str(source),
                "source_fingerprints": release["source_fingerprints"], "prepared_fingerprints": fingerprints,
                "profile_physical_path": str(profile.resolve(strict=True)),
                "profile_seed_paths": {item["relative"]: str(within(profile, item["relative"])) for item in release["profile_seeds"]},
                "runtime_isolation_verified": False}
    write_json(destination / "local-client.json", manifest)
    for relative, expected in release["source_fingerprints"].items():
        if digest(within(source, relative)) != expected:
            raise ValueError("Official source changed during preparation")
    return verify_client(destination, release, require_seeds=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a fingerprint-bound isolated PC client")
    parser.add_argument("--release", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--verify", action="store_true")
    action.add_argument("--repair-profile", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    release = json.loads(args.release.read_text(encoding="utf-8")) if args.release is not None else load_local_release(root)
    destination = args.destination.resolve() if args.destination is not None else default_client_dir(root)
    if args.repair_profile:
        from dotabyss_ps.admin_launcher import game_processes
        from dotabyss_ps.process_lock import exclusive_process_lock

        with exclusive_process_lock(destination / ".local-launcher.lock"):
            if game_processes(within(destination, release["executable"])):
                parser.error("Exit the local game before repairing its profile storage context")
            result = repair_profile_context(destination, release)
    elif args.verify:
        result = verify_client(destination, release)
    else:
        if args.source is None:
            parser.error("--source is required for preparation")
        identity = release["identity"]
        profile = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow" / identity["company"] / identity["product"]
        result = prepare(args.source, destination, release, profile)
    print(json.dumps({"root": result["root"], "profile": result["profile"], "release": result["release"],
                      "verified_files": len(result["prepared_fingerprints"]),
                      "runtime_isolation_verified": result["runtime_isolation_verified"]}, ensure_ascii=True))


if __name__ == "__main__":
    main()
