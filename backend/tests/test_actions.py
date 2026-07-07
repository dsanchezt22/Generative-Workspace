"""The action registry: tier-routing truth table + every executor.

All time is injected (an ExecContext carries `now`); no sleeps. Executors are
exercised against a real (isolated) SQLite file via the db layer.
"""

from datetime import datetime, timezone

import pytest
from src import db, llm
from src.schema import ModuleConfig
from src.services import actions

from tests.conftest import fake_generate

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _ctx(state=None, page_id=None, interval=None):
    return actions.ExecContext(
        automation_id="a1", page_id=page_id, state=state or {}, now=NOW, interval_secs=interval
    )


def _ensure_owner(owner):
    """Give an arbitrary owner id a sessions row so module inserts satisfy the
    session_id foreign key (owner == session id in dev, R-903)."""
    with db._conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO sessions (id, created_at) VALUES (?, ?)", (owner, db._now())
        )
    return owner


def _mk_module(owner, components, state=None, title="M"):
    _ensure_owner(owner)
    cfg = ModuleConfig(title=title, components=components, state=state or {})
    return db.insert_module(owner, cfg)


# ── requires_approval truth table (AUT-1/AUT-4) ──────────────────────────────


def _expected(spec, dial):
    if spec.irreversible:
        return True
    if dial <= 0:
        return True
    if spec.floor == "consequential":
        return dial < 2
    return False


@pytest.mark.parametrize("action_type", list(actions.ACTION_SPECS))
@pytest.mark.parametrize("dial", [0, 1, 2])
def test_requires_approval_truth_table(action_type, dial):
    spec = actions.ACTION_SPECS[action_type]
    assert actions.requires_approval(action_type, dial) == _expected(spec, dial)


@pytest.mark.parametrize(
    "action_type", [t for t, s in actions.ACTION_SPECS.items() if s.irreversible]
)
def test_irreversible_floor_holds_even_at_dial_2(action_type):
    # The parametrized floor test — any future irreversible type is auto-covered.
    assert actions.requires_approval(action_type, 2) is True


def test_archive_module_runs_at_2_parks_at_1():
    assert actions.requires_approval("archive_module", 1) is True
    assert actions.requires_approval("archive_module", 2) is False


def test_track_parks_at_0_runs_at_1():
    assert actions.requires_approval("track", 0) is True
    assert actions.requires_approval("track", 1) is False


def test_unknown_type_raises_keyerror():
    with pytest.raises(KeyError):
        actions.requires_approval("bogus", 1)


def test_registry_has_twelve_types():
    assert len(actions.ACTION_SPECS) == 12


# ── registry invariants (fail-closed floor, no un-previewed irreversible spend) ─

# The ONE reviewed-reversible exception on the consequential floor (archive is
# restorable from Archived). Any other consequential spec must be irreversible.
_REVIEWED_REVERSIBLE_CONSEQUENTIAL = {"archive_module"}


def test_no_spec_is_both_llm_and_irreversible():
    # _freeze_payload is a no-op for uses_llm actions (zero-spend park freezes the
    # SPEC, not composed content), so a spec with both flags would let "approve"
    # authorize model output never previewed for an irreversible delivery. A
    # future compose-and-send must use two-stage approval instead.
    for action_type, spec in actions.ACTION_SPECS.items():
        assert not (spec.uses_llm and spec.irreversible), (
            f"{action_type}: uses_llm+irreversible authorizes un-previewed model "
            "output for irreversible delivery — use two-stage approval instead"
        )


def test_consequential_floor_is_irreversible_unless_allowlisted():
    # Fail-closed: a new consequential executor is irreversible=True until
    # explicitly reviewed down into the allowlist above.
    for action_type, spec in actions.ACTION_SPECS.items():
        if spec.floor == "consequential" and action_type not in _REVIEWED_REVERSIBLE_CONSEQUENTIAL:
            assert spec.irreversible, (
                f"{action_type}: consequential executors are irreversible=True until "
                "explicitly reviewed down (add to the allowlist with a reason)"
            )


# ── watch: edge-triggered via state_json.armed ───────────────────────────────


