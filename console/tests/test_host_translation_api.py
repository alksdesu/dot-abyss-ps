import asyncio

import pytest
from fastapi.testclient import TestClient

from console.host_api import create_host_app
from console.client import ConsoleError
from console.tests.test_host_api import ORIGIN, SECRET, NATIVE, BROWSER, Manager, authenticate


class Translation:
    def __init__(self):
        self.calls = []

    def call(self, name):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        self.calls.append(name)
        return {"state": "running" if name == "install" else "ready", "can_start": name != "install"}

    def status(self):
        return self.call("status")

    def install(self):
        return self.call("install")

    def logs(self):
        self.call("logs")
        return {"text": "fixture logs", "path": None}

    def set_dynamic_mosaic(self, enabled):
        self.call(("mosaic", enabled))
        return {"state": "ready", "can_start": True, "dynamic_mosaic": enabled}


@pytest.fixture
def client():
    service = Translation()
    app = create_host_app(Manager(), SECRET, service)
    app.state.origin = ORIGIN
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 10001)) as client:
        client.translation = service
        yield client


@pytest.mark.parametrize("method,path", [("GET", "status"), ("GET", "logs"), ("POST", "install"), ("POST", "mosaic")])
def test_translation_routes_require_authentication(client, method, path):
    response = client.request(method, "/host/translation/" + path, json={} if method == "POST" else None)
    assert response.status_code in (401, 403)
    assert client.translation.calls == []


def test_translation_uses_existing_browser_session_and_async_job_response(client):
    authenticate(client)
    assert client.get("/host/translation/status", headers=BROWSER).status_code == 200
    response = client.post("/host/translation/install", headers=BROWSER, json={})
    assert response.status_code == 202 and response.json()["state"] == "running"
    assert client.get("/host/translation/logs", headers=BROWSER).json()["text"] == "fixture logs"
    assert client.translation.calls == ["status", "install", "logs"]


@pytest.mark.parametrize("body", [{"client": "C:/another-client"}, {"command": "anything"}, {"url": "https://example.com"}, []])
def test_install_does_not_accept_arbitrary_paths_commands_or_sources(client, body):
    response = client.post("/host/translation/install", headers=NATIVE, json=body)
    assert response.status_code == 400 and client.translation.calls == []


def test_translation_failure_preserves_status_and_does_not_break_service_api(client, monkeypatch):
    def blocked():
        raise ConsoleError("请先退出游戏", 409)
    monkeypatch.setattr(client.translation, "install", blocked)
    response = client.post("/host/translation/install", headers=NATIVE, json={})
    assert response.status_code == 409 and response.json()["error"]["message"] == "请先退出游戏"
    assert client.get("/host/status", headers=NATIVE).status_code == 200


def test_older_host_without_translation_has_clear_error_and_service_still_works():
    app = create_host_app(Manager(), SECRET)
    app.state.origin = ORIGIN
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 10001)) as client:
        assert client.get("/host/translation/status", headers=NATIVE).status_code == 503
        assert client.get("/host/status", headers=NATIVE).status_code == 200


def test_mosaic_switch_passes_only_a_boolean_to_the_manager(client):
    response = client.post("/host/translation/mosaic", headers=NATIVE, json={"enabled": False})
    assert response.status_code == 200 and response.json()["dynamic_mosaic"] is False
    assert client.translation.calls == [("mosaic", False)]


@pytest.mark.parametrize("body", [{}, {"enabled": "false"}, {"enabled": 0}, {"enabled": True, "client": "C:/x"}, []])
def test_mosaic_switch_rejects_anything_but_a_boolean(client, body):
    response = client.post("/host/translation/mosaic", headers=NATIVE, json=body)
    assert response.status_code == 400 and client.translation.calls == []
