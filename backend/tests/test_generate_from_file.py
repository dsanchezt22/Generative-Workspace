"""POST /api/modules/generate_from_file.

R-211: a file upload must be grounded in the document's actual content on EVERY
provider. When the active provider can't read a file natively (stub; openai-
compat for non-image mimes), server-side text extraction (src.services.extract)
grounds generation instead. Only when extraction ALSO can't read the file
(unsupported mime, e.g. .bin) does the route refuse honestly (422) instead of
silently degrading to a generic keyword template while claiming success.
"""

import json

import pytest
from fastapi.testclient import TestClient
from src import llm
from src.main import app
from src.services import orchestrator

from tests.conftest import fake_generate


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_generate_from_file_stub_mode_unextractable_file_refuses_honestly(client):
    """R-211: text/csv/md/pdf files now GROUND (via server-side extraction) even
    in stub mode — see test_generate_from_file_stub_provider_txt_grounds_via_extraction
    below. A genuinely unreadable file (unsupported mime, nothing to extract) still
    refuses honestly (422): nothing persisted, no 'Created …' turn logged as a fake
    success."""
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("data.bin", b"some binary content", "application/octet-stream")},
        data={"prompt": "track my workouts"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "refusal" in detail
    assert "current model configuration" in detail["refusal"]
    # Nothing was written to the canvas …
    assert client.get("/api/modules").json() == []
    # … and no fake "Created …" assistant turn was logged.
    convo = client.get("/api/conversations").json()
    assert not any(m["text"].startswith("Created ") for m in convo if m["role"] == "assistant")


def test_generate_from_file_stub_provider_txt_without_live_model_refuses(client):
    """FIX 1 (R-211): in stub mode an extractable .txt DOES reach the text model —
    but llm.generate returns generic keyword templates with provider='stub', which
    is NOT a real read of the document. The grounded path must refuse honestly (422)
    instead of 200-ing as a fake success. Nothing persisted, no 'Created …' turn."""
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("notes.txt", b"Budget line: rent $1200", "text/plain")},
        data={"prompt": "track my rent"},
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "refusal" in detail
    assert "current model configuration" in detail["refusal"]
    assert client.get("/api/modules").json() == []
    convo = client.get("/api/conversations").json()
    assert not any(m["text"].startswith("Created ") for m in convo if m["role"] == "assistant")


def test_generate_from_file_grounded_surfaces_cascade_degraded(client, monkeypatch):
    """FIX 2 (R-403): when the grounded generation's model call cascade-degraded,
    the response must surface degraded=true — mirroring the /generate handler —
    not silently hide it."""
    monkeypatch.setattr(
        llm,
        "generate",
        fake_generate(
            json.dumps(
                [
                    {
                        "title": "Grounded",
                        "components": [{"id": "a", "type": "text_input", "label": "A"}],
                    }
                ]
            ),
            degraded=True,
        ),
    )
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("notes.txt", b"Some grounded content", "text/plain")},
        data={"prompt": "make a tool"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["degraded"] is True


def test_generate_from_file_stub_provider_txt_grounds_via_extraction(client, monkeypatch):
    """R-211: the stub provider has no native way to read ANY file — but an
    extractable file (.txt here) now grounds via server-side text extraction
    instead of refusing. Assert the extracted document content reaches the
    actual prompt sent to the model (not just the filename)."""
    captured: dict = {}
    inner = fake_generate(
        json.dumps(
            [{"title": "Grounded", "components": [{"id": "a", "type": "text_input", "label": "A"}]}]
        )
    )

    def spy(*args, **kwargs):
        captured["args"] = args
        return inner(*args, **kwargs)

    monkeypatch.setattr(llm, "generate", spy)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("notes.txt", b"Budget line: rent $1200", "text/plain")},
        data={"prompt": "track my rent"},
    )
    assert resp.status_code == 200, resp.text
    prompt = captured["args"][0]
    assert "Budget line: rent $1200" in prompt
    assert "DOCUMENT CONTENT" in prompt