def test_watch_edge_trigger_writes_disarms_rearms(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "temp", "type": "number_input", "label": "Temp"}], {})
    payload = {
        "type": "watch",
        "provider": "weather",
        "query": {"place": "SF"},
        "module_id": m.id,
        "component_id": "temp",
        "op": "over",
        "threshold": 30,
    }
    monkeypatch.setattr(
        "src.services.live_data.fetch", lambda *a, **k: {"value": 32.0, "error": None}
    )
    # cross while armed → write value + disarm
    res = actions.ACTION_SPECS["watch"].execute(owner, payload, _ctx({}))
    assert res.result["flagged"] is True
    assert res.state == {"armed": False}
    assert db.get_module(owner, m.id).config.state["temp"] == 32.0

    # still above, but disarmed → no re-fire, no state change
    res2 = actions.ACTION_SPECS["watch"].execute(owner, payload, _ctx({"armed": False}))
    assert res2.result["flagged"] is False
    assert res2.state is None

    # back under → re-arm
    monkeypatch.setattr(
        "src.services.live_data.fetch", lambda *a, **k: {"value": 25.0, "error": None}
    )
    res3 = actions.ACTION_SPECS["watch"].execute(owner, payload, _ctx({"armed": False}))
    assert res3.result["flagged"] is False
    assert res3.state == {"armed": True}


def test_watch_no_threshold_just_reports(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "t", "type": "number_input", "label": "T"}], {})
    monkeypatch.setattr(
        "src.services.live_data.fetch", lambda *a, **k: {"value": 21.0, "error": None}
    )
    res = actions.ACTION_SPECS["watch"].execute(
        owner,
        {
            "type": "watch",
            "provider": "weather",
            "query": {},
            "module_id": m.id,
            "component_id": "t",
        },
        _ctx({}),
    )
    assert res.result["flagged"] is False and res.state is None


def test_watch_provider_error_is_not_flagged(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "t", "type": "number_input", "label": "T"}], {})
    monkeypatch.setattr(
        "src.services.live_data.fetch",
        lambda *a, **k: {"value": None, "error": "Could not reach Open-Meteo"},
    )
    res = actions.ACTION_SPECS["watch"].execute(
        owner,
        {
            "type": "watch",
            "provider": "weather",
            "query": {},
            "module_id": m.id,
            "component_id": "t",
            "op": "over",
            "threshold": 30,
        },
        _ctx({}),
    )
    assert res.result["flagged"] is False
    assert res.result["error"] == "Could not reach Open-Meteo"


def test_watch_alert_lands_feed_entry(monkeypatch):
    owner = "o"
    m = _mk_module(
        owner,
        [
            {"id": "temp", "type": "number_input", "label": "Temp"},
            {"id": "feed", "type": "list", "label": "Alerts"},
        ],
        {},
    )
    payload = {
        "type": "watch",
        "provider": "weather",
        "query": {"place": "SF"},
        "module_id": m.id,
        "component_id": "temp",
        "op": "over",
        "threshold": 30,
        "feed_module_id": m.id,
        "feed_component_id": "feed",
    }
    monkeypatch.setattr(
        "src.services.live_data.fetch", lambda *a, **k: {"value": 32.0, "error": None}
    )
    actions.ACTION_SPECS["watch"].execute(owner, payload, _ctx({}))
    feed = db.get_module(owner, m.id).config.state["feed"]
    assert isinstance(feed, list) and feed[0]["badge"] == "alert"


# ── _write_state: optimistic rev, retry then yield (HUMAN WINS) ──────────────


