"""R-1201/R-1202/R-1203: activity measurable, generations accounted, ops surface gated."""

from fastapi.testclient import TestClient
from src import db
from src.main import app


def test_generation_records_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = client.post("/api/modules/preview", json={"prompt": "track my reading"})
        assert r.status_code == 200
    stats = db.gen_stats(days=1)
    assert stats["total"] == 1
    assert stats["by_outcome"].get("ok") == 1
    assert db.daily_active(days=1)[0]["owners"] >= 1


def test_failed_generation_records_error_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    from src.schema import LLMError
    from src.services import orchestrator

    def boom(*a, **k):
        raise LLMError("down")

    monkeypatch.setattr(orchestrator, "generate_modules", boom)
    with TestClient(app) as client:
        r = client.post("/api/modules/preview", json={"prompt": "x y z"})
        assert r.status_code == 503
    assert db.gen_stats(days=1)["by_outcome"].get("error") == 1


def test_ops_summary_is_token_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_OPS_TOKEN", "sekrit")
    with TestClient(app) as client:
        assert client.get("/api/ops/summary").status_code == 401
        assert client.get("/api/ops/summary?token=wrong").status_code == 401
        ok = client.get("/api/ops/summary?token=sekrit")
        assert ok.status_code == 200
        assert {"generations", "daily_active"} <= set(ok.json().keys())
