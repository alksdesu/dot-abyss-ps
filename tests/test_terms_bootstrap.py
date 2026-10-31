import json

import msgpack
import pytest
from fastapi.testclient import TestClient

from dotabyss_ps.app import Settings, create_app


READ_ROUTES = (
    ("/terms/fetch", {"s_terms_versions": []}),
    ("/api/terms/fetch-agreements", {"t_terms_agreements": []}),
    ("/version", {}),
)
ALL_ROUTES = tuple(path for path, _ in READ_ROUTES) + ("/api/terms/agree",)


@pytest.fixture
def setup(tmp_path):
    settings = Settings.from_directory(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        login = client.post("/local/login", json={"profile": "terms-test"}).json()
        headers = {"x-olg-session": login["contents"]["token"], "api-token": login["api_token"]}
        yield settings, app.state.store, client, headers


@pytest.mark.parametrize("path,contents", READ_ROUTES)
@pytest.mark.parametrize("accept", ("application/json", "application/x-msgpack"))
def test_clean_install_reads_local_bootstrap_without_fixtures(setup, path, contents, accept):
    settings, store, client, headers = setup
    store.set_runtime({"application_version": "1.15.0", "bundle_version": "0.1.0", "resource_version": "test-master"})
    assert not list(settings.fixtures_dir.iterdir())

    response = client.get(path, params={"platform_type": 4}, headers={**headers, "accept": accept})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(accept)
    body = msgpack.unpackb(response.content, raw=False) if accept == "application/x-msgpack" else response.json()
    assert body["status"] == "success"
    assert body["contents"] == contents
    assert body["api_token"] == headers["api-token"]
    assert body["versions"]["ClientVersionStandaloneDmmR18"] == ["1.15.0"]
    assert body["versions"]["AssetVersionStandaloneDmmR18"] == ["0.1.0"]
    assert body["versions"]["resource"] == ["test-master"]
    assert not list(settings.fixtures_dir.iterdir())
    assert client.get("/diagnostics").json()["route_sources"][path] == "builtin"


@pytest.mark.parametrize("path,contents", READ_ROUTES)
def test_local_bootstrap_does_not_read_stale_fixture_agreements(setup, path, contents):
    settings, _, client, headers = setup
    fixture = settings.fixtures_dir / (path.lstrip("/") + ".json")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps({"contents": {"stale": True}}), encoding="utf-8")
    assert client.get(path, headers=headers).json()["contents"] == contents


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_bootstrap_validates_session_and_supplied_api_token(setup, path):
    _, store, client, headers = setup
    method = "POST" if path.endswith("/agree") else "GET"
    for credentials in ({}, {"api-token": headers["api-token"]}, {**headers, "api-token": "wrong"}):
        response = client.request(method, path, headers=credentials, json={"terms_agreements": []})
        assert response.status_code == 401
        assert response.json()["errors"]["code"] == 4010
    with store.connection() as db:
        db.execute("UPDATE sessions SET expires_at=0")
    assert client.request(method, path, headers=headers, json={"terms_agreements": []}).status_code == 401


@pytest.mark.parametrize("path,contents", READ_ROUTES)
def test_read_bootstrap_preserves_session_only_compatibility(setup, path, contents):
    _, _, client, headers = setup
    response = client.get(path, headers={"x-olg-session": headers["x-olg-session"]})
    assert response.status_code == 200
    assert response.json()["contents"] == contents
    assert response.json()["api_token"] == ""


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_bootstrap_rejects_wrong_method_even_with_a_fixture(setup, path):
    settings, _, client, headers = setup
    fixture = settings.fixtures_dir / (path.lstrip("/") + ".json")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text('{"contents":{}}', encoding="utf-8")
    method = "GET" if path.endswith("/agree") else "POST"
    response = client.request(method, path, headers=headers, json={"terms_agreements": []})
    assert response.status_code == 405
    assert response.json()["errors"]["code"] == 4050


@pytest.mark.parametrize("content_type", ("application/json", "application/x-msgpack"))
def test_empty_agreement_request_is_supported(setup, content_type):
    _, _, client, headers = setup
    body = {"terms_agreements": []}
    payload = msgpack.packb(body) if content_type == "application/x-msgpack" else json.dumps(body).encode()
    response = client.post("/api/terms/agree", content=payload,
                           headers={**headers, "content-type": content_type, "accept": content_type})
    assert response.status_code == 200
    result = msgpack.unpackb(response.content, raw=False) if content_type == "application/x-msgpack" else response.json()
    assert result["contents"] == {"t_terms_agreements": []}
    assert result["status"] == "success"


@pytest.mark.parametrize("body", (
    {}, {"terms_agreements": None}, {"terms_agreements": {}},
    {"terms_agreements": [{"version": 1, "terms_type": 0}]},
    {"terms_agreements": [], "token": "external-token"},
))
def test_unknown_or_malformed_agreements_are_not_accepted(setup, body):
    _, _, client, headers = setup
    response = client.post("/api/terms/agree", json=body, headers=headers)
    assert response.status_code == 400
    assert response.json()["errors"]["code"] == 4006
    assert client.get("/api/terms/fetch-agreements", headers=headers).json()["contents"] == {"t_terms_agreements": []}


def test_agree_requires_api_token(setup):
    _, _, client, headers = setup
    response = client.post("/api/terms/agree", json={"terms_agreements": []},
                           headers={"x-olg-session": headers["x-olg-session"]})
    assert response.status_code == 401


def test_bootstrap_does_not_change_saved_game_or_identity(setup):
    settings, store, client, headers = setup
    with store.connection() as db:
        profile_id = db.execute("SELECT id FROM profiles").fetchone()[0]
        db.execute("INSERT INTO master_datasets VALUES ('test-master', '{}', 0)")
        db.execute("INSERT INTO game_states VALUES (?, 1, 'test-master', ?, 'saved')",
                   (profile_id, json.dumps({"currency": 123, "t_terms_agreements": []})))
        db.execute("INSERT INTO gameplay_progress VALUES (?, 'test-master', ?)",
                   (profile_id, json.dumps({"main_story": {"chapter": 2}})))

    def snapshot():
        with store.connection() as db:
            return {
                table: [tuple(row) for row in db.execute("SELECT * FROM " + table)]
                for table in ("profiles", "sessions", "profile_presence", "settings", "game_states", "gameplay_progress")
            }

    before = snapshot()
    for _ in range(2):
        for path, _ in READ_ROUTES:
            assert client.get(path, headers=headers).status_code == 200
        assert client.post("/api/terms/agree", headers=headers, json={"terms_agreements": []}).status_code == 200
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get("/api/terms/fetch-agreements", headers=headers).json()["contents"] == {"t_terms_agreements": []}
    assert snapshot() == before


@pytest.mark.parametrize("path", ALL_ROUTES)
def test_login_alias_cannot_shadow_builtin_bootstrap(tmp_path, path):
    settings = Settings.from_directory(tmp_path)
    with pytest.raises(ValueError, match="non-reserved"):
        create_app(Settings(settings.data_dir, settings.fixtures_dir, settings.resources_dir, path))
