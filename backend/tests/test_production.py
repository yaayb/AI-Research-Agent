from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def test_access_key_protects_api(monkeypatch):
    monkeypatch.setattr(get_settings(), "access_key", "s3cret")
    with TestClient(create_app()) as c:
        assert c.get("/api/health").json()["auth_required"] is True
        assert c.get("/api/research/providers").status_code == 401
        assert c.get("/api/research/providers", headers={"X-Access-Key": "s3cret"}).status_code == 200
        assert c.get("/api/research/providers", params={"key": "s3cret"}).status_code == 200
        assert c.get("/api/research/providers", headers={"X-Access-Key": "bad"}).status_code == 401


def test_busy_server_returns_429(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_concurrent_runs", 1)
    with TestClient(create_app()) as c:
        from app.api.routes_research import RunChannel
        c.app.state.ctx.channels["running"] = RunChannel()  # an unfinished run occupies the only slot
        r = c.post("/api/research/start", json={"topic": "anything goes", "depth": "quick"})
        assert r.status_code == 429
