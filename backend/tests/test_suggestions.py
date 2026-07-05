"""Per-owner usage-seeded suggestions (R-104). R-903: another owner's prompts
must NEVER appear — see the cross-owner isolation test below."""

from fastapi.testclient import TestClient
from src import db, semantic_cache
from src.main import app

# ---------------------------------------------------------------------------
# db.suggestion_prompts — db-level
# ---------------------------------------------------------------------------


def test_new_owner_has_no_suggestions():
    db.init_db()
    owner = db.ensure_session(None)
    assert db.suggestion_prompts(owner, 5) == []


def test_populated_after_a_generation_is_cached():
    db.init_db()
    owner = db.ensure_session(None)
    semantic_cache.store("system", "track my workouts", [{"title": "Workout Log"}], owner=owner)
    assert db.suggestion_prompts(owner, 5) == ["track my workouts"]


def test_ordering_favors_hits_over_recency():
    db.init_db()
    owner = db.ensure_session(None)
    semantic_cache.store("system", "plan a road trip", [{"title": "Trip"}], owner=owner)
    semantic_cache.store("system", "track my workouts", [{"title": "Workout"}], owner=owner)
    # "plan a road trip" was stored first (older) but gets reused (exact-match
    # lookup bumps hits) — it must outrank the newer, never-reused prompt.
    mode, _ = semantic_cache.lookup("system", "plan a road trip", owner=owner)
    assert mode == "hit"
    assert db.suggestion_prompts(owner, 5) == ["plan a road trip", "track my workouts"]


def test_dedup_is_case_insensitive():
    db.init_db()
    owner = db.ensure_session(None)
    semantic_cache.store("system", "Track My Workouts", [{"title": "a"}], owner=owner)
    semantic_cache.store("system", "track my workouts", [{"title": "b"}], owner=owner)
    prompts = db.suggestion_prompts(owner, 5)
    assert len(prompts) == 1
    assert prompts[0].lower() == "track my workouts"


def test_blob_like_prompts_are_excluded():
    db.init_db()
    owner = db.ensure_session(None)
    blob = "x" * 201
    semantic_cache.store("system", blob, [{"title": "a"}], owner=owner)
    semantic_cache.store("system", "track my workouts", [{"title": "b"}], owner=owner)
    prompts = db.suggestion_prompts(owner, 5)
    assert blob not in prompts
    assert prompts == ["track my workouts"]


def test_empty_prompt_is_excluded():
    db.init_db()
    owner = db.ensure_session(None)
    semantic_cache.store("system", "   ", [{"title": "a"}], owner=owner)
    assert db.suggestion_prompts(owner, 5) == []


def test_messages_top_up_when_cache_is_short():
    db.init_db()
    owner = db.ensure_session(None)
    semantic_cache.store("system", "track my workouts", [{"title": "a"}], owner=owner)
    db.add_message(owner, "user", "plan my week", page_id="p1")
    db.add_message(owner, "assistant", "Created Planner", page_id="p1")
    db.add_message(owner, "user", "monthly budget tracker", page_id="p2")
    prompts = db.suggestion_prompts(owner, 5)
    assert prompts[0] == "track my workouts"  # gen_cache contribution stays first
    assert "plan my week" in prompts
    assert "monthly budget tracker" in prompts
    assert "Created Planner" not in prompts  # assistant-role rows never counted


def test_messages_never_duplicate_what_gen_cache_already_gave():
    db.init_db()
    owner = db.ensure_session(None)
    semantic_cache.store("system", "track my workouts", [{"title": "a"}], owner=owner)
    db.add_message(owner, "user", "Track My Workouts", page_id="p1")  # same, different case
    prompts = db.suggestion_prompts(owner, 5)
    assert len(prompts) == 1


def test_limit_caps_the_returned_count():
    db.init_db()
    owner = db.ensure_session(None)
    for i in range(8):
        semantic_cache.store("system", f"idea number {i}", [{"title": "a"}], owner=owner)
    assert len(db.suggestion_prompts(owner, 3)) == 3


# ---------------------------------------------------------------------------
# Stage-2b backlog: server-side noise filter (moved from suggestions.ts) —
# a 📎 log line, a refine-combined prompt, a refine imperative, and a terse
# (<3 word) fragment must never surface as a suggestion.
# ---------------------------------------------------------------------------


def test_file_upload_log_line_is_excluded():
    db.init_db()
    owner = db.ensure_session(None)
    db.add_message(owner, "user", "📎 receipt.png: extracted 3 line items", page_id="p1")
    db.add_message(owner, "user", "create a budget tracker", page_id="p1")
    prompts = db.suggestion_prompts(owner, 5)
    assert prompts == ["create a budget tracker"]


def test_refine_combined_preview_prompt_is_excluded():
    db.init_db()
    owner = db.ensure_session(None)
    db.add_message(owner, "user", "Create a workout log — add a rest-day checkbox", page_id="p1")
    db.add_message(owner, "user", "Create a workout log", page_id="p1")
    prompts = db.suggestion_prompts(owner, 5)
    assert prompts == ["Create a workout log"]