def test_write_state_retries_then_applies(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "c", "type": "note", "label": "N"}], {"c": "old"})
    real = db.update_module
    calls = {"n": 0}

    def flaky(session, mid, cfg, expected_rev=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise db.RevConflict(db.get_module(owner, mid))
        return real(session, mid, cfg, expected_rev=None)

    monkeypatch.setattr(db, "update_module", flaky)
    assert actions._write_state(owner, m.id, "c", "new") is True
    assert calls["n"] == 2
    assert db.get_module(owner, m.id).config.state["c"] == "new"


def test_write_state_yields_after_three_losses(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "c", "type": "note", "label": "N"}], {"c": "old"})
    calls = {"n": 0}

    def always_conflict(session, mid, cfg, expected_rev=None):
        calls["n"] += 1
        raise db.RevConflict(db.get_module(owner, mid))

    monkeypatch.setattr(db, "update_module", always_conflict)
    with pytest.raises(actions.ConflictYield):
        actions._write_state(owner, m.id, "c", "new")
    assert calls["n"] == 3
    # module untouched
    assert db.get_module(owner, m.id).config.state["c"] == "old"


def test_write_state_missing_module_returns_false():
    assert actions._write_state("o", "nope", "c", "v") is False


# ── sort / track ─────────────────────────────────────────────────────────────


def test_sort_reorders_by_field():
    owner = "o"
    items = [{"label": "c"}, {"label": "a"}, {"label": "b"}]
    m = _mk_module(owner, [{"id": "list", "type": "list", "label": "L"}], {"list": items})
    res = actions.ACTION_SPECS["sort"].execute(
        owner, {"type": "sort", "module_id": m.id, "component_id": "list", "by": "label"}, _ctx()
    )
    assert res.result["n"] == 3
    assert [i["label"] for i in db.get_module(owner, m.id).config.state["list"]] == ["a", "b", "c"]


def test_track_appends_source_value_to_series():
    owner = "o"
    src = _mk_module(
        owner, [{"id": "w", "type": "number_input", "label": "W"}], {"w": 180}, title="Src"
    )
    tgt = _mk_module(owner, [{"id": "s", "type": "chart", "label": "S"}], {"s": []}, title="Trend")
    res = actions.ACTION_SPECS["track"].execute(
        owner,
        {
            "type": "track",
            "module_id": tgt.id,
            "component_id": "s",
            "source_module_id": src.id,
            "source_component_id": "w",
            "label": "weight",
        },
        _ctx(),
    )
    series = db.get_module(owner, tgt.id).config.state["s"]
    assert series == [{"date": NOW.date().isoformat(), "value": 180.0}]
    assert res.result["metric"] == "weight"


def test_track_counts_list_items_as_value():
    owner = "o"
    src = _mk_module(owner, [{"id": "l", "type": "list", "label": "L"}], {"l": ["x", "y", "z"]})
    tgt = _mk_module(owner, [{"id": "s", "type": "chart", "label": "S"}], {"s": []})
    actions.ACTION_SPECS["track"].execute(
        owner,
        {
            "type": "track",
            "module_id": tgt.id,
            "component_id": "s",
            "source_module_id": src.id,
            "source_component_id": "l",
        },
        _ctx(),
    )
    assert db.get_module(owner, tgt.id).config.state["s"][0]["value"] == 3.0


def test_sort_missing_target_raises():
    with pytest.raises(ValueError, match="not found"):
        actions.ACTION_SPECS["sort"].execute(
            "o", {"type": "sort", "module_id": "gone", "component_id": "c", "by": "date"}, _ctx()
        )


# ── remind (journal is the product — no messaging channel faked) ─────────────


def test_remind_lists_pending_tracker_subjects():
    owner = "o"
    rows = {"rows": [{"name": "water", "done": []}, {"name": "stretch", "done": ["2026-07-06"]}]}
    m = _mk_module(owner, [{"id": "t", "type": "tracker", "label": "T"}], {"t": rows})
    res = actions.ACTION_SPECS["remind"].execute(
        owner, {"type": "remind", "module_id": m.id, "component_id": "t"}, _ctx()
    )
    assert res.result["pending"] == ["water"]  # stretch is done today


def test_remind_reads_checklist_pending():
    owner = "o"
    items = [{"text": "buy milk", "done": False}, {"text": "call mom", "done": True}]
    m = _mk_module(owner, [{"id": "cl", "type": "checklist", "label": "C"}], {"cl": items})
    res = actions.ACTION_SPECS["remind"].execute(
        owner, {"type": "remind", "module_id": m.id, "component_id": "cl"}, _ctx()
    )
    assert res.result["pending"] == ["buy milk"]


