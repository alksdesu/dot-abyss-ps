from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


MANIFEST_PATH = Path("pc/releases/manifest.json")
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
LEGACY_BUILD_FIELDS = (
    "release", "application_version", "launcher_product_id", "executable", "app_info", "identity",
    "source_fingerprints", "settings", "prepared_fingerprints",
)


class ReleaseManifestError(ValueError):
    pass


def project_root(root=None):
    return Path(root).resolve() if root is not None else Path(__file__).resolve().parents[2]


def canonical_json(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseManifestError("Duplicate release manifest field: " + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise ReleaseManifestError("Invalid JSON constant: " + value)


def _read_object(path):
    if path.is_symlink() or not path.is_file():
        raise ReleaseManifestError("Release configuration is missing or not a regular file: " + str(path))
    with path.open("rb") as stream:
        payload = stream.read(MAX_MANIFEST_BYTES + 1)
    if not payload or len(payload) > MAX_MANIFEST_BYTES:
        raise ReleaseManifestError("Release configuration exceeds its size limit: " + str(path))
    try:
        result = json.loads(payload.decode("utf-8-sig"), object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (UnicodeError, ValueError) as error:
        raise ReleaseManifestError("Invalid release configuration: " + str(path)) from error
    if not isinstance(result, dict):
        raise ReleaseManifestError("Release configuration must be an object: " + str(path))
    return result


def _text(value, label):
    if not isinstance(value, str) or not value or len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise ReleaseManifestError("Invalid " + label)
    return value


def _hash(value, label, length=64):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{" + str(length) + r"}", value) is None:
        raise ReleaseManifestError("Invalid " + label)
    return value


def _relative(value, label):
    value = _text(value, label)
    if "\\" in value or ":" in value or value.startswith("/") or any(part in ("", ".", "..") for part in value.split("/")):
        raise ReleaseManifestError("Expected a relative " + label)
    return value


def _path(root, relative, *, client=False):
    if client and isinstance(relative, str) and relative.startswith("../dotabyss_pc/"):
        _relative(relative[len("../"):], "client directory")
        boundary = root.parent / "dotabyss_pc"
    else:
        _relative(relative, "release path")
        boundary = root
    target = root / relative
    if not target.resolve().is_relative_to(boundary.resolve()) or target.resolve() == boundary.resolve():
        raise ReleaseManifestError("Release path leaves its allowed directory: " + relative)
    return target.resolve()


def _object(value, label):
    if not isinstance(value, dict):
        raise ReleaseManifestError("Invalid " + label)
    return value


def _validate_profile(root, identifier, profile):
    profile = _object(profile, "release profile")
    build = _object(profile.get("build"), "client build")
    content = _object(profile.get("content"), "content profile")
    paths = _object(profile.get("paths"), "release paths")
    if build.get("release") != identifier:
        raise ReleaseManifestError("Release identifier does not match its build")
    for key in ("application_version", "launcher_product_id", "executable"):
        _text(build.get(key), key)
    _relative(build["executable"], "executable filename")
    if PurePosixPath(build["executable"]).name != build["executable"] or "\\" in build["executable"]:
        raise ReleaseManifestError("Invalid executable filename")
    _relative(build.get("app_info"), "app info path")
    identity = _object(build.get("identity"), "client identity")
    for key in ("company", "product"):
        _relative(identity.get(key), "client " + key)
        if "/" in identity[key]:
            raise ReleaseManifestError("Invalid client " + key)
    for name in ("source_fingerprints", "prepared_fingerprints"):
        values = _object(build.get(name), name)
        if not values:
            raise ReleaseManifestError("Empty " + name)
        for relative, digest in values.items():
            _relative(relative, "fingerprint path")
            _hash(digest, "file fingerprint")
    settings = _object(build.get("settings"), "settings preparation")
    _relative(settings.get("path"), "settings path")
    _hash(settings.get("sha256"), "settings fingerprint")
    if settings["sha256"] != build["source_fingerprints"].get(settings["path"]):
        raise ReleaseManifestError("Settings source fingerprint does not match the build")
    for key in ("string_changes", "integer_changes"):
        changes = settings.get(key)
        if not isinstance(changes, list):
            raise ReleaseManifestError("Invalid settings changes")
        for change in changes:
            if not isinstance(change, dict) or type(change.get("offset")) is not int or change["offset"] < 0:
                raise ReleaseManifestError("Invalid settings offset")
            for name in ("before", "after"):
                if key == "string_changes":
                    _text(change.get(name), "settings string")
                elif type(change.get(name)) is not int or not 0 <= change[name] <= 0xffffffff:
                    raise ReleaseManifestError("Invalid settings integer")
    schema = _object(build.get("schema"), "schema binding")
    _path(root, schema.get("path"))
    _hash(schema.get("sha256"), "schema fingerprint")
    for key in ("data_directory", "local_release", "legacy_projection"):
        _path(root, paths.get(key))
    _path(root, paths.get("client_directory"), client=True)
    definitions = [MANIFEST_PATH.as_posix(), schema["path"], paths["local_release"], paths["legacy_projection"]]
    if len(set(value.casefold() for value in definitions)) != len(definitions):
        raise ReleaseManifestError("Release source, schema, local override and generated projection must be separate")
    transport = _object(build.get("transport"), "resource transport")
    _text(transport.get("bundle_version"), "bundle version")
    resource_root = _text(transport.get("resource_root"), "resource root")
    if not resource_root.startswith("/") or not resource_root.endswith("/"):
        raise ReleaseManifestError("Resource root must be an absolute URL path ending in a slash")
    _relative(resource_root[1:-1], "resource root")
    prefix = _relative(transport.get("catalog_prefix"), "catalog prefix")
    if not ("/" + prefix + "/").startswith(resource_root):
        raise ReleaseManifestError("Catalog prefix leaves the resource root")
    for key in ("catalog_path", "catalog_hash_path"):
        value = _relative(transport.get(key), key)
        if str(PurePosixPath(value).parent) != prefix:
            raise ReleaseManifestError("Catalog files must belong to the declared catalog prefix")
    if transport["catalog_path"] == transport["catalog_hash_path"]:
        raise ReleaseManifestError("Catalog and hash paths must be separate")
    remote = urlsplit(_text(transport.get("remote_base"), "remote resource base"))
    if (remote.scheme != "https" or not remote.hostname or remote.username or remote.password
            or remote.query or remote.fragment or remote.path.rstrip("/") != "/" + prefix):
        raise ReleaseManifestError("Remote resource base does not match the catalog prefix")
    proxy = _object(build.get("proxy"), "native proxy binding")
    _hash(proxy.get("unity_player_sha256"), "UnityPlayer fingerprint")
    if proxy["unity_player_sha256"] != build["source_fingerprints"].get("UnityPlayer.dll"):
        raise ReleaseManifestError("Proxy fingerprint does not match UnityPlayer")
    if type(proxy.get("entry_rva")) is not int or not 0 < proxy["entry_rva"] <= 0x7fffffff:
        raise ReleaseManifestError("Invalid native proxy address")
    if not isinstance(proxy.get("entry_hex"), str) or re.fullmatch(r"(?:[0-9a-f]{2}){1,256}", proxy["entry_hex"]) is None:
        raise ReleaseManifestError("Invalid native proxy signature")
    seeds = content.get("profile_seeds")
    if not isinstance(seeds, list) or not seeds:
        raise ReleaseManifestError("Content profile must include resource seeds")
    seen = set()
    for seed in seeds:
        seed = _object(seed, "resource seed")
        relative = _relative(seed.get("relative"), "resource seed path")
        if relative in seen:
            raise ReleaseManifestError("Duplicate resource seed path")
        seen.add(relative)
        _hash(seed.get("sha256"), "resource seed fingerprint")
        if "source" in seed:
            _text(seed["source"], "resource seed source")
    _hash(content.get("catalog_version_hash"), "catalog version hash", 32)


def load_manifest(root=None):
    root = project_root(root)
    manifest = _read_object(root / MANIFEST_PATH)
    if type(manifest.get("format_version")) is not int or manifest["format_version"] != 1:
        raise ReleaseManifestError("Unsupported release manifest format")
    releases = _object(manifest.get("releases"), "releases")
    selected = _text(manifest.get("default_release"), "default release identifier")
    if not releases or selected not in releases:
        raise ReleaseManifestError("Default release is missing from the manifest")
    for identifier, profile in releases.items():
        _text(identifier, "release identifier")
        _validate_profile(root, identifier, profile)
    derived_clients = []
    for profile in releases.values():
        build = profile["build"]
        metadata = [digest for path, digest in build["source_fingerprints"].items()
                    if path.endswith("/il2cpp_data/Metadata/global-metadata.dat")]
        if len(metadata) != 1:
            raise ReleaseManifestError("Client build must identify exactly one metadata fingerprint")
        client = {"package": build["launcher_product_id"], "version": build["application_version"],
                  "metadata_sha256": metadata[0]}
        if client not in derived_clients:
            derived_clients.append(client)
    clients = manifest.get("supported_clients")
    if not isinstance(clients, list):
        raise ReleaseManifestError("Supported client identities are missing")
    build_packages = {client["package"] for client in derived_clients}
    historical_clients = []
    for client in clients:
        client = _object(client, "supported client")
        _text(client.get("package"), "supported package")
        _text(client.get("version"), "supported version")
        _hash(client.get("metadata_sha256"), "supported metadata fingerprint")
        if client["package"] in build_packages:
            if client not in derived_clients:
                raise ReleaseManifestError("Supported client identity conflicts with the canonical build")
        elif client not in historical_clients:
            historical_clients.append(client)
    manifest["supported_clients"] = historical_clients + derived_clients
    bindings = _object(manifest.get("server_master_bindings"), "server master bindings")
    for name, binding in bindings.items():
        _text(name, "server master table")
        binding = _object(binding, "server master binding")
        _hash(binding.get("reviewed_sha256"), "reviewed table fingerprint")
        fields = binding.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ReleaseManifestError("Server master binding has no fields")
        names = set()
        for field in fields:
            field = _object(field, "server master field")
            field_name = _text(field.get("name"), "server master field name")
            if field_name in names or field.get("type") not in ("int", "long"):
                raise ReleaseManifestError("Invalid server master field contract")
            names.add(field_name)
    return manifest


def default_release(root=None):
    manifest = load_manifest(root)
    return manifest["releases"][manifest["default_release"]]


def legacy_release(profile):
    build = profile["build"]
    result = {"format_version": 1, **{key: copy.deepcopy(build[key]) for key in LEGACY_BUILD_FIELDS}}
    result["profile_seeds"] = copy.deepcopy(profile["content"]["profile_seeds"])
    if "updates" in profile:
        result["updates"] = copy.deepcopy(profile["updates"])
    return result


def local_release_path(root=None):
    root = project_root(root)
    return _path(root, default_release(root)["paths"]["local_release"])


def default_data_dir(root=None):
    root = project_root(root)
    return _path(root, default_release(root)["paths"]["data_directory"])


def default_client_dir(root=None):
    root = project_root(root)
    return _path(root, default_release(root)["paths"]["client_directory"], client=True)


def schema_path(root=None, profile_id=None):
    root = project_root(root)
    manifest = load_manifest(root)
    selected = profile_id or manifest["default_release"]
    if selected not in manifest["releases"]:
        raise ReleaseManifestError("Unknown client build profile: " + str(selected))
    schema = manifest["releases"][selected]["build"]["schema"]
    path = _path(root, schema["path"])
    if hashlib.sha256(canonical_json(_read_object(path))).hexdigest() != schema["sha256"]:
        raise ReleaseManifestError("Schema fingerprint does not match the selected release")
    return path


def default_schema_path(root=None):
    return schema_path(root)


def load_local_release(root=None):
    root = project_root(root)
    profile = default_release(root)
    result = legacy_release(profile)
    path = _path(root, profile["paths"]["local_release"])
    if not path.exists() and not path.is_symlink():
        return result
    local = _read_object(path)
    if any(local.get(key) != result[key] for key in LEGACY_BUILD_FIELDS):
        raise ReleaseManifestError("Local release structure differs from the canonical manifest")
    sources = {}
    seeds = local.get("profile_seeds", [])
    if not isinstance(seeds, list):
        raise ReleaseManifestError("Invalid local resource seeds")
    for seed in seeds:
        seed = _object(seed, "local resource seed")
        relative = _relative(seed.get("relative"), "local resource seed path")
        if relative in sources:
            raise ReleaseManifestError("Duplicate local resource seed path")
        sources[relative] = seed
    for seed in result["profile_seeds"]:
        source = sources.get(seed["relative"], {})
        if source.get("sha256") == seed["sha256"] and "source" in source:
            seed["source"] = _text(source["source"], "local resource seed source")
    return result
