"""R-1202 completion: generate-route rate limiting + per-owner daily cost cap.

All 5 LLM-backed handlers (generate/preview/generate_from_file/refine/
workspace-insights) share ONE per-owner budget — a preview and a generate
count toward the same window. The check runs right after `_owner_id` resolves
and BEFORE any orchestrator call (fail fast, no spend), so these tests never
need to mock the LLM: stub mode (the deterministic test default — see
conftest._isolate_llm_env) is enough to prove the gate fires before any model
work happens, whatever that work would have returned.
"""

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def second_client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Rate limit: default budget, per-owner isolation, shared across handlers.
# ---------------------------------------------------------------------------


def test_31st_generate_in_window_returns_429(client):
    """AC: default budget is 30 calls / 5 min per owner; the 31st call in the
    window is refused with an honest 429 rather than silently degrading."""
    for _ in range(30):
        resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
        assert resp.status_code != 429, resp.text
    resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert resp.status_code == 429
    assert "too many generations" in resp.json()["detail"].lower()


def test_gen_rate_limit_is_per_owner(client, second_client, monkeypatch):
    """A different owner's budget is untouched by another owner exhausting theirs."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "1")
    assert (
        client.post("/api/modules/preview", json={"prompt": "track my workouts"}).status_code != 429
    )
    blocked = client.post("/api/modules/preview", json={"prompt": "track my workouts"})
    assert blocked.status_code == 429

    still_ok = second_client.post("/api/modules/preview", json={"prompt": "track my workouts"})
    assert still_ok.status_code != 429


def test_gen_rate_limit_shared_between_preview_and_generate(client, monkeypatch):
    """A preview and a generate count toward the SAME owner budget."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "2")
    assert client.post("/api/modules/preview", json={"prompt": "x"}).status_code != 429
    assert client.post("/api/modules/generate", json={"prompt": "y"}).status_code != 429
    # Budget (2) is now spent across two DIFFERENT handlers — a 3rd call to
    # either one is blocked.
    resp = client.post("/api/modules/preview", json={"prompt": "z"})
    assert resp.status_code == 429


def test_gen_rate_limit_shared_with_file_refine_and_insights(client, monkeypatch):
    """The remaining 3 handlers (generate_from_file/refine/insights) also draw
    from the same shared budget — exhausting it via `generate` blocks all three."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "1")
    created = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
    assert created.status_code != 429
    module_id = created.json()["module"]["id"]

    file_resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
        data={"prompt": "build something"},
    )
    assert file_resp.status_code == 429

    refine_resp = client.post(f"/api/modules/{module_id}/refine", json={"prompt": "add a field"})
    assert refine_resp.status_code == 429

    insights_resp = client.post("/api/workspace/insights")
    assert insights_resp.status_code == 429


def test_gen_rate_limit_window_is_configurable(client, monkeypatch):
    """TRUS_GEN_RATE_WINDOW is read fresh per request (not baked in at import),
    so a test (or an operator) can override it without a process restart. The
    block assertion uses a deliberately HUGE window so the 2nd call is in-window
    no matter how slowly this test runs under load/coverage (a 10ms window +
    real sleeps flaked). The sliding/aging behavior itself is owned by the
    injected-clock `_RateLimiter.allow(now=...)` unit test below."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "1")
    monkeypatch.setenv("TRUS_GEN_RATE_WINDOW", "3600")
    from src.routes.deps import _gen_rate_window

    assert _gen_rate_window() == 3600.0  # env re-read now, not baked at import
    assert client.post("/api/modules/preview", json={"prompt": "a"}).status_code != 429
    assert client.post("/api/modules/preview", json={"prompt": "b"}).status_code == 429


# ---------------------------------------------------------------------------
# Layout Studio vision routes draw from the SAME budget (final Stage-4 review:
# import/capture were the last unmetered spend surfaces — R-1202 completion).
# ---------------------------------------------------------------------------

_PNG = b"\x89PNG\r\n\x1a\n"  # minimal header — the gate fires before any image work


