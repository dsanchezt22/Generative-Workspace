"""R-1103: one user's generation must never freeze the API for others."""

import threading
import time

from fastapi.testclient import TestClient
from src import db
from src.main import app


def test_health_responds_while_generation_in_flight(monkeypatch, tmp_path):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))

    from src.services import orchestrator

    def slow_generate(prompt, existing_modules=None):
        time.sleep(1.5)
        from src.schema import ModuleConfig
        from src.stub_templates import pick_system

        return [ModuleConfig.model_validate(c) for c in pick_system(prompt)]

    monkeypatch.setattr(orchestrator, "generate_modules", slow_generate)

    with TestClient(app) as client:
        started = threading.Event()

        def fire_generation():
            started.set()
            client.post("/api/modules/preview", json={"prompt": "track my workouts"})

        t = threading.Thread(target=fire_generation)
        t.start()
        started.wait()
        time.sleep(0.2)  # let the generation enter the handler
        t0 = time.monotonic()
        r = client.get("/api/health")
        elapsed = time.monotonic() - t0
        t.join()
        assert r.status_code == 200
        assert elapsed < 1.0, f"health blocked {elapsed:.2f}s behind a generation (R-1103 AC)"


def test_sqlite_runs_wal_with_busy_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with db._conn() as c:
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert c.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