def test_remind_all_done():
    owner = "o"
    rows = {"rows": [{"name": "water", "done": ["2026-07-06"]}]}
    m = _mk_module(owner, [{"id": "t", "type": "tracker", "label": "T"}], {"t": rows})
    res = actions.ACTION_SPECS["remind"].execute(
        owner, {"type": "remind", "module_id": m.id, "component_id": "t"}, _ctx()
    )
    assert res.result["pending"] == []
    assert res.result["body"] == "all done today"


# ── LLM executors (summarize / draft / learn) ────────────────────────────────


def test_summarize_writes_note_and_records_gen_event(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "note", "type": "note", "label": "Digest"}], {"note": ""})
    monkeypatch.setattr(
        "src.services.actions.llm.generate", fake_generate("Everything looks on track.")
    )
    res = actions.ACTION_SPECS["summarize"].execute(
        owner,
        {
            "type": "summarize",
            "module_id": m.id,
            "component_id": "note",
            "source_module_ids": [m.id],
        },
        _ctx(),
    )
    assert db.get_module(owner, m.id).config.state["note"] == "Everything looks on track."
    assert res.result["name"] == "M"
    # gen_event kind='automation' recorded so the cost cap self-enforces
    assert db.gen_stats(days=1)["total"] >= 1


def test_summarize_falls_back_to_page_modules(monkeypatch):
    owner = "o"
    page = db.create_page(_ensure_owner(owner), "P")
    src = db.insert_module(
        owner,
        ModuleConfig(title="Src", components=[{"id": "n", "type": "note", "label": "N"}]),
        page_id=page.id,
    )
    tgt = db.insert_module(
        owner,
        ModuleConfig(
            title="Digest", components=[{"id": "d", "type": "note", "label": "D"}], state={"d": ""}
        ),
        page_id=page.id,
    )
    monkeypatch.setattr("src.services.actions.llm.generate", fake_generate("Two tools present."))
    res = actions.ACTION_SPECS["summarize"].execute(
        owner,
        {"type": "summarize", "module_id": tgt.id, "component_id": "d", "source_module_ids": []},
        _ctx(page_id=page.id),
    )
    assert res.result["n"] == 2  # both modules on the page summarized
    assert db.get_module(owner, tgt.id).config.state["d"] == "Two tools present."
    assert src.id  # referenced


def _capturing_generate(store):
    """An llm.generate replacement that records the composed prompt (+ system) and
    sets llm.last_call, so a test can assert what _exec_summarize actually sends
    to the model. Accepts the keyword-only expect_text param the path threads."""

    def _gen(prompt, system=None, **kwargs):
        store["prompt"] = prompt
        store["system"] = system
        res = llm.GenResult(text="A tidy digest.", provider="test", model="test")
        llm.last_call.set(res)
        return res

    return _gen


def test_summarize_prompt_includes_profile_facts(monkeypatch):
    # PROF-1 (DESIGN-runtime §8): a seeded profile fact must reach the summarize
    # prompt via orchestrator._profile_block, so a digest is shaped by what Trus
    # has learned about the owner.
    owner = "o"
    m = _mk_module(owner, [{"id": "note", "type": "note", "label": "Digest"}], {"note": ""})
    db.profile_add(owner, "preference", "Prefers metric units", source="manual")
    store: dict = {}
    monkeypatch.setattr("src.services.actions.llm.generate", _capturing_generate(store))
    actions.ACTION_SPECS["summarize"].execute(
        owner,
        {
            "type": "summarize",
            "module_id": m.id,
            "component_id": "note",
            "source_module_ids": [m.id],
        },
        _ctx(),
    )
    assert "What I know about you:" in store["prompt"]
    assert "Prefers metric units" in store["prompt"]