def test_generate_from_file_openai_provider_csv_grounds_via_extraction(client, monkeypatch):
    """R-211: the openai-compat provider only takes image/* natively — a .csv
    upload must still ground via text extraction rather than refuse."""
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("TRUS_LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("TRUS_LLM_MODEL", "test-model")

    captured: dict = {}
    inner = fake_generate(
        json.dumps(
            [
                {
                    "title": "Grounded CSV",
                    "components": [{"id": "a", "type": "text_input", "label": "A"}],
                }
            ]
        )
    )

    def spy(*args, **kwargs):
        captured["args"] = args
        return inner(*args, **kwargs)

    monkeypatch.setattr(llm, "generate", spy)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("expenses.csv", b"Item,USD\nCoffee,4", "text/csv")},
        data={"prompt": "turn this into a tracker"},
    )
    assert resp.status_code == 200, resp.text
    prompt = captured["args"][0]
    assert "Item,USD" in prompt
    assert "Coffee,4" in prompt


def test_generate_from_file_grounded_path_does_not_enter_semantic_cache(client, monkeypatch):
    """R-903/R-1004: document content is per-upload and often sensitive — the
    grounded (extraction) path must call _generate_validated directly and never
    look up/store the shared semantic cache (gen_cache)."""
    from src import db

    before = db.cache_stats()["entries"]

    monkeypatch.setattr(
        llm,
        "generate",
        fake_generate(
            json.dumps(
                [
                    {
                        "title": "Grounded",
                        "components": [{"id": "a", "type": "text_input", "label": "A"}],
                    }
                ]
            )
        ),
    )
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("notes.txt", b"Some grounded document content here", "text/plain")},
        data={"prompt": "make a tool"},
    )
    assert resp.status_code == 200, resp.text
    after = db.cache_stats()["entries"]
    assert after == before


def test_generate_from_file_defaults_prompt_to_filename(client, monkeypatch):
    """A blank prompt defaults the instruction to the filename — and that filename
    must actually reach the generation prompt (not just be echoed back)."""
    captured: dict = {}

    def fake_generate_from_file(user_message, system, data, mime):
        captured["user_message"] = user_message
        return json.dumps(
            [{"title": "Meals", "components": [{"id": "cal", "type": "kpi", "label": "Calories"}]}]
        )

    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate_from_file", fake_generate_from_file)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("meals.png", b"\x89PNG\r\n", "image/png")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["module"] is not None
    # The filename reached the actual generation prompt sent to the model.
    assert "meals.png" in captured["user_message"]


def test_generate_from_file_rejects_empty_file(client):
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("empty.txt", b"", "text/plain")},
    )
    assert resp.status_code == 422


def test_generate_from_file_rejects_oversized_file(client):
    oversized = b"x" * (15 * 1024 * 1024 + 1)
    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("big.bin", oversized, "application/octet-stream")},
    )
    assert resp.status_code == 413


def test_generate_from_file_read_cap_preserves_full_content(client, monkeypatch):
    """F3: the route's read-cap (15MB+1) must not truncate a normal upload.
    Proven on the grounded (extraction) path: the ENTIRE file content — start,
    middle rows, and end sentinel — must reach the generation prompt verbatim.
    (Content is kept under extract.py's 20k-char cap so any missing byte can
    only mean the route-level read truncated it.)"""
    body = (
        "START-SENTINEL\n"
        + "\n".join(f"row {i:03d}: value-{i}" for i in range(200))
        + "\nEND-SENTINEL"
    )
    assert len(body) < 20_000  # guard: stay under the extraction cap

    captured: dict = {}
    inner = fake_generate(
        json.dumps(
            [{"title": "OK", "components": [{"id": "a", "type": "text_input", "label": "A"}]}]
        )
    )

    def spy(*args, **kwargs):
        captured["args"] = args
        return inner(*args, **kwargs)

    monkeypatch.setattr(llm, "generate", spy)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("small.txt", body.encode("utf-8"), "text/plain")},
        data={"prompt": "make a tool"},
    )
    assert resp.status_code == 200, resp.text
    assert body in captured["args"][0]  # full content, not a truncated prefix


