import copy
import hashlib

import pytest
from fastapi.testclient import TestClient

from dotabyss_ps.app import create_app
from dotabyss_ps.assets import AssetDataError, UNITY_PROVIDER
from test_assets import asset_setup, unity_payload
from test_newgame import PC_CLIENT, PLAY_CLIENT


def add_asset(context, identifier, kind, *, present=False, version=""):
    version = version or hashlib.sha256(f"{identifier}:{kind}".encode()).hexdigest()[:32]
    if kind == "prefab":
        filename = f"general-ui-bg-event_assets_assets_project_lazyassets_general_ui_bg_event_{identifier}_{version}.bundle"
    else:
        filename = f"general-ui-bg-novel_assets_assets_project_lazyassets_general_ui_bg_novel_{identifier}.png_{version}.bundle"
    relative = context.prefix + "/" + filename
    record = {"relative_path": relative, "resolved_url": context.index["binding"]["remote_base"] + "/" + filename,
              "cache_key": "bg-" + version, "hash128": version, "provider": UNITY_PROVIDER, "bundle_size": len(unity_payload())}
    context.index["records"].append(record)
    if present:
        cache_asset(context, record)
    return record


def cache_asset(context, record):
    folder = context.cache / record["cache_key"] / record["hash128"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "__info").write_text("-1\n1793371989\n1\n__data\n", encoding="ascii")
    (folder / "__data").write_bytes(unity_payload())


def activate(context):
    result = context.stage(allow_partial=True)
    context.assets.activate(result["revision"])
    return result


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_missing_backgrounds_report_verified_images_without_changing_original_downloads(asset_setup):
    context = asset_setup
    prefab = add_asset(context, "abg11101a", "prefab")
    image = add_asset(context, "abg11101a", "image", present=True)
    add_asset(context, "functionbg012", "prefab")
    result = activate(context)
    pointer = (context.assets.root / "active.json").read_bytes()
    with TestClient(create_app(context.settings)) as client:
        response = client.get("/local/event-backgrounds")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"asset_revision": result["revision"], "backgrounds": [
            {"id": "abg11101a", "image_available": True}, {"id": "functionbg012", "image_available": False}]}
        assert client.get("/" + prefab["relative_path"]).status_code == 404
        assert client.get("/" + image["relative_path"]).content == unity_payload()
    assert (context.assets.root / "active.json").read_bytes() == pointer


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_existing_prefab_takes_priority_and_reimport_removes_compatibility(asset_setup):
    context = asset_setup
    missing = add_asset(context, "abg11101a", "prefab")
    add_asset(context, "abg20200b", "prefab", present=True)
    first = activate(context)
    with TestClient(create_app(context.settings)) as client:
        assert client.get("/local/event-backgrounds").json()["backgrounds"] == [{"id": "abg11101a", "image_available": False}]
        cache_asset(context, missing)
        second = activate(context)
        assert first["revision"] != second["revision"]
        assert client.get("/local/event-backgrounds").json() == {"asset_revision": second["revision"], "backgrounds": []}


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_present_prefab_version_prevents_older_missing_version_from_overriding_it(asset_setup):
    context = asset_setup
    add_asset(context, "abg11101a", "prefab")
    add_asset(context, "abg11101a", "prefab", present=True, version="f" * 32)
    activate(context)
    assert context.assets.event_backgrounds()["backgrounds"] == []


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_missing_or_corrupt_image_is_reported_unavailable(asset_setup):
    context = asset_setup
    add_asset(context, "abg11101a", "prefab")
    image = add_asset(context, "abg11101a", "image", present=True)
    result = activate(context)
    entry = result["entries"][image["relative_path"]]
    (context.assets.root / "blobs" / entry["sha256"]).write_bytes(b"corrupt")
    with TestClient(create_app(context.settings)) as client:
        response = client.get("/local/event-backgrounds")
        assert response.json()["backgrounds"] == [{"id": "abg11101a", "image_available": False}]
        assert client.get("/" + image["relative_path"]).status_code == 503


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_corrupt_original_prefab_still_requires_repair(asset_setup):
    context = asset_setup
    prefab = add_asset(context, "abg11101a", "prefab", present=True)
    result = activate(context)
    entry = result["entries"][prefab["relative_path"]]
    (context.assets.root / "blobs" / entry["sha256"]).unlink()
    assert context.assets.event_backgrounds()["backgrounds"] == []
    with pytest.raises(AssetDataError):
        context.assets.read(prefab["relative_path"])


@pytest.mark.parametrize("asset_setup", [PC_CLIENT, PLAY_CLIENT], indirect=True)
def test_no_assets_and_other_platforms_do_not_enable_compatibility(asset_setup):
    context = asset_setup
    with TestClient(create_app(context.settings)) as client:
        assert client.get("/local/event-backgrounds").json() == {"asset_revision": None, "backgrounds": []}
        add_asset(context, "abg11101a", "prefab")
        activate(context)
        if context.master_record["client"] == PLAY_CLIENT:
            assert client.get("/local/event-backgrounds").json() == {"asset_revision": None, "backgrounds": []}


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_unknown_paths_and_invalid_background_identifiers_are_excluded(asset_setup):
    context = asset_setup
    for identifier in ("BadCase", "a" * 65, "abg-111", "folder/abg111"):
        add_asset(context, identifier, "prefab")
    add_asset(context, "valid_name_01", "prefab")
    result = activate(context)
    assert context.assets.event_backgrounds()["backgrounds"] == [{"id": "valid_name_01", "image_available": False}]
    candidate = copy.deepcopy(result)
    candidate["missing"] += [{"relative_path": "/" + result["missing"][0]["relative_path"]},
                             {"relative_path": "https://other.test/" + result["missing"][0]["relative_path"]}]
    context.assets.active = lambda: candidate
    assert context.assets.event_backgrounds()["backgrounds"] == [{"id": "valid_name_01", "image_available": False}]


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_background_query_rejects_stale_master_binding(asset_setup):
    context = asset_setup
    add_asset(context, "abg11101a", "prefab")
    activate(context)
    context.master(number=2)
    with TestClient(create_app(context.settings)) as client:
        response = client.get("/local/event-backgrounds")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["errors"]["code"] == 5035


@pytest.mark.parametrize("asset_setup", [PC_CLIENT], indirect=True)
def test_background_query_enforces_the_client_entry_limit(asset_setup):
    context = asset_setup
    for number in range(257):
        add_asset(context, f"bg{number}", "prefab")
    activate(context)
    with pytest.raises(AssetDataError, match="count exceeds"):
        context.assets.event_backgrounds()
