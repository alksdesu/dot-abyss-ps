from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath

from dotabyss_ps.release_manifest import (
    MANIFEST_PATH, ReleaseManifestError, legacy_release, load_manifest, project_root, schema_path,
)


GENERATED_HEADER = "// Generated from the canonical client build profile."


def _fingerprint(build, suffix, *, prepared=False):
    fingerprints = build["prepared_fingerprints" if prepared else "source_fingerprints"]
    values = [digest for path, digest in fingerprints.items() if path == suffix or path.endswith("/" + suffix)]
    if len(values) != 1:
        raise ReleaseManifestError("Build must contain exactly one fingerprint for " + suffix)
    return values[0]


def render_client_profile(profile):
    build = profile["build"]
    transport, proxy = build["transport"], build["proxy"]
    fields = {
        "Package": build["launcher_product_id"],
        "ApplicationVersion": build["application_version"],
        "IdentityCompany": build["identity"]["company"],
        "IdentityProduct": build["identity"]["product"],
        "MetadataHash": _fingerprint(build, "il2cpp_data/Metadata/global-metadata.dat"),
        "NativeHash": _fingerprint(build, "GameAssembly.dll"),
        "PreparedSettingsHash": build["prepared_fingerprints"][build["settings"]["path"]],
        "SchemaHash": build["schema"]["sha256"],
        "BundleVersion": transport["bundle_version"],
        "ResourceRoot": transport["resource_root"],
        "CatalogPrefix": transport["catalog_prefix"],
        "CatalogPath": "/" + transport["catalog_path"],
        "CatalogHashPath": "/" + transport["catalog_hash_path"],
        "CatalogFileName": PurePosixPath(transport["catalog_path"]).name,
        "CatalogHashFileName": PurePosixPath(transport["catalog_hash_path"]).name,
        "UnityPlayerHash": proxy["unity_player_sha256"],
        "ProxyEntryHex": proxy["entry_hex"],
    }
    lines = [GENERATED_HEADER,
             "namespace DotAbyss.Local.Pc;", "", "internal static class ClientBuildProfile", "{"]
    lines.extend("    internal const string " + name + " = " + json.dumps(value, ensure_ascii=True) + ";"
                 for name, value in fields.items())
    lines.append("    internal const int ProxyEntryRva = " + str(proxy["entry_rva"]) + ";")
    lines.extend(("}", ""))
    return "\n".join(lines)


def build_fingerprint(profile):
    return hashlib.sha256(render_client_profile(profile).encode()).hexdigest()


def _write_or_check(path, payload, check):
    if path.is_symlink() or path.exists() and not path.is_file():
        raise ReleaseManifestError("Generated binding must be a regular file: " + str(path))
    if path.is_file() and path.read_bytes().replace(b"\r\n", b"\n") == payload:
        return False
    if check:
        raise ReleaseManifestError("Generated binding is missing or stale: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".partial", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return True


def _check_output(root, manifest, path):
    protected = {root / MANIFEST_PATH, Path(__file__).resolve(), root / "server/dotabyss_ps/release_manifest.py"}
    for profile in manifest["releases"].values():
        protected.update((root / profile["build"]["schema"]["path"], root / profile["paths"]["local_release"],
                          root / profile["paths"]["legacy_projection"]))
    if path.resolve() in {value.resolve() for value in protected}:
        raise ReleaseManifestError("Generated output would overwrite a release input: " + str(path))
    if path.suffix.lower() != ".cs":
        raise ReleaseManifestError("Client build binding output must be a C# file")
    if path.is_file():
        with path.open("rb") as stream:
            header = stream.readline(256).decode("utf-8-sig", errors="replace").rstrip("\r\n")
        if header != GENERATED_HEADER:
            raise ReleaseManifestError("Generated output would overwrite an existing source file: " + str(path))


def generate(root=None, output=None, *, profile_id=None, check=False):
    root = project_root(root)
    manifest = load_manifest(root)
    if profile_id is not None and profile_id not in manifest["releases"]:
        raise ReleaseManifestError("Unknown client build profile: " + profile_id)
    selected = profile_id or manifest["default_release"]
    if output is not None:
        path = Path(output)
        _check_output(root, manifest, path)
        schema_path(root, selected)
        payload = render_client_profile(manifest["releases"][selected]).encode()
        return {"path": str(path), "changed": _write_or_check(path, payload, check)}
    identifiers = [profile_id] if profile_id else list(manifest["releases"])
    changed = []
    for identifier in identifiers:
        profile = manifest["releases"][identifier]
        path = root / profile["paths"]["legacy_projection"]
        payload = (json.dumps(legacy_release(profile), ensure_ascii=False, indent=2) + "\n").encode()
        if _write_or_check(path, payload, check):
            changed.append(str(path))
    return {"changed": changed}


def main():
    parser = argparse.ArgumentParser(description="Generate bindings from the canonical release manifest")
    parser.add_argument("--root", type=Path)
    parser.add_argument("--profile")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        result = generate(args.root, args.output, profile_id=args.profile, check=args.check)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, "Release binding generation failed: " + str(error) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