def test_studio_import_and_capture_draw_from_the_gen_budget(client, monkeypatch):
    """A 4th studio call in-window is refused with the same 429 the modules.py
    handlers give, and capture shares the same exhausted budget as import."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "3")
    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")
    from src.services import studio as studio_service

    monkeypatch.setattr(
        studio_service.llm,
        "vision_describe",
        lambda *a, **k: '{"title":"X","components":[{"id":"a","type":"text_input","label":"A"}]}',
    )
    for _ in range(3):
        r = client.post(
            "/api/studio/use-cases/calorie/import",
            files={"file": ("ui.png", _PNG, "image/png")},
        )
        assert r.status_code == 200, r.text
    blocked = client.post(
        "/api/studio/use-cases/calorie/import", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert blocked.status_code == 429
    assert "too many generations" in blocked.json()["detail"].lower()
    # capture draws from the SAME per-owner budget — also blocked, and blocked
    # BEFORE any vision work (no mock needed: the gate must fire first).
    blocked_capture = client.post(
        "/api/studio/use-cases/calorie/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert blocked_capture.status_code == 429


def test_studio_generate_route_draws_from_the_gen_budget(client, monkeypatch):
    """Layout mining (POST /use-cases/{key}/generate) calls llm.generate() in
    non-stub mode — same R-1202 spend hole — so a 4th in-window call is 429.
    Stub mode is enough: the gate fires before any generation work."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "3")
    for _ in range(3):
        r = client.post("/api/studio/use-cases/calorie/generate?n=2")
        assert r.status_code != 429, r.text
    blocked = client.post("/api/studio/use-cases/calorie/generate?n=2")
    assert blocked.status_code == 429
    assert "too many generations" in blocked.json()["detail"].lower()


def test_all_studio_gen_routes_share_the_modules_budget(client, monkeypatch):
    """One owner budget across modules-generate + studio generate/import/capture:
    generate + layout-mine + import spend it (MAX=3), then capture → 429."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "3")
    monkeypatch.setenv("TRUS_VISION_MODEL", "fake-vlm")
    from src.services import studio as studio_service

    monkeypatch.setattr(
        studio_service.llm,
        "vision_describe",
        lambda *a, **k: '{"title":"X","components":[{"id":"a","type":"text_input","label":"A"}]}',
    )
    assert client.post("/api/modules/generate", json={"prompt": "track x"}).status_code != 429
    assert client.post("/api/studio/use-cases/calorie/generate?n=2").status_code != 429
    assert (
        client.post(
            "/api/studio/use-cases/calorie/import",
            files={"file": ("ui.png", _PNG, "image/png")},
        ).status_code
        != 429
    )
    # Budget (3) spent across three different generation surfaces — capture 429s.
    blocked = client.post(
        "/api/studio/use-cases/calorie/capture", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert blocked.status_code == 429


def test_studio_and_generate_share_one_owner_budget(client, monkeypatch):
    """3 generates then a studio import → 429. The 429 (not the 503 an
    unconfigured vision model would give) proves the gate fires fail-fast,
    before any vision/LLM call."""
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "3")
    for _ in range(3):
        resp = client.post("/api/modules/generate", json={"prompt": "track my workouts"})
        assert resp.status_code != 429, resp.text
    r = client.post(
        "/api/studio/use-cases/calorie/import", files={"file": ("ui.png", _PNG, "image/png")}
    )
    assert r.status_code == 429


# ---------------------------------------------------------------------------
# Optional per-owner daily cost cap.
# ---------------------------------------------------------------------------


def test_daily_cost_cap_blocks_over_budget_owner(monkeypatch):
    monkeypatch.setenv("TRUS_TOKEN_COST_IN", "1")
    monkeypatch.setenv("TRUS_TOKEN_COST_OUT", "1")
    monkeypatch.setenv("TRUS_DAILY_COST_CAP_USD", "0.001")  # trivially small cap
    user = db.create_user("Ada")
    with TestClient(app) as c:
        claim = c.post("/api/auth/claim", json={"token": user["invite_token"]})
        assert claim.status_code == 200
        # Seed today's spend directly — as if an earlier generation already cost
        # more than the cap ($200 at these rates: (100*1 + 100*1)/1000 * 1000... —
        # concretely: 100 in + 100 out tokens at $1/1k each = $0.2, well over $0.001).
        db.add_gen_event(user["id"], "generate", "ok", "stub", "stub", 10, 100, 100)
        resp = c.post("/api/modules/preview", json={"prompt": "track my reading"})
    assert resp.status_code == 429
    assert resp.json()["detail"] == "You've reached today's usage budget."


def test_daily_cost_cap_unset_never_blocks(monkeypatch):
    monkeypatch.setenv("TRUS_TOKEN_COST_IN", "1")
    monkeypatch.setenv("TRUS_TOKEN_COST_OUT", "1")
    # TRUS_DAILY_COST_CAP_USD left unset.
    user = db.create_user("Bea")
    with TestClient(app) as c:
        c.post("/api/auth/claim", json={"token": user["invite_token"]})
        db.add_gen_event(user["id"], "generate", "ok", "stub", "stub", 10, 1_000_000, 1_000_000)
        resp = c.post("/api/modules/preview", json={"prompt": "track my reading"})
    assert resp.status_code != 429


def test_daily_cost_cap_of_zero_never_blocks(monkeypatch):
    """The spec's cap gate is '> 0' — an explicit 0 behaves like unset."""
    monkeypatch.setenv("TRUS_TOKEN_COST_IN", "1")
    monkeypatch.setenv("TRUS_DAILY_COST_CAP_USD", "0")
    user = db.create_user("Cid")
    with TestClient(app) as c:
        c.post("/api/auth/claim", json={"token": user["invite_token"]})
        db.add_gen_event(user["id"], "generate", "ok", "stub", "stub", 10, 1_000_000, 0)
        resp = c.post("/api/modules/preview", json={"prompt": "track my reading"})
    assert resp.status_code != 429


