"""Tests for the Layout Studio (use-case catalog, generation, library, promote)."""

import pytest
from fastapi.testclient import TestClient
from src.main import app

from tests.conftest import fake_generate


@pytest.fixture
def client(monkeypatch):
    # Force offline stub mode so generation is deterministic and hits no network.
    # (TRUS_CACHE* and TRUS_LLM_BASE_URL are already cleared by conftest.)
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
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


def _clean_layouts_raw() -> str:
    import json

    return json.dumps(
        [
            {
                "label": "Nutrient dashboard",
                "inspired_by": "Cronometer",
                "config": {
                    "title": "Nutrition",
                    "components": [{"id": "cals", "type": "kpi", "label": "Calories"}],
                },
            }
        ]
    )


def test_promote_seeds_the_generation_pool(client, monkeypatch):
    """Promoting a CLEAN (non-degraded) studio layout makes it retrievable as a
    generation seed — this is the connection to the main app's real-time generation."""
    from src import db, llm, semantic_cache

    # Claim a user so the promote seeds (and is retrievable) under a known owner (R-903).
    user = db.create_user("Promoter")
    client.post("/api/auth/claim", json={"token": user["invite_token"]})
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate", fake_generate(_clean_layouts_raw()))

    client.post("/api/studio/use-cases/calorie/generate?n=1")
    lid = client.get("/api/studio/layouts?use_case=calorie").json()[0]["id"]

    pr = client.post(f"/api/studio/layouts/{lid}/promote").json()
    assert pr["ok"] is True
    assert pr["seed_prompt"] == "calorie tracker"
    assert pr["library"]["entries"] >= 1

    # A main-app generation for this use case now finds the promoted layout.
    mode, cached = semantic_cache.lookup("system", "calorie tracker", owner=user["id"])
    assert mode == "hit"
    assert cached and cached[0]["title"]


def test_promote_refuses_degraded_generate_layout_with_409(client):
    """R-403/R-211: a stub-mode GENERATE layout is a generic template, not a real
    generation — it is marked degraded and must be refused (409) by promote so it
    can't poison the shared seed pool. (client fixture runs in stub mode.)"""
    from src import db

    client.post("/api/studio/use-cases/calorie/generate?n=1")
    lid = client.get("/api/studio/layouts?use_case=calorie").json()[0]["id"]

    r = client.post(f"/api/studio/layouts/{lid}/promote")
    assert r.status_code == 409
    assert "degraded" in r.json()["detail"]
    assert db.cache_stats()["entries"] == 0  # seed pool untouched


