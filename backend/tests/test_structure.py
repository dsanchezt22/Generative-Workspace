"""Self-composing structure of surfaces (SURF/ONB-1..2), amended by
DESIGN-RECONCILED rulings 2 & 4: proposed automations carry `action_type` (no
`tier`), confirm creates REAL enabled automations (trust_dial=1) through the
shared creation path, and unresolvable ones are dropped + reported (pages/modules
always intact). Parse tests drive the pure orchestrator helpers; route tests use
TestClient (stub mode by default via conftest).
"""

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from src import db, llm
from src.main import app
from src.schema import Feed, ModuleConfig, StructurePage, StructureProposal
from src.services import orchestrator

from tests.conftest import gen_result as _gr

STRUCTURE_DICT = {
    "plan": "A two-surface system.",
    "pages": [
        {
            "name": "Ops",
            "icon": "briefcase",
            "accent": "sky",
            "purpose": "ops",
            "modules": [
                {
                    "title": "Brief",
                    "components": [{"id": "brief", "type": "feed", "label": "Brief"}],
                },
                {
                    "title": "Tasks",
                    "components": [{"id": "tasks", "type": "checklist", "label": "Tasks"}],
                },
            ],
        },
        {
            "name": "Clients",
            "modules": [
                {
                    "title": "Clients",
                    "components": [
                        {"id": "clients", "type": "table", "label": "Clients", "columns": ["Name"]}
                    ],
                }
            ],
        },
    ],
    "automations": [
        {
            "name": "Digest",
            "description": "daily digest into the brief",
            "schedule": "daily",
            "action_type": "summarize",
            "page": 0,
            "target_component_id": "brief",
        }
    ],
}
STRUCTURE_JSON = json.dumps(STRUCTURE_DICT)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def other():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def _non_stub():
    from unittest.mock import patch

    with patch("src.services.orchestrator.llm.is_stub_mode", return_value=False):
        yield


def _capture_generate(text, capture):
    def gen(prompt, system=None, **kw):
        capture["msg"] = prompt
        llm.last_call.set(llm.GenResult(text, "test", "test"))
        return llm.GenResult(text, "test", "test")

    return gen


# ── 1. happy path parse ──────────────────────────────────────────────────────


def test_structure_parse_happy_path():
    d = orchestrator._parse_structure(STRUCTURE_DICT)
    assert d.modules == [] and d.structure is not None
    assert [p.name for p in d.structure.pages] == ["Ops", "Clients"]
    assert d.structure.automations[0].action_type == "summarize"
    assert d.structure.pages[0].accent == "sky"


# ── 1b. data_source honesty (SEAM-2): the structure path shares the flat
# path's sanitizer, not a separate/weaker check ────────────────────────────


