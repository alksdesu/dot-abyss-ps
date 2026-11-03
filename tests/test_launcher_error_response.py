import pytest
from fastapi.testclient import TestClient

from dotabyss_ps.app import Settings, create_app


@pytest.mark.parametrize("failure", [FileNotFoundError(2, "missing profile directory"), PermissionError(13, "access denied")])
def test_launcher_filesystem_failure_returns_json_service_error(tmp_path, monkeypatch, failure):
    settings = Settings.from_directory(tmp_path / "data")
    app = create_app(settings)
    app.state.launcher.client_root = tmp_path / "client"
    def fail(*_):
        raise failure
    monkeypatch.setattr(app.state.launcher, "_start", fail)
    token = (settings.data_dir / "admin-token.txt").read_text().strip()
    with TestClient(app, base_url="http://127.0.0.1:18083", raise_server_exceptions=False) as client:
        response = client.post("/admin/launcher/start", json={"profile_id": 1}, headers={"x-admin-token": token})
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == "5038"
    assert "缓存目录和文件权限" in response.json()["error"]["message"]