def test_import_small_file_read_ok(client, monkeypatch):
    """F3: the studio image read-cap (_MAX_IMAGE_BYTES+1) must not truncate a normal
    small upload — a tiny screenshot still flows through _load_image and imports."""
    from src.services import studio

    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")
    monkeypatch.setattr(
        studio.llm,
        "vision_describe",
        lambda *a, **k: (
            '{"title":"Imported","components":[{"id":"a","type":"text_input","label":"A"}]}'
        ),
    )
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        files={"file": ("small.png", _PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["config"]["components"][0]["type"] == "text_input"


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


# ---------------------------------------------------------------------------
# services/studio.py — the LLM-backed layout mining logic directly (non-stub
# generation, parsing, and vision-import edge cases not exercised via routes).
# ---------------------------------------------------------------------------


def test_generate_layouts_non_stub_parses_model_output(monkeypatch):
    import json

    from src import llm
    from src.services import studio

    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    raw = json.dumps(
        [
            {
                "label": "Nutrient dashboard",
                "inspired_by": "Cronometer",
                "config": {
                    "title": "Nutrition",
                    "components": [{"id": "cals", "type": "kpi", "label": "Calories"}],
                },
            }
        ]
    )
    monkeypatch.setattr(llm, "generate", fake_generate(raw))
    layouts = studio.generate_layouts("calorie", n=2)
    assert layouts[0]["label"] == "Nutrient dashboard"
    assert layouts[0]["inspired_by"] == "Cronometer"
    assert layouts[0]["config"]["title"] == "Nutrition"
    # A clean (non-degraded) generate carries no degraded marker.
    assert layouts[0]["degraded"] is False
    assert layouts[0]["source"] is None


def test_generate_layouts_unknown_use_case_raises_refusal():
    from src.schema import RefusalError
    from src.services import studio

    with pytest.raises(RefusalError):
        studio.generate_layouts("not-a-real-use-case")


def test_generate_layouts_falls_back_to_stub_after_persistent_invalid_output(monkeypatch):
    from src import llm
    from src.services import studio

    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate", fake_generate("not json"))
    layouts = studio.generate_layouts("calorie", n=1)
    assert layouts  # fell back to _stub_layouts instead of raising
    assert layouts[0]["config"]["title"]
    # The fallback is a degraded, non-promotable result (R-403).
    assert layouts[0]["degraded"] is True
    assert layouts[0]["source"] == "stub_fallback"


def test_generate_layouts_llm_error_breaks_and_falls_back_to_stub(monkeypatch):
    from src import llm
    from src.schema import LLMError
    from src.services import studio

    def boom(*a, **k):
        raise LLMError("endpoint down")

    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate", boom)
    layouts = studio.generate_layouts("calorie", n=1)
    assert layouts
    # LLMError → degraded stub fallback (last_call is NOT consulted here — it may
    # be unset/stale on the error path).
    assert layouts[0]["degraded"] is True
    assert layouts[0]["source"] == "stub_fallback"


def test_parse_layouts_unwraps_layouts_key_and_skips_invalid_items():
    import json

    from src.services import studio

    raw = json.dumps(
        {
            "layouts": [
                {
                    "label": "Good",
                    "config": {
                        "title": "T",
                        "components": [{"id": "a", "type": "text_input", "label": "A"}],
                    },
                },
                {"label": "Bad", "config": {"title": "T2"}},  # missing components → invalid
                "not-a-dict",
            ]
        }
    )
    out = studio._parse_layouts(raw)
    assert len(out) == 1
    assert out[0]["label"] == "Good"


def test_parse_layouts_raises_invalid_on_non_json():
    from src.services import studio

    with pytest.raises(studio._Invalid):
        studio._parse_layouts("not json at all")


def test_parse_layouts_raises_invalid_when_not_a_list():
    import json

    from src.services import studio

    with pytest.raises(studio._Invalid):
        studio._parse_layouts(json.dumps({"foo": "bar"}))


def test_parse_layouts_raises_invalid_when_no_valid_layouts():
    import json

    from src.services import studio

    with pytest.raises(studio._Invalid):
        studio._parse_layouts(json.dumps([{"label": "Bad", "config": {"title": "T"}}]))


def test_coerce_drops_invalid_components_but_keeps_valid():
    from src.services import studio

    data = {
        "title": "T",
        "components": [
            {"id": "a", "type": "text_input", "label": "A"},
            {"id": "bad", "type": "not_a_real_type", "label": "Bad"},
        ],
    }
    mc = studio._coerce(data)
    assert [c.id for c in mc.components] == ["a"]


def test_parse_one_non_json_raises_invalid():
    from src.services import studio

    with pytest.raises(studio._Invalid):
        studio._parse_one("not json")


def test_parse_one_accepts_array_and_takes_first_valid():
    import json

    from src.services import studio

    raw = json.dumps(
        [
            {"bad": "shape"},
            {"title": "T", "components": [{"id": "a", "type": "text_input", "label": "A"}]},
        ]
    )
    mc = studio._parse_one(raw)
    assert mc.title == "T"


def test_parse_one_raises_invalid_when_array_has_no_valid_config():
    import json

    from src.services import studio

    with pytest.raises(studio._Invalid):
        studio._parse_one(json.dumps([{"bad": "shape"}]))


def test_parse_one_raises_invalid_for_bad_object():
    import json

    from src.services import studio

    with pytest.raises(studio._Invalid):
        studio._parse_one(json.dumps({"bad": "shape"}))


def test_import_from_image_raises_refusal_after_failed_attempts(monkeypatch):
    from src import llm
    from src.schema import RefusalError
    from src.services import studio

    monkeypatch.setattr(llm, "vision_describe", lambda *a, **k: "not valid json")
    with pytest.raises(RefusalError):
        studio.import_from_image("calorie", b"data", "image/png")


def test_import_from_image_unknown_use_case_raises_refusal():
    from src.schema import RefusalError
    from src.services import studio

    with pytest.raises(RefusalError):
        studio.import_from_image("nope", b"data", "image/png")


def test_capture_layout_unknown_use_case_raises_refusal():
    from src.schema import RefusalError
    from src.services import studio

    with pytest.raises(RefusalError):
        studio.capture_layout("nope", b"data", "image/png")


# ---------------------------------------------------------------------------
# routes/studio.py gaps: unknown use case / refusal / LLM-error / not-found
# paths not exercised by the happy-path route tests above.
# ---------------------------------------------------------------------------


def test_import_route_unknown_use_case_404(client):
    r = client.post(
        "/api/studio/use-cases/not-real/import", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 404


def test_import_route_surfaces_refusal_as_422(client, monkeypatch):
    from src.services import studio

    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")
    monkeypatch.setattr(studio.llm, "vision_describe", lambda *a, **k: "not valid json")
    r = client.post(
        "/api/studio/use-cases/calorie/import", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 422
    assert "refusal" in r.json()["detail"]


def test_capture_route_surfaces_refusal_as_422(client, monkeypatch):
    from src.schema import RefusalError

    monkeypatch.setattr(
        "src.services.studio.capture_layout",
        lambda *a, **k: (_ for _ in ()).throw(RefusalError("couldn't read layout")),
    )
    r = client.post(
        "/api/studio/use-cases/calorie/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 422
    assert "refusal" in r.json()["detail"]


def test_capture_route_surfaces_llm_error_as_503(client, monkeypatch):
    from src.schema import LLMError

    monkeypatch.setattr(
        "src.services.studio.capture_layout",
        lambda *a, **k: (_ for _ in ()).throw(LLMError("model unavailable")),
    )
    r = client.post(
        "/api/studio/use-cases/calorie/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 503


def test_capture_llm_error_detail_is_sanitized(client, monkeypatch):
    """F5-equivalent for the studio capture path: the raw LLMError text can embed
    the internal endpoint URL — the client must only ever see the sanitized,
    mapped message (never the leaked "http://..." endpoint)."""
    from src.schema import LLMError

    leak = "Could not reach the LLM endpoint at http://10.1.2.3:11434/v1: refused"
    monkeypatch.setattr(
        "src.services.studio.capture_layout",
        lambda *a, **k: (_ for _ in ()).throw(LLMError(leak)),
    )
    r = client.post(
        "/api/studio/use-cases/calorie/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "http" not in detail


def test_promote_unknown_layout_404(client):
    assert client.post("/api/studio/layouts/does-not-exist/promote").status_code == 404


def test_import_rejects_oversized_upload(client, monkeypatch):
    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")
    oversized = b"x" * (12 * 1024 * 1024 + 1)
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        files={"file": ("big.png", oversized, "image/png")},
    )
    assert r.status_code == 413


def test_import_via_image_url_rejects_non_http_scheme(client):
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "ftp://example.com/x.png"},
    )
    assert r.status_code == 422


def test_import_without_file_or_url_returns_422(client):
    r = client.post("/api/studio/use-cases/calorie/import")
    assert r.status_code == 422


def test_import_via_image_url_fetches_and_stores(client, monkeypatch):
    import urllib.request

    from src.services import studio

    class _FakeHeaders:
        def get(self, key, default=None):
            return "image/png" if key == "Content-Type" else default

    class _FakeUrlResp:
        headers = _FakeHeaders()
        url = "https://example.com/screenshot.png"

        def read(self, n=-1):
            return _PNG

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeUrlResp())
    monkeypatch.setattr(
        studio,
        "import_from_image",
        lambda key, data, mime: {
            "label": "From URL",
            "inspired_by": "reference screenshot",
            "config": {
                "title": "T",
                "components": [{"id": "a", "type": "text_input", "label": "A"}],
            },
        },
    )
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "https://example.com/screenshot.png"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "From URL"


def test_import_via_image_url_non_image_content_type_422(client, monkeypatch):
    import urllib.request

    class _FakeHeaders:
        def get(self, key, default=None):
            return "text/html" if key == "Content-Type" else default

    class _FakeUrlResp:
        headers = _FakeHeaders()
        url = "https://example.com/page.html"

        def read(self, n=-1):
            return b"<html></html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeUrlResp())
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "https://example.com/page.html"},
    )
    assert r.status_code == 422


def test_import_via_image_url_network_failure_422(client, monkeypatch):
    import urllib.request

    def boom(req, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "https://example.com/x.png"},
    )
    assert r.status_code == 422