def test_generate_from_file_non_stub_empty_sentinel_refuses(client, monkeypatch):
    """When the model config can't read the file it returns the '{}' sentinel →
    honest 422 refusal, nothing persisted."""
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate_from_file", lambda *a, **k: "{}")

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("report.pdf", b"%PDF-1.4 ...", "application/pdf")},
        data={"prompt": "build tools from this"},
    )
    assert resp.status_code == 422, resp.text
    assert "refusal" in resp.json()["detail"]
    assert client.get("/api/modules").json() == []


def test_generate_from_file_non_stub_happy_path_persists_and_grounds(client, monkeypatch):
    """A live model that actually reads the file NATIVELY (Gemini — the only
    provider that needs no text-extraction step, see _needs_text_extraction)
    returns modules grounded in it → 200, persisted onto the canvas, and the
    conversation logs the filename."""
    grounded = json.dumps(
        [
            {
                "title": "Q3 Expenses",
                "components": [
                    {
                        "id": "rows",
                        "type": "table",
                        "label": "Line items",
                        "columns": ["Item", "USD"],
                    }
                ],
            }
        ]
    )
    # A non-stub-looking GEMINI_API_KEY resolves the provider to "gemini", which
    # reads every mime natively — this exercises the multimodal path below
    # (generate_from_file), not the text-extraction grounding path.
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-stub-key")
    monkeypatch.setattr(llm, "is_stub_mode", lambda: False)
    monkeypatch.setattr(llm, "generate_from_file", lambda *a, **k: grounded)

    resp = client.post(
        "/api/modules/generate_from_file",
        files={"file": ("expenses.csv", b"Item,USD\nCoffee,4", "text/csv")},
        data={"prompt": "turn this into a tracker"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["module"]["config"]["title"] == "Q3 Expenses"
    # Persisted, not just returned.
    assert len(client.get("/api/modules").json()) == 1
    convo = client.get("/api/conversations").json()
    assert any("expenses.csv" in m["text"] for m in convo if m["role"] == "user")


def test_generate_from_file_grounded_path_excludes_recent_conversation(client, monkeypatch):
    """R-302: conversation context feeds the generate/preview paths only — the
    grounded (file) path must never receive it (document content already
    dominates there). Seed a distinctive prior turn via a normal generate call,
    then confirm the grounded file-path prompt has no trace of it. The file
    route gets an EXPLICIT page_id (the page the seeded turn landed on), so
    this can't pass trivially via the no-page-no-context rule (review 2b-4) —
    only via the file path genuinely never fetching conversation context."""
    client.post(
        "/api/modules/generate", json={"prompt": "a distinctive prior request about llamas"}
    )
    pid = client.get("/api/pages").json()[0]["id"]

    captured: dict = {}
    inner = fake_generate(
        json.dumps(
            [{"title": "Grounded", "components": [{"id": "a", "type": "text_input", "label": "A"}]}]
        )
    )

    def spy(*args, **kwargs):
        captured["args"] = args
        return inner(*args, **kwargs)

    monkeypatch.setattr(llm, "generate", spy)

    resp = client.post(
        f"/api/modules/generate_from_file?page_id={pid}",
        files={"file": ("notes.txt", b"Some grounded document content here", "text/plain")},
        data={"prompt": "make a tool"},
    )
    assert resp.status_code == 200, resp.text
    prompt = captured["args"][0]
    assert "Recent conversation:" not in prompt
    assert "llamas" not in prompt


def test_generate_from_file_route_module_is_reachable():
    """Guard: the route module imports the orchestrator symbol it delegates to."""
    assert hasattr(orchestrator, "generate_modules_from_file")