def test_summarize_prompt_omits_profile_block_when_empty(monkeypatch):
    # No profile facts → no "What I know about you:" block at all (the empty-facts
    # branch of _profile_block returns "").
    owner = "o"
    m = _mk_module(owner, [{"id": "note", "type": "note", "label": "Digest"}], {"note": ""})
    store: dict = {}
    monkeypatch.setattr("src.services.actions.llm.generate", _capturing_generate(store))
    actions.ACTION_SPECS["summarize"].execute(
        owner,
        {
            "type": "summarize",
            "module_id": m.id,
            "component_id": "note",
            "source_module_ids": [m.id],
        },
        _ctx(),
    )
    assert "What I know about you:" not in store["prompt"]


def test_safe_reason_class_name_for_plain_exception():
    assert actions.safe_reason(ValueError("x")) == "ValueError"


def test_draft_lands_feed_entry_with_draft_badge(monkeypatch):
    owner = "o"
    m = _mk_module(owner, [{"id": "out", "type": "list", "label": "Outbox"}], {"out": []})
    monkeypatch.setattr("src.services.actions.llm.generate", fake_generate("Dear Sam, thanks!"))
    actions.ACTION_SPECS["draft"].execute(
        owner,
        {
            "type": "draft",
            "module_id": m.id,
            "component_id": "out",
            "recipient": "Sam",
            "instruction": "thank you note",
        },
        _ctx(),
    )
    entry = db.get_module(owner, m.id).config.state["out"][0]
    assert entry["badge"] == "draft"
    assert entry["body"] == "Dear Sam, thanks!"


def test_learn_mines_dedups_and_caps(monkeypatch):
    owner = _ensure_owner("o")
    db.add_message(owner, "user", "I run every morning at 6", page_id="p")
    monkeypatch.setattr(
        "src.services.actions.llm.generate",
        fake_generate('["Runs mornings", "Runs mornings", "Prefers tea", "Extra fact"]'),
    )
    res = actions.ACTION_SPECS["learn"].execute(
        owner, {"type": "learn", "lookback_days": 7, "max_facts": 3}, _ctx()
    )
    # max_facts caps the slice to 3, then dedup collapses the pair → 2 distinct
    assert res.result["n"] == 2
    texts = {f["text"] for f in db.profile_list(owner)}
    assert texts == {"Runs mornings", "Prefers tea"}
    assert all(f["source"] == "activity" for f in db.profile_list(owner))


def test_learn_no_messages_is_noop():
    res = actions.ACTION_SPECS["learn"].execute(
        "empty", {"type": "learn", "lookback_days": 7, "max_facts": 3}, _ctx()
    )
    assert res.result["n"] == 0


# ── archive_module (dial-2 unlock) + delete_data (irreversible) ──────────────


def test_archive_module_sets_archived():
    owner = "o"
    m = _mk_module(owner, [{"id": "c", "type": "note", "label": "N"}], {})
    res = actions.ACTION_SPECS["archive_module"].execute(
        owner, {"type": "archive_module", "module_id": m.id}, _ctx()
    )
    assert res.result["module_title"] == "M"
    assert db.get_module(owner, m.id).archived is True


def test_delete_data_really_deletes_module():
    owner = "o"
    m = _mk_module(owner, [{"id": "c", "type": "note", "label": "N"}], {})
    actions.ACTION_SPECS["delete_data"].execute(
        owner, {"type": "delete_data", "target": "module", "target_id": m.id}, _ctx()
    )
    assert db.get_module(owner, m.id) is None


def test_delete_data_missing_raises():
    with pytest.raises(ValueError, match="not found"):
        actions.ACTION_SPECS["delete_data"].execute(
            "o", {"type": "delete_data", "target": "module", "target_id": "gone"}, _ctx()
        )


# ── SEAM stubs mark results simulated (never claim real success) ─────────────


@pytest.mark.parametrize(
    "action_type,payload",
    [
        ("send_email", {"to": "a@b.co", "subject": "hi"}),
        ("message_human", {"to": "Sam", "text": "yo"}),
        ("pay", {"payee": "P", "amount_usd": 5}),
    ],
)
def test_seam_stubs_are_simulated(action_type, payload):
    res = actions.ACTION_SPECS[action_type].execute("o", payload, _ctx())
    assert res.result["simulated"] is True
