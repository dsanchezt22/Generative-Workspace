"""Evolving user profile store + interview accretion (R-801/R-802).

DB-layer tests exercise src.db.profile_* directly (cap/dedup/ordering are
storage-layer concerns). Route tests exercise the HTTP surface, owner-gating
(R-903), request validation, and the accretion seam on generate/preview.
"""

import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.routes.modules import _activity_fact, _prompt_goal_fact
from src.schema import ModuleConfig

from tests.conftest import gen_result as _gr

VALID_RAW = json.dumps(
    {
        "title": "Workout Log",
        "components": [{"id": "exercise", "type": "text_input", "label": "Exercise"}],
    }
)


# ---------------------------------------------------------------------------
# DB layer: add/list/update/delete/clear, ordering, dedup, cap.
# ---------------------------------------------------------------------------


def test_profile_add_and_list(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    entry = db.profile_add("owner-a", "fact", "Lives in Austin", source="manual")
    assert entry["kind"] == "fact"
    assert entry["text"] == "Lives in Austin"
    assert entry["source"] == "manual"
    assert entry["owner"] == "owner-a"
    listed = db.profile_list("owner-a")
    assert len(listed) == 1
    assert listed[0]["id"] == entry["id"]


def test_profile_list_orders_most_recently_updated_first(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    first = db.profile_add("owner-a", "fact", "First fact", source="manual")
    db.profile_add("owner-a", "fact", "Second fact", source="manual")
    # Touch the first entry so it becomes the most recently updated.
    db.profile_update("owner-a", first["id"], "First fact, edited")
    listed = db.profile_list("owner-a")
    assert listed[0]["id"] == first["id"]
    assert listed[0]["text"] == "First fact, edited"


def test_profile_update(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    entry = db.profile_add("owner-a", "goal", "Run a 5k", source="manual")
    updated = db.profile_update("owner-a", entry["id"], "Run a 10k")
    assert updated is not None
    assert updated["text"] == "Run a 10k"
    assert updated["id"] == entry["id"]


def test_profile_update_unknown_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    assert db.profile_update("owner-a", "nope", "x") is None


def test_profile_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    entry = db.profile_add("owner-a", "fact", "Deletable", source="manual")
    assert db.profile_delete("owner-a", entry["id"]) is True
    assert db.profile_list("owner-a") == []


def test_profile_delete_unknown_returns_false(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    assert db.profile_delete("owner-a", "nope") is False


def test_profile_clear_returns_count_and_empties(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.profile_add("owner-a", "fact", "One", source="manual")
    db.profile_add("owner-a", "goal", "Two", source="manual")
    assert db.profile_clear("owner-a") == 2
    assert db.profile_list("owner-a") == []


def test_profile_owner_isolation_at_db_layer(tmp_path, monkeypatch):
    """R-903 hard isolation: owner B never sees owner A's facts."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.profile_add("owner-a", "fact", "A's secret", source="manual")
    db.profile_add("owner-b", "fact", "B's secret", source="manual")
    a_texts = [e["text"] for e in db.profile_list("owner-a")]
    b_texts = [e["text"] for e in db.profile_list("owner-b")]
    assert a_texts == ["A's secret"]
    assert b_texts == ["B's secret"]


def test_profile_add_dedup_same_owner_kind_case_insensitive(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    first = db.profile_add("owner-a", "fact", "Owns a cat", source="manual")
    again = db.profile_add("owner-a", "fact", "OWNS A CAT", source="manual")
    assert again["id"] == first["id"]
    assert len(db.profile_list("owner-a")) == 1


def test_profile_add_no_dedup_across_different_kinds(tmp_path, monkeypatch):
    """Dedup is scoped to owner+kind — the same text under a different kind is
    a distinct fact (e.g. "run a 5k" as a stated goal vs. a logged activity)."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    db.profile_add("owner-a", "goal", "Run a 5k", source="manual")
    db.profile_add("owner-a", "pattern", "Run a 5k", source="manual")
    assert len(db.profile_list("owner-a")) == 2


def test_profile_add_cap_enforced_prunes_oldest(tmp_path, monkeypatch):
    """51st distinct add must not exceed the 50-fact cap — the oldest
    (by updated_at) row is pruned rather than the add being refused."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    first = db.profile_add("owner-a", "fact", "fact-0", source="manual")
    for i in range(1, 51):
        db.profile_add("owner-a", "fact", f"fact-{i}", source="manual")
    listed = db.profile_list("owner-a")
    assert len(listed) == 50
    ids = {e["id"] for e in listed}
    assert first["id"] not in ids  # the oldest was pruned
    texts = {e["text"] for e in listed}
    assert "fact-50" in texts  # the newest survives


# ---------------------------------------------------------------------------
# Route layer: CRUD, validation, owner-gating.
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def second_client():
    with TestClient(app) as c:
        yield c


def test_list_profile_empty(client):
    resp = client.get("/api/profile")
    assert resp.status_code == 200
    assert resp.json() == []


def test_add_profile_manual_appears_in_list(client):
    resp = client.post("/api/profile", json={"kind": "fact", "text": "Prefers dark mode"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["kind"] == "fact"
    assert body["text"] == "Prefers dark mode"
    assert body["source"] == "manual"
    listed = client.get("/api/profile").json()
    assert len(listed) == 1
    assert listed[0]["text"] == "Prefers dark mode"


def test_add_profile_dedup_does_not_double_add(client):
    client.post("/api/profile", json={"kind": "fact", "text": "Owns a cat"})
    client.post("/api/profile", json={"kind": "fact", "text": "owns a cat"})
    assert len(client.get("/api/profile").json()) == 1


def test_add_profile_rejects_bad_kind(client):
    resp = client.post("/api/profile", json={"kind": "nonsense", "text": "x"})
    assert resp.status_code == 422


def test_add_profile_rejects_overlong_text(client):
    resp = client.post("/api/profile", json={"kind": "fact", "text": "x" * 501})
    assert resp.status_code == 422


def test_add_profile_rejects_empty_text(client):
    resp = client.post("/api/profile", json={"kind": "fact", "text": "   "})
    assert resp.status_code == 422


def test_patch_profile_updates_text(client):
    created = client.post("/api/profile", json={"kind": "goal", "text": "Run a 5k"}).json()
    resp = client.patch(f"/api/profile/{created['id']}", json={"text": "Run a 10k"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "Run a 10k"


def test_patch_profile_rejects_overlong_text(client):
    created = client.post("/api/profile", json={"kind": "goal", "text": "Run a 5k"}).json()
    resp = client.patch(f"/api/profile/{created['id']}", json={"text": "x" * 501})
    assert resp.status_code == 422


def test_patch_profile_rejects_empty_text(client):
    created = client.post("/api/profile", json={"kind": "goal", "text": "Run a 5k"}).json()
    resp = client.patch(f"/api/profile/{created['id']}", json={"text": "   "})
    assert resp.status_code == 422


def test_patch_unknown_profile_returns_404(client):
    resp = client.patch("/api/profile/nope", json={"text": "x"})
    assert resp.status_code == 404


def test_delete_profile_removes_it(client):
    created = client.post("/api/profile", json={"kind": "fact", "text": "Deletable"}).json()
    resp = client.delete(f"/api/profile/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/api/profile").json() == []


def test_delete_unknown_profile_returns_404(client):
    resp = client.delete("/api/profile/nope")
    assert resp.status_code == 404


def test_clear_profile_removes_all(client):
    client.post("/api/profile", json={"kind": "fact", "text": "One"})
    client.post("/api/profile", json={"kind": "goal", "text": "Two"})
    resp = client.delete("/api/profile")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == 2
    assert client.get("/api/profile").json() == []


def test_profile_scoped_to_session(client, second_client):
    client.post("/api/profile", json={"kind": "fact", "text": "Client one's fact"})
    # second_client has its own (anonymous) session — sees nothing of client's.
    assert second_client.get("/api/profile").json() == []


def test_profile_routes_owner_scoped_cross_owner_claimed_clients(tmp_path, monkeypatch):
    """R-903 hard isolation via two CLAIMED identities (not just two anonymous
    sessions) — owner B must never see owner A's profile facts."""
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    user_a = db.create_user("Alice")
    user_b = db.create_user("Bob")
    with TestClient(app) as device_a, TestClient(app) as device_b:
        assert (
            device_a.post("/api/auth/claim", json={"token": user_a["invite_token"]}).status_code
            == 200
        )
        assert (
            device_b.post("/api/auth/claim", json={"token": user_b["invite_token"]}).status_code
            == 200
        )
        device_a.post("/api/profile", json={"kind": "fact", "text": "Alice's secret"})
        device_b.post("/api/profile", json={"kind": "fact", "text": "Bob's secret"})
        a_texts = [e["text"] for e in device_a.get("/api/profile").json()]
        b_texts = [e["text"] for e in device_b.get("/api/profile").json()]
        assert a_texts == ["Alice's secret"]
        assert b_texts == ["Bob's secret"]


def test_profile_routes_require_owner_when_anon_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    with TestClient(app) as c:
        assert c.get("/api/profile").status_code == 401
        assert c.post("/api/profile", json={"kind": "fact", "text": "x"}).status_code == 401


# ---------------------------------------------------------------------------
# Accretion (R-802): accretion fires on the CONFIRMED insert (POST /api/modules)
# that carries the interview exchange — not on preview/generate. So a discarded
# draft never enters the profile; only a proposal the user actually accepted does.
# ---------------------------------------------------------------------------

CONFIG = {
    "title": "Workout Log",
    "components": [{"id": "exercise", "type": "text_input", "label": "Exercise"}],
}


def test_insert_with_exchange_accretes_an_interview_fact(client):
    exchange = [{"question": "What's your goal?", "answer": "I want to lose 10 pounds"}]
    resp = client.post(
        "/api/modules",
        json={"configs": [CONFIG], "prompt": "track my weight", "exchange": exchange},
    )
    assert resp.status_code == 201, resp.text
    interview = [p for p in client.get("/api/profile").json() if p["source"] == "interview"]
    assert len(interview) == 1
    assert interview[0]["text"] == "I want to lose 10 pounds"
    assert interview[0]["kind"] == "goal"  # heuristic: "want"/"goal" → goal


def test_insert_with_exchange_accretes_a_fact_kind(client):
    exchange = [{"question": "Where do you live?", "answer": "Austin, Texas"}]
    resp = client.post(
        "/api/modules",
        json={"configs": [CONFIG], "prompt": "plan my week", "exchange": exchange},
    )
    assert resp.status_code == 201, resp.text
    interview = [p for p in client.get("/api/profile").json() if p["source"] == "interview"]
    assert len(interview) == 1
    assert interview[0]["text"] == "Austin, Texas"
    assert interview[0]["kind"] == "fact"  # no goal/want/track keyword


def test_insert_without_exchange_accretes_no_interview_fact(client):
    resp = client.post("/api/modules", json={"configs": [CONFIG], "prompt": "track my weight"})
    assert resp.status_code == 201, resp.text
    # (prompt/activity accretion may fire — see the R-802-completion section below —
    # but interview facts require an exchange.)
    assert [p for p in client.get("/api/profile").json() if p["source"] == "interview"] == []


def test_preview_does_not_accrete(client):
    """The accretion seam moved OFF preview — a preview draft the user may still
    discard must never touch the profile (R-802)."""
    exchange = [{"question": "Where do you live?", "answer": "Austin, Texas"}]
    with (
        patch("src.services.orchestrator.llm.is_stub_mode", return_value=False),
        patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)),
    ):
        resp = client.post(
            "/api/modules/preview",
            json={"prompt": "plan my week", "exchange": exchange},
        )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/profile").json() == []


def test_generate_does_not_accrete(client):
    """The accretion seam also moved OFF generate (the direct-build path)."""
    exchange = [{"question": "What's your goal?", "answer": "I want to lose 10 pounds"}]
    with (
        patch("src.services.orchestrator.llm.is_stub_mode", return_value=False),
        patch("src.services.orchestrator.llm.generate", return_value=_gr(VALID_RAW)),
    ):
        resp = client.post(
            "/api/modules/generate",
            json={"prompt": "track my weight", "exchange": exchange},
        )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/profile").json() == []


def test_insert_accretion_is_bounded_to_three_facts(client):
    exchange = [{"question": f"Q{i}?", "answer": f"Answer {i}"} for i in range(1, 5)]
    resp = client.post(
        "/api/modules",
        json={"configs": [CONFIG], "prompt": "plan my trip", "exchange": exchange},
    )
    assert resp.status_code == 201, resp.text
    interview = [p for p in client.get("/api/profile").json() if p["source"] == "interview"]
    assert len(interview) == 3


def test_insert_accretion_is_owner_scoped(client, second_client):
    exchange = [{"question": "Goal?", "answer": "I want to run a marathon"}]
    client.post(
        "/api/modules",
        json={"configs": [CONFIG], "prompt": "track my training", "exchange": exchange},
    )
    # second_client is a different (anonymous) owner — never sees client's accreted fact.
    assert second_client.get("/api/profile").json() == []


# ---------------------------------------------------------------------------
# R-802 completion: prompt- + activity-derived accretion, SAME confirmed-insert
# seam as interview accretion above. Conservative by design: ≤1 prompt-fact and
# ≤1 activity-fact per insert, and only on a confident heuristic match — a plain
# build prompt or an unrecognizable tool accretes NOTHING (no noise).
# ---------------------------------------------------------------------------

NEUTRAL_CONFIG = {
    "title": "Notes",
    "components": [{"id": "note", "type": "text_input", "label": "Note"}],
}

NUTRITION_CONFIG = {
    "title": "Calorie Tracker",
    "components": [{"id": "cal", "type": "text_input", "label": "Calories"}],
}


# --- pure helper: _prompt_goal_fact ---


@pytest.mark.parametrize(
    "prompt",
    [
        "I want to track my reading",
        "my goal is to save money",
        "track my sleep",
        "I prefer short workouts",
        "I'm trying to read more",
    ],
)
def test_prompt_goal_fact_detects_goal_statements(prompt):
    fact = _prompt_goal_fact(prompt)
    assert fact == ("goal", prompt)


@pytest.mark.parametrize("prompt", ["add a notes field", "make it blue", "", "   ", None])
def test_prompt_goal_fact_skips_non_goal_prompts(prompt):
    assert _prompt_goal_fact(prompt) is None


@pytest.mark.parametrize(
    "prompt",
    [
        "add a tracking number field",  # "tracking" is not "track"
        "build a trackpad test app",  # "trackpad" is not "track"
        "unwanted side effects widget",  # "unwanted" is not "want"
        "add a racetrack game",  # "racetrack" is not "track"
    ],
)
def test_prompt_goal_fact_matches_whole_words_not_substrings(prompt):
    """Regression (R-802 no-noise): a keyword embedded inside another word must
    NOT trip the gate — these are plain build prompts, not durable goals."""
    assert _prompt_goal_fact(prompt) is None


@pytest.mark.parametrize(
    "prompt",
    [
        "I want to track my reading",
        "my goal is to read more",
        "I prefer mornings",
        "I'm trying to save money",
    ],
)
def test_prompt_goal_fact_still_fires_on_genuine_goals(prompt):
    assert _prompt_goal_fact(prompt) == ("goal", prompt)


def test_prompt_goal_fact_bounds_and_trims_text():
    fact = _prompt_goal_fact("  I want to " + "x" * 400)
    assert fact is not None
    assert fact[1].startswith("I want to")  # leading whitespace trimmed
    assert len(fact[1]) <= 200


# --- pure helper: _activity_fact ---


def _cfg(title: str) -> ModuleConfig:
    return ModuleConfig(title=title, components=[])


@pytest.mark.parametrize(
    ("title", "text"),
    [
        ("Calorie Tracker", "Tracks nutrition"),
        ("Meal Planner", "Tracks nutrition"),
        ("Workout Log", "Tracks workouts"),
        ("Gym Sessions", "Tracks workouts"),
        ("Monthly Budget", "Tracks budget/finances"),
        ("Expense Log", "Tracks budget/finances"),
        ("Habit Tracker", "Tracks habits"),
        ("Sleep Log", "Tracks sleep"),
        ("Reading List", "Tracks reading"),
        ("Mood Journal", "Tracks mood"),
    ],
)
def test_activity_fact_recognizes_known_domains(title, text):
    assert _activity_fact([_cfg(title)]) == ("pattern", text)


@pytest.mark.parametrize(
    "title", ["Notes", "Party Planner", "Booking Dashboard", "Recipe Book", "Address Book"]
)
def test_activity_fact_unrecognized_domain_returns_none(title):
    # "Booking Dashboard" also proves token matching ("booking" must not match a
    # "book" cue), and "Recipe Book"/"Address Book" prove bare "book" is no
    # longer a reading cue (final Stage-4 review: it accreted wrong facts).
    assert _activity_fact([_cfg(title)]) is None


def test_activity_fact_empty_configs_returns_none():
    assert _activity_fact([]) is None


# --- route seam: source="prompt" ---


def test_insert_goal_prompt_accretes_prompt_fact(client):
    resp = client.post(
        "/api/modules",
        json={"configs": [NEUTRAL_CONFIG], "prompt": "I want to track my reading"},
    )
    assert resp.status_code == 201, resp.text
    facts = [p for p in client.get("/api/profile").json() if p["source"] == "prompt"]
    assert len(facts) == 1
    assert facts[0]["kind"] == "goal"
    assert facts[0]["text"] == "I want to track my reading"


def test_insert_non_goal_prompt_accretes_nothing(client):
    resp = client.post(
        "/api/modules", json={"configs": [NEUTRAL_CONFIG], "prompt": "add a notes field"}
    )
    assert resp.status_code == 201, resp.text
    assert client.get("/api/profile").json() == []  # no noise: nothing at all


def test_insert_prompt_fact_text_is_bounded(client):
    resp = client.post(
        "/api/modules",
        json={"configs": [NEUTRAL_CONFIG], "prompt": "I want to " + "x" * 400},
    )
    assert resp.status_code == 201, resp.text
    facts = [p for p in client.get("/api/profile").json() if p["source"] == "prompt"]
    assert len(facts) == 1
    assert len(facts[0]["text"]) <= 200


# --- route seam: source="activity" ---


def test_insert_nutrition_tool_accretes_activity_fact(client):
    resp = client.post(
        "/api/modules",
        json={"configs": [NUTRITION_CONFIG], "prompt": "add a calorie counter"},
    )
    assert resp.status_code == 201, resp.text
    profile = client.get("/api/profile").json()
    activity = [p for p in profile if p["source"] == "activity"]
    assert len(activity) == 1
    assert activity[0]["kind"] == "pattern"
    assert activity[0]["text"] == "Tracks nutrition"
    assert [p for p in profile if p["source"] == "prompt"] == []  # non-goal prompt: none


def test_insert_unrecognizable_tool_accretes_no_activity_fact(client):
    resp = client.post("/api/modules", json={"configs": [NEUTRAL_CONFIG]})
    assert resp.status_code == 201, resp.text
    assert client.get("/api/profile").json() == []


# --- all three sources on one insert; bounded + deduped + owner-scoped ---


def test_all_three_sources_fire_once_and_dedupe_on_repeat(client):
    payload = {
        "configs": [NUTRITION_CONFIG],
        "prompt": "I want to eat healthier",
        "exchange": [{"question": "Goal?", "answer": "I want to lose 10 pounds"}],
    }
    for _ in range(2):  # a second identical insert must not double-add anything
        assert client.post("/api/modules", json=payload).status_code == 201
    profile = client.get("/api/profile").json()
    assert sorted(p["source"] for p in profile) == ["activity", "interview", "prompt"]


def test_prompt_and_activity_accretion_is_owner_scoped(client, second_client):
    resp = second_client.post(
        "/api/modules",
        json={"configs": [NUTRITION_CONFIG], "prompt": "I want to eat healthier"},
    )
    assert resp.status_code == 201, resp.text
    # owner B's insert wrote B's profile (prompt + activity), never owner A's.
    assert client.get("/api/profile").json() == []
    assert len(second_client.get("/api/profile").json()) == 2


def test_failed_insert_accretes_nothing(client):
    # An invalid config fails validation (422) before the insert — accretion
    # only ever runs after a successful insert, so the profile stays empty.
    bad = {
        "configs": [{"title": "Calorie Tracker", "components": [{"id": "x", "type": "nope"}]}],
        "prompt": "I want to eat healthier",
    }
    resp = client.post("/api/modules", json=bad)
    assert resp.status_code == 422
    assert client.get("/api/profile").json() == []
