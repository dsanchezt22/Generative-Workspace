"""Tests for the Layout Studio (use-case catalog, generation, library, promote)."""

import pytest
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client(monkeypatch):
    # Force offline stub mode so generation is deterministic and hits no network.
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    monkeypatch.delenv("TRUS_LLM_BASE_URL", raising=False)
    for k in ("TRUS_CACHE", "TRUS_CACHE_THRESHOLD"):
        monkeypatch.delenv(k, raising=False)
    with TestClient(app) as c:
        yield c


def test_use_cases_listed(client):
    data = client.get("/api/studio/use-cases").json()
    keys = {u["key"] for u in data}
    assert {"calorie", "fitness", "travel", "finance", "productivity", "habits"} <= keys
    cal = next(u for u in data if u["key"] == "calorie")
    assert "Cronometer" in cal["apps"] and "MyFitnessPal" in cal["apps"]
    assert cal["count"] == 0


def test_generate_list_count_delete(client):
    layouts = client.post("/api/studio/use-cases/calorie/generate?n=3").json()
    assert 1 <= len(layouts) <= 3
    assert all(ly["use_case"] == "calorie" and ly["id"] for ly in layouts)
    assert all(ly["config"]["title"] for ly in layouts)
    assert any(ly["config"]["components"] for ly in layouts)

    cal = next(u for u in client.get("/api/studio/use-cases").json() if u["key"] == "calorie")
    assert cal["count"] == len(layouts)

    listed = client.get("/api/studio/layouts?use_case=calorie").json()
    assert len(listed) == len(layouts)

    lid = layouts[0]["id"]
    assert client.delete(f"/api/studio/layouts/{lid}").status_code == 204
    assert len(client.get("/api/studio/layouts?use_case=calorie").json()) == len(layouts) - 1


def test_generate_unknown_use_case_404(client):
    assert client.post("/api/studio/use-cases/not-real/generate").status_code == 404


def test_delete_missing_404(client):
    assert client.delete("/api/studio/layouts/does-not-exist").status_code == 404


def test_promote_seeds_the_generation_pool(client):
    """Promoting a studio layout makes it retrievable as a generation seed — this
    is the connection to the main app's real-time generation."""
    from src import semantic_cache

    client.post("/api/studio/use-cases/calorie/generate?n=1")
    lid = client.get("/api/studio/layouts?use_case=calorie").json()[0]["id"]

    pr = client.post(f"/api/studio/layouts/{lid}/promote").json()
    assert pr["ok"] is True
    assert pr["seed_prompt"] == "calorie tracker"
    assert pr["library"]["entries"] >= 1

    # A main-app generation for this use case now finds the promoted layout.
    mode, cached = semantic_cache.lookup("system", "calorie tracker")
    assert mode == "hit"
    assert cached and cached[0]["title"]


_PNG = b"\x89PNG\r\n\x1a\n"  # minimal header — bytes are irrelevant when vision is mocked


def test_import_without_vision_model_returns_503(client):
    # No TRUS_VISION_MODEL configured (conftest clears it) → 503.
    r = client.post(
        "/api/studio/use-cases/calorie/import", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 503


def test_import_from_screenshot_stores_layout(client, monkeypatch):
    from src.services import studio

    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")

    def fake_vision(system, user_text, data, mime):
        return (
            '{"title":"Imported Nutrition","components":'
            '[{"id":"diary","type":"table","label":"Food log","columns":["Food","Cal"]},'
            '{"id":"cals","type":"ring","label":"Calories","max":2000}]}'
        )

    monkeypatch.setattr(studio.llm, "vision_describe", fake_vision)
    r = client.post(
        "/api/studio/use-cases/calorie/import", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 200
    ly = r.json()
    assert ly["use_case"] == "calorie"
    assert ly["inspired_by"] == "reference screenshot"
    assert [c["type"] for c in ly["config"]["components"]] == ["table", "ring"]
    # it landed in the library
    listed = client.get("/api/studio/layouts?use_case=calorie").json()
    assert any(x["id"] == ly["id"] for x in listed)


def test_import_rejects_non_image(client, monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 422