def test_daily_cost_cap_zero_rates_never_blocks_regardless_of_cap(monkeypatch):
    """Default $0 token rates mean cost_usd is always 0 — a cap can never bind
    no matter how much volume an owner has generated."""
    monkeypatch.setenv("TRUS_DAILY_COST_CAP_USD", "0.0001")
    user = db.create_user("Dee")
    with TestClient(app) as c:
        c.post("/api/auth/claim", json={"token": user["invite_token"]})
        db.add_gen_event(user["id"], "generate", "ok", "stub", "stub", 10, 1_000_000, 1_000_000)
        resp = c.post("/api/modules/preview", json={"prompt": "track my reading"})
    assert resp.status_code != 429


# ---------------------------------------------------------------------------
# db.owner_cost_today — owner + UTC-day isolation.
# ---------------------------------------------------------------------------


def test_owner_cost_today_scopes_to_owner_and_today(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_TOKEN_COST_IN", "2")
    monkeypatch.setenv("TRUS_TOKEN_COST_OUT", "3")
    db.init_db()
    db.add_gen_event("owner-a", "generate", "ok", "stub", "stub", 10, 1000, 1000)  # today
    with db._conn() as c:
        c.execute(
            "INSERT INTO gen_events (id, owner, kind, outcome, provider, model,"
            " latency_ms, tokens_in, tokens_out, created_at)"
            " VALUES ('old', 'owner-a', 'generate', 'ok', 'stub', 'stub', 10, 5000, 5000,"
            " '2020-01-01T00:00:00+00:00')"
        )
    db.add_gen_event("owner-b", "generate", "ok", "stub", "stub", 10, 1000, 1000)  # different owner

    result = db.owner_cost_today("owner-a")

    assert result["tokens_in"] == 1000
    assert result["tokens_out"] == 1000
    assert result["cost_usd"] == pytest.approx((1000 * 2 + 1000 * 3) / 1000)


def test_owner_cost_today_zero_rates_cost_zero_but_tokens_present(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    db.add_gen_event("owner-a", "generate", "ok", "stub", "stub", 10, 500, 500)

    result = db.owner_cost_today("owner-a")

    assert result["tokens_in"] == 500
    assert result["tokens_out"] == 500
    assert result["cost_usd"] == 0


# ---------------------------------------------------------------------------
# _RateLimiter (moved to routes/deps.py — see also test_transcribe.py, whose
# `from src.routes.transcribe import _RateLimiter` imports keep working via
# transcribe.py's re-export of the same class).
# ---------------------------------------------------------------------------


def test_rate_limiter_reexported_from_transcribe_is_the_same_class():
    from src.routes.deps import _RateLimiter as DepsLimiter
    from src.routes.transcribe import _RateLimiter as TranscribeLimiter

    assert DepsLimiter is TranscribeLimiter


def test_rate_limiter_allow_overrides_take_precedence_over_instance_defaults():
    from src.routes.deps import _RateLimiter

    limiter = _RateLimiter(max_calls=100, window_secs=100)  # generous instance defaults
    assert limiter.allow("k", now=0.0, max_calls=2, window_secs=10)
    assert limiter.allow("k", now=0.0, max_calls=2, window_secs=10)
    assert not limiter.allow("k", now=0.0, max_calls=2, window_secs=10)
    # The window override is honored too — sliding past it re-admits the key.
    assert limiter.allow("k", now=11.0, max_calls=2, window_secs=10)