def test_refine_imperative_prefix_is_excluded():
    db.init_db()
    owner = db.ensure_session(None)
    db.add_message(owner, "user", "make it a bar chart instead", page_id="p1")
    db.add_message(owner, "user", "change the currency to euros", page_id="p1")
    db.add_message(owner, "user", "create a savings goal tracker", page_id="p1")
    prompts = db.suggestion_prompts(owner, 5)
    assert prompts == ["create a savings goal tracker"]


def test_terse_fragment_under_three_words_is_excluded():
    db.init_db()
    owner = db.ensure_session(None)
    db.add_message(owner, "user", "budget", page_id="p1")
    db.add_message(owner, "user", "add columns", page_id="p1")
    db.add_message(owner, "user", "create a reading list", page_id="p1")
    prompts = db.suggestion_prompts(owner, 5)
    assert prompts == ["create a reading list"]


# ---------------------------------------------------------------------------
# GET /api/suggestions — route-level
# ---------------------------------------------------------------------------


def _claimed_client(name: str) -> tuple[TestClient, str]:
    user = db.create_user(name)
    client = TestClient(app)
    client.__enter__()
    resp = client.post("/api/auth/claim", json={"token": user["invite_token"]})
    assert resp.status_code == 200
    return client, user["id"]


def test_cross_owner_isolation_r903():
    """R-903 HARD RULE: owner B must never see owner A's prompts."""
    db.init_db()
    client_a, owner_a = _claimed_client("Alice")
    client_b, owner_b = _claimed_client("Bob")
    try:
        semantic_cache.store(
            "system", "Alice's very distinctive garden planner", [{"title": "a"}], owner=owner_a
        )
        semantic_cache.store(
            "system", "Bob's very distinctive invoice tool", [{"title": "b"}], owner=owner_b
        )

        resp_a = client_a.get("/api/suggestions")
        resp_b = client_b.get("/api/suggestions")
        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        prompts_a = [s["prompt"] for s in resp_a.json()]
        prompts_b = [s["prompt"] for s in resp_b.json()]

        assert "Alice's very distinctive garden planner" in prompts_a
        assert "Bob's very distinctive invoice tool" not in prompts_a

        assert "Bob's very distinctive invoice tool" in prompts_b
        assert "Alice's very distinctive garden planner" not in prompts_b
    finally:
        client_a.__exit__(None, None, None)
        client_b.__exit__(None, None, None)


def test_route_response_shape_is_prompt_objects():
    db.init_db()
    client, owner = _claimed_client("Carol")
    try:
        semantic_cache.store("system", "track my workouts", [{"title": "a"}], owner=owner)
        resp = client.get("/api/suggestions")
        assert resp.status_code == 200
        assert resp.json() == [{"prompt": "track my workouts"}]
    finally:
        client.__exit__(None, None, None)


def test_limit_clamps_above_ten():
    db.init_db()
    client, owner = _claimed_client("Dave")
    try:
        for i in range(15):
            semantic_cache.store("system", f"idea number {i}", [{"title": "a"}], owner=owner)
        resp = client.get("/api/suggestions?limit=100")
        assert resp.status_code == 200
        assert len(resp.json()) == 10
    finally:
        client.__exit__(None, None, None)


def test_limit_clamps_below_one():
    db.init_db()
    client, owner = _claimed_client("Erin")
    try:
        semantic_cache.store("system", "track my workouts", [{"title": "a"}], owner=owner)
        resp = client.get("/api/suggestions?limit=0")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
    finally:
        client.__exit__(None, None, None)


def test_default_limit_is_five():
    db.init_db()
    client, owner = _claimed_client("Frank")
    try:
        for i in range(8):
            semantic_cache.store("system", f"idea number {i}", [{"title": "a"}], owner=owner)
        resp = client.get("/api/suggestions")
        assert resp.status_code == 200
        assert len(resp.json()) == 5
    finally:
        client.__exit__(None, None, None)


def test_route_never_returns_noise_seeded_into_messages():
    """Stage-2b backlog: a 📎 file-upload log line and a refine-combined
    prompt seeded into `messages` must never appear in the API response."""
    db.init_db()
    client, owner = _claimed_client("Grace")
    try:
        db.add_message(owner, "user", "📎 receipt.png: extracted 3 line items", page_id="p1")
        db.add_message(
            owner, "user", "Create a workout log — add a rest-day checkbox", page_id="p1"
        )
        db.add_message(owner, "user", "Create a distinctive workout log", page_id="p1")
        resp = client.get("/api/suggestions")
        assert resp.status_code == 200
        prompts = [s["prompt"] for s in resp.json()]
        assert "📎 receipt.png: extracted 3 line items" not in prompts
        assert "Create a workout log — add a rest-day checkbox" not in prompts
        assert "Create a distinctive workout log" in prompts
    finally:
        client.__exit__(None, None, None)