def test_structure_keeps_valid_data_source():
    d = orchestrator._parse_structure(
        {
            "pages": [
                {
                    "name": "Kitchen",
                    "modules": [
                        {
                            "title": "Groceries",
                            "components": [
                                {
                                    "id": "kpi1",
                                    "type": "kpi",
                                    "label": "Calories",
                                    "data_source": {
                                        "provider": "nutrition",
                                        "query": {"food": "banana"},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    kpi = d.structure.pages[0].modules[0].components[0]
    assert kpi.data_source is not None
    assert kpi.data_source.provider == "nutrition"


def test_structure_strips_out_of_domain_data_source():
    d = orchestrator._parse_structure(
        {
            "pages": [
                {
                    "name": "Portfolio",
                    "modules": [
                        {
                            "title": "Stocks",
                            "components": [
                                {
                                    "id": "kpi1",
                                    "type": "kpi",
                                    "label": "AAPL",
                                    "data_source": {
                                        "provider": "stocks",
                                        "query": {"ticker": "AAPL"},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }
    )
    # The out-of-domain binding costs only itself — the component (and its
    # page/module) survive as ordinary manual entry, exactly the flat path's
    # R-705 contract (test_generate_modules_strips_out_of_domain_data_source).
    kpi = d.structure.pages[0].modules[0].components[0]
    assert kpi.data_source is None
    assert d.structure.pages[0].name == "Portfolio"


# ── 2. size ceiling — clip, never raise ──────────────────────────────────────


def test_size_ceiling_clips_to_4x6():
    big = {
        "pages": [
            {
                "name": f"P{i}",
                "modules": [
                    {"title": f"M{j}", "components": [{"id": "c", "type": "note", "label": "N"}]}
                    for j in range(30)
                ],
            }
            for i in range(40)
        ]
    }
    d = orchestrator._parse_structure(big)
    assert len(d.structure.pages) == 4
    assert all(len(p.modules) == 6 for p in d.structure.pages)


# ── 3. sanitize-not-reject ───────────────────────────────────────────────────


def test_bad_module_drops_empty_page_drops_its_automation_drops():
    data = {
        "pages": [
            {
                "name": "Good",
                "modules": [
                    {"title": "G", "components": [{"id": "brief", "type": "feed", "label": "B"}]},
                    {"title": "Bad", "components": [{"id": "c", "type": "NOPE", "label": "N"}]},
                ],
            },
            {
                "name": "AllBad",
                "modules": [
                    {"title": "X", "components": [{"id": "c", "type": "ALSO_NOPE", "label": "N"}]}
                ],
            },
        ],
        "automations": [
            {"name": "keep", "description": "d", "page": 0, "target_component_id": "brief"},
            {"name": "drop", "description": "d", "page": 1, "target_component_id": "c"},
        ],
    }
    d = orchestrator._parse_structure(data)
    assert len(d.structure.pages) == 1  # AllBad dropped
    assert len(d.structure.pages[0].modules) == 1  # the NOPE module dropped
    assert [a.name for a in d.structure.automations] == ["keep"]  # page-1 automation dropped


# ── 4. action_type validation (fail-closed replacement for tier) ─────────────


def test_missing_action_type_defaults_summarize():
    data = {
        "pages": [
            {
                "name": "P",
                "modules": [
                    {"title": "M", "components": [{"id": "brief", "type": "feed", "label": "B"}]}
                ],
            }
        ],
        "automations": [
            {"name": "a", "description": "d", "page": 0, "target_component_id": "brief"}
        ],
    }
    d = orchestrator._parse_structure(data)
    assert d.structure.automations[0].action_type == "summarize"


def test_garbage_action_type_drops_automation():
    data = {
        "pages": [
            {
                "name": "P",
                "modules": [
                    {"title": "M", "components": [{"id": "brief", "type": "feed", "label": "B"}]}
                ],
            }
        ],
        "automations": [
            {
                "name": "bad",
                "description": "d",
                "page": 0,
                "action_type": "DELETE_EVERYTHING",
                "target_component_id": "brief",
            }
        ],
    }
    d = orchestrator._parse_structure(data)
    assert d.structure.automations == []  # the parser never emits a type the JSON didn't state


# ── 5. page-index remap + unknown target → None ──────────────────────────────


def test_page_index_remap_and_unknown_target_nulled():
    data = {
        "pages": [
            {
                "name": "Empty",
                "modules": [
                    {"title": "X", "components": [{"id": "c", "type": "BAD", "label": "N"}]}
                ],
            },
            {
                "name": "Real",
                "modules": [
                    {"title": "M", "components": [{"id": "brief", "type": "feed", "label": "B"}]}
                ],
            },
        ],
        "automations": [
            {
                "name": "a",
                "description": "d",
                "page": 1,
                "action_type": "summarize",
                "target_component_id": "ghost",
            }
        ],
    }
    d = orchestrator._parse_structure(data)
    assert len(d.structure.pages) == 1  # "Empty" dropped
    auto = d.structure.automations[0]
    assert auto.page == 0  # remapped from original index 1 → surviving 0
    assert auto.target_component_id is None  # "ghost" not on the page → nulled at parse


# ── 6. zero surviving pages → degrade to flat modules ────────────────────────


def test_zero_pages_degrades_to_flat_modules():
    # A page whose name is too long fails StructurePage validation, but its valid
    # modules survive → degrade to flat (structure None).
    data = {
        "pages": [
            {
                "name": "x" * 80,
                "modules": [
                    {"title": "M", "components": [{"id": "c", "type": "note", "label": "N"}]}
                ],
            }
        ]
    }
    d = orchestrator._parse_structure(data)
    assert d.structure is None
    assert len(d.modules) == 1


# ── 7. preview returns structure, persists nothing ───────────────────────────


def test_preview_returns_structure_persists_nothing(client, _non_stub, monkeypatch):
    monkeypatch.setattr(
        "src.services.orchestrator.llm.generate", lambda *a, **k: _gr(STRUCTURE_JSON)
    )
    r = client.post("/api/modules/preview", json={"prompt": "run my whole life"})
    assert r.status_code == 200
    body = r.json()
    assert body["structure"] is not None
    assert body["previews"] is None and body["modules"] is None
    assert client.get("/api/modules").json() == []  # nothing persisted


# ── 8. insert_structure transactionality ─────────────────────────────────────


def _counts(owner):
    with db._conn() as c:
        p = c.execute("SELECT COUNT(*) FROM pages WHERE session_id = ?", (owner,)).fetchone()[0]
        m = c.execute("SELECT COUNT(*) FROM modules WHERE session_id = ?", (owner,)).fetchone()[0]
    return (p, m)


def test_insert_structure_rolls_back_on_mid_insert_failure(monkeypatch):
    owner = db.ensure_session(None)
    real = db._record_version
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full mid-insert")
        return real(*a, **k)

    monkeypatch.setattr(db, "_record_version", boom)
    prop = StructureProposal(
        pages=[
            StructurePage(
                name="P",
                modules=[
                    ModuleConfig(title="A", components=[{"id": "a", "type": "note", "label": "A"}]),
                    ModuleConfig(title="B", components=[{"id": "b", "type": "note", "label": "B"}]),
                ],
            )
        ]
    )
    before = _counts(owner)
    with pytest.raises(RuntimeError):
        db.insert_structure(owner, prop, None)
    assert _counts(owner) == before  # zero pages/modules persisted


# ── 9. cross-owner isolation via overview ────────────────────────────────────


def test_overview_cross_owner_isolation(client, other):
    resp = client.post("/api/structure", json={"structure": STRUCTURE_DICT}).json()
    a_page_ids = {p["id"] for p in resp["pages"]}
    b_overview = other.get("/api/pages/overview").json()
    assert a_page_ids.isdisjoint(set(b_overview.keys()))


# ── 10. cache — structure never stored; a flat hit still serves ──────────────


def test_structure_never_cached(client, _non_stub, monkeypatch):
    owner = db.ensure_session(None)
    monkeypatch.setattr(
        "src.services.orchestrator.llm.generate", lambda *a, **k: _gr(STRUCTURE_JSON)
    )
    orchestrator.generate_modules("run my whole life", owner=owner)
    assert orchestrator.last_structure.get() is not None
    assert db.cache_rows("system", owner=owner) == []  # nothing stored under the prompt


def test_flat_cache_hit_still_serves(_non_stub, monkeypatch):
    from src import semantic_cache

    owner = db.ensure_session(None)
    flat = [{"title": "Cached", "components": [{"id": "c", "type": "note", "label": "N"}]}]
    semantic_cache.store("system", "run my whole life", flat, owner=owner)
    spy = {"called": False}

    def gen(*a, **k):
        spy["called"] = True
        return _gr(STRUCTURE_JSON)

    monkeypatch.setattr("src.services.orchestrator.llm.generate", gen)
    result = orchestrator.generate_modules("run my whole life", owner=owner)
    assert [m.title for m in result] == ["Cached"]  # flat hit served
    assert spy["called"] is False  # model never ran
    assert orchestrator.last_structure.get() is None


# ── 11. budget — preview gated, confirm free ─────────────────────────────────


def test_preview_budget_gated_confirm_is_free(client, monkeypatch):
    monkeypatch.setenv("TRUS_GEN_RATE_MAX", "0")  # exhaust the generation budget
    assert client.post("/api/modules/preview", json={"prompt": "x"}).status_code == 429
    # confirm makes zero LLM calls → no budget gate
    r = client.post("/api/structure", json={"structure": STRUCTURE_DICT})
    assert r.status_code == 200
    assert len(r.json()["pages"]) == 2


# ── 12. Feed validation bounds ───────────────────────────────────────────────


def test_feed_max_items_bounds():
    assert Feed(id="f", label="F", max_items=50).max_items == 50
    with pytest.raises(ValidationError):
        Feed(id="f", label="F", max_items=0)
    with pytest.raises(ValidationError):
        Feed(id="f", label="F", max_items=101)


# ── 13. file path degrades structure to flat ─────────────────────────────────


def test_flatten_degrades_structure():
    parsed = orchestrator._parse_structure(STRUCTURE_DICT)
    flat = orchestrator._flatten(parsed)
    assert all(isinstance(m, ModuleConfig) for m in flat)
    assert {m.title for m in flat} == {"Brief", "Tasks", "Clients"}


def test_generate_from_file_never_yields_structure(monkeypatch):
    monkeypatch.setattr(
        "src.services.orchestrator.llm.provider_info", lambda: {"provider": "gemini"}
    )
    monkeypatch.setattr(
        "src.services.orchestrator.llm.generate_from_file",
        lambda *a, **k: (
            llm.last_call.set(llm.GenResult(STRUCTURE_JSON, "gemini", "g")),
            STRUCTURE_JSON,
        )[1],
    )
    mods = orchestrator.generate_modules_from_file("build from this", b"x", "application/pdf")
    assert {m.title for m in mods} == {"Brief", "Tasks", "Clients"}  # flat, not pages


# ── 14. restart — confirmed structure fully present ──────────────────────────


def test_confirmed_structure_persists(client):
    client.post("/api/structure", json={"structure": STRUCTURE_DICT})
    # a fresh set of reads (the DB file persists) shows the whole structure
    pages = client.get("/api/pages").json()
    assert {"Ops", "Clients"}.issubset({p["name"] for p in pages})
    assert len(client.get("/api/modules").json()) == 3
    assert len(client.get("/api/automations").json()["automations"]) == 1


# ── 15. stub pick_structure drives the full ONB-1 A-flow offline ─────────────


def test_stub_structure_a_flow(client):
    r = client.post("/api/modules/preview", json={"prompt": "run my freelance business"})
    assert r.status_code == 200
    structure = r.json()["structure"]
    assert structure is not None
    confirm = client.post("/api/structure", json={"structure": structure}).json()
    assert len(confirm["pages"]) == 2
    autos = client.get("/api/automations").json()["automations"]
    assert autos[0]["action_type"] == "summarize" and autos[0]["enabled"] is True


# ── 16. confirm creates REAL enabled automations with correct composition ────


def test_confirm_composes_real_summarize_automation(client):
    client.post("/api/structure", json={"structure": STRUCTURE_DICT})
    autos = client.get("/api/automations").json()["automations"]
    assert len(autos) == 1
    a = autos[0]
    assert a["enabled"] is True and a["trust_dial"] == 1
    assert a["action"]["type"] == "summarize"
    assert a["action"]["component_id"] == "brief"
    # source_module_ids = the page's OTHER created module (the checklist)
    assert len(a["action"]["source_module_ids"]) == 1


# ── 17. unresolvable automation → dropped + reported, pages/modules intact ────


def test_unresolvable_automation_dropped_pages_intact(client):
    struct = json.loads(STRUCTURE_JSON)
    struct["automations"].append(
        {
            "name": "orphan",
            "description": "d",
            "schedule": "daily",
            "action_type": "summarize",
            "page": 0,
            "target_component_id": "does-not-exist",
        }
    )
    resp = client.post("/api/structure", json={"structure": struct}).json()
    assert resp["dropped"] == ["orphan"]
    assert len(resp["automation_ids"]) == 1  # the good one landed
    assert len(resp["pages"]) == 2 and len(resp["modules"]) == 3  # intact


def test_track_without_source_dropped(client):
    struct = json.loads(STRUCTURE_JSON)
    struct["automations"] = [
        {
            "name": "tracker",
            "description": "d",
            "schedule": "daily",
            "action_type": "track",
            "page": 0,
            "target_component_id": "brief",
        }  # no source_component_id → unresolvable
    ]
    resp = client.post("/api/structure", json={"structure": struct}).json()
    assert resp["dropped"] == ["tracker"] and resp["automation_ids"] == []


# ── 18. schedule mapping ─────────────────────────────────────────────────────


def test_schedule_mapping(client):
    struct = json.loads(STRUCTURE_JSON)
    struct["automations"] = [
        {
            "name": "hourly",
            "description": "d",
            "schedule": "hourly",
            "action_type": "summarize",
            "page": 0,
            "target_component_id": "brief",
        },
        {
            "name": "daily",
            "description": "d",
            "schedule": "daily",
            "action_type": "remind",
            "page": 0,
            "target_component_id": "tasks",
        },
        {
            "name": "weekly",
            "description": "d",
            "schedule": "weekly",
            "action_type": "draft",
            "page": 0,
            "target_component_id": "brief",
        },
    ]
    client.post("/api/structure", json={"structure": struct})
    autos = {a["name"]: a for a in client.get("/api/automations").json()["automations"]}
    assert (
        autos["hourly"]["schedule_kind"] == "interval" and autos["hourly"]["interval_secs"] == 3600
    )
    assert autos["daily"]["schedule_kind"] == "daily" and autos["daily"]["daily_at"] == "07:00"
    assert (
        autos["weekly"]["schedule_kind"] == "interval"
        and autos["weekly"]["interval_secs"] == 604800
    )


# ── 19. page_overview real counts + last_run_at from the automations table ───


def test_overview_real_counts_and_last_run(client):
    resp = client.post("/api/structure", json={"structure": STRUCTURE_DICT}).json()
    ops_id = next(p["id"] for p in resp["pages"] if p["name"] == "Ops")
    aid = resp["automation_ids"][0]

    ov = client.get("/api/pages/overview").json()
    assert ov[ops_id]["modules"] == 2
    assert ov[ops_id]["automations"] == 1
    assert ov[ops_id]["last_run_at"] is None  # never run yet

    client.post(f"/api/automations/{aid}/run")  # a real run stamps last_run_at
    ov2 = client.get("/api/pages/overview").json()
    assert ov2[ops_id]["last_run_at"] is not None


# ── 20. ONB-4 — profile facts reach the composed structure message ───────────


def test_profile_reaches_structure_prompt(_non_stub, monkeypatch):
    owner = db.ensure_session(None)
    db.profile_add(owner, "goal", "Grow my consulting practice", source="manual")
    capture: dict = {}
    monkeypatch.setattr(
        "src.services.orchestrator.llm.generate", _capture_generate(STRUCTURE_JSON, capture)
    )
    orchestrator.generate_modules("run my whole business", owner=owner)
    assert orchestrator.last_structure.get() is not None
    assert "Grow my consulting practice" in capture["msg"]  # profile shaped the prompt
    assert db.cache_rows("system", owner=owner) == []  # key stays raw prompt; structure not stored
