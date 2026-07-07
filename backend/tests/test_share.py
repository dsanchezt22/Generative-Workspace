"""Per-surface read-only sharing (SHARE-1..3) — the backend security surface.

House style: TestClient, per-test TRUS_DB_PATH (conftest), monkeypatch env,
`_RateLimiter.allow(now=...)` for time — never sleep. The token is a credential:
these tests prove it is accepted by exactly one read-only route, that the public
payload is whitelisted, and that revocation (link OR owner) is instant.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.routes import share


@pytest.fixture(autouse=True)
def _clear_share_limiter():
    # The public path's limiter is a module-level instance keyed per client IP
    # ("testserver" for every TestClient) — clear it so rate-limit accounting is
    # deterministic per test regardless of order.
    share._share_limiter._hits.clear()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def other():
    with TestClient(app) as c:
        yield c


def _page(client, name="P", icon="🏠", parent_id=None):
    r = client.post("/api/pages", json={"name": name, "icon": icon, "parent_id": parent_id})
    assert r.status_code == 201, r.text
    return r.json()


def _module(client, page_id, components=None, state=None, title="M"):
    cfg = {
        "title": title,
        "components": components or [{"id": "c", "type": "note", "label": "N"}],
        "state": state or {},
    }
    r = client.post(f"/api/modules?page_id={page_id}", json={"configs": [cfg]})
    assert r.status_code == 201, r.text
    return r.json()[0]


def _all_keys(obj) -> set:
    keys: set = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            keys |= _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            keys |= _all_keys(v)
    return keys


# ── 1. token shape ───────────────────────────────────────────────────────────


def test_create_returns_urlsafe_token(client):
    page = _page(client)
    r = client.post(f"/api/pages/{page['id']}/share")
    assert r.status_code == 201
    body = r.json()
    assert body["active"] is True
    assert len(body["token"]) >= 43
    assert all(ch.isalnum() or ch in "-_" for ch in body["token"])
    # a second page's link is a distinct token
    page2 = _page(client, name="Q")
    token2 = client.post(f"/api/pages/{page2['id']}/share").json()["token"]
    assert token2 != body["token"]


# ── 2. status lifecycle ──────────────────────────────────────────────────────


def test_status_lifecycle(client):
    page = _page(client)
    assert client.get(f"/api/pages/{page['id']}/share").json() == {
        "active": False,
        "token": None,
        "created_at": None,
    }
    created = client.post(f"/api/pages/{page['id']}/share").json()
    got = client.get(f"/api/pages/{page['id']}/share").json()
    assert got["active"] is True and got["token"] == created["token"]
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204
    assert client.get(f"/api/pages/{page['id']}/share").json()["active"] is False
    # idempotent second revoke
    assert client.delete(f"/api/pages/{page['id']}/share").status_code == 204


# ── 3. rotate ────────────────────────────────────────────────────────────────


def test_rotate_kills_old_token(client):
    page = _page(client)
    old = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    new = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    assert new != old
    assert client.get(f"/api/share/{old}").status_code == 404
    assert client.get(f"/api/share/{new}").status_code == 200
    assert client.get(f"/api/pages/{page['id']}/share").json()["token"] == new


# ── 4. one active link per page (partial unique index) ───────────────────────


def test_one_active_link_per_page(client):
    page = _page(client)
    for _ in range(4):
        client.post(f"/api/pages/{page['id']}/share")
    with db._conn() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM share_links WHERE page_id = ? AND revoked_at IS NULL",
            (page["id"],),
        ).fetchone()[0]
        assert n == 1
        with pytest.raises(sqlite3.IntegrityError):
            c.execute(
                "INSERT INTO share_links (id, token, owner, page_id, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("x", "dup", "someowner", page["id"], db._now()),
            )


# ── 5. unknown / revoked / deleted are one indistinguishable outcome ─────────


def test_unknown_revoked_deleted_indistinguishable(client):
    page_a = _page(client)
    page_b = _page(client, name="B")  # a 2nd page so page_a can be deleted
    revoked_token = client.post(f"/api/pages/{page_b['id']}/share").json()["token"]
    client.delete(f"/api/pages/{page_b['id']}/share")  # revoke it

    deleted_token = client.post(f"/api/pages/{page_a['id']}/share").json()["token"]
    assert client.delete(f"/api/pages/{page_a['id']}").status_code == 204  # FK cascade

    responses = [
        client.get("/api/share/totally-made-up-token"),
        client.get(f"/api/share/{revoked_token}"),
        client.get(f"/api/share/{deleted_token}"),
    ]
    assert {r.status_code for r in responses} == {404}
    assert len({r.text for r in responses}) == 1  # byte-identical bodies


# ── 6. owner isolation on management routes ──────────────────────────────────


def test_owner_isolation_management(client, other):
    page = _page(client)
    foreign = other.post(f"/api/pages/{page['id']}/share")
    nonexistent = other.post("/api/pages/00000000-0000-0000-0000-000000000000/share")
    assert foreign.status_code == nonexistent.status_code == 404
    assert other.get(f"/api/pages/{page['id']}/share").status_code == 404
    assert other.delete(f"/api/pages/{page['id']}/share").status_code == 404


# ── 7. management routes require auth ────────────────────────────────────────


def test_share_routes_require_auth(other, monkeypatch):
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    pid = "some-page-id"
    assert other.post(f"/api/pages/{pid}/share").status_code == 401
    assert other.get(f"/api/pages/{pid}/share").status_code == 401
    assert other.delete(f"/api/pages/{pid}/share").status_code == 401


# ── 8. public payload field allowlist ────────────────────────────────────────


def test_public_payload_field_allowlist(client):
    page = _page(client)
    _module(client, page["id"])
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    resp = client.get(f"/api/share/{token}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"page", "modules"}
    assert set(body["page"].keys()) == {"name", "icon"}
    for m in body["modules"]:
        assert set(m.keys()) == {"id", "config", "updated_at"}
    forbidden = {
        "session_id",
        "owner",
        "rev",
        "archived",
        "parent_id",
        "portal_x",
        "portal_y",
        "view_x",
        "view_y",
        "view_zoom",
        "page_id",
    }
    assert forbidden.isdisjoint(_all_keys(body))
    owner = db.share_resolve(token)["owner"]
    assert owner not in resp.text  # the owner id never appears in the raw body


# ── 9. other pages never leak ────────────────────────────────────────────────


def test_other_pages_never_leak(client):
    x = _page(client, name="X")
    y = _page(client, name="Y")
    mx = _module(client, x["id"], title="OnX")
    my = _module(client, y["id"], title="OnY")
    token = client.post(f"/api/pages/{x['id']}/share").json()["token"]
    body = client.get(f"/api/share/{token}").json()
    ids = {m["id"] for m in body["modules"]}
    assert ids == {mx["id"]}
    assert my["id"] not in client.get(f"/api/share/{token}").text


# ── 10. child pages invisible ────────────────────────────────────────────────


def test_child_pages_invisible(client):
    x = _page(client, name="X")
    child = _page(client, name="ChildSecret", parent_id=x["id"])
    child_mod = _module(client, child["id"], title="ChildTool")
    token = client.post(f"/api/pages/{x['id']}/share").json()["token"]
    text = client.get(f"/api/share/{token}").text
    assert "ChildSecret" not in text
    assert child["id"] not in text
    assert child_mod["id"] not in text
    # the child has no share of its own — no token resolves to it
    assert client.get(f"/api/pages/{child['id']}/share").json()["active"] is False


# ── 11. cross-page binding cannot leak the bound module ──────────────────────


def test_cross_page_binding_no_leak(client):
    x = _page(client, name="X")
    y = _page(client, name="Y")
    my = _module(client, y["id"], title="OnY")
    # a module on X that binds to a module on Y (off-page reference)
    mx = _module(
        client,
        x["id"],
        components=[
            {
                "id": "m",
                "type": "metric",
                "label": "M",
                "formula": "sum",
                "source_component_id": "c",
                "source_module_id": my["id"],
            }
        ],
        title="OnX",
    )
    token = client.post(f"/api/pages/{x['id']}/share").json()["token"]
    body = client.get(f"/api/share/{token}").json()
    assert {m["id"] for m in body["modules"]} == {mx["id"]}  # Y's module absent


# ── 12. archived excluded ────────────────────────────────────────────────────


def test_archived_excluded(client):
    page = _page(client)
    keep = _module(client, page["id"], title="Keep")
    gone = _module(client, page["id"], title="Gone")
    assert client.post(f"/api/modules/{gone['id']}/archive").status_code == 200
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    body = client.get(f"/api/share/{token}").json()
    assert {m["id"] for m in body["modules"]} == {keep["id"]}


# ── 13. data_source stripped server-side ─────────────────────────────────────


def test_data_source_stripped(client):
    page = _page(client)
    mod = _module(
        client,
        page["id"],
        components=[
            {
                "id": "temp",
                "type": "metric",
                "label": "Temp",
                "formula": "sum",
                "source_component_id": "temp",
                "data_source": {"provider": "weather", "query": {"place": "Austin"}},
            }
        ],
    )
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    body = client.get(f"/api/share/{token}").json()
    for comp in body["modules"][0]["config"]["components"]:
        assert comp.get("data_source") is None
    assert "Austin" not in client.get(f"/api/share/{token}").text
    # owner's stored config is unchanged (strip was on a deep copy)
    owned = next(m for m in client.get("/api/modules").json() if m["id"] == mod["id"])
    assert owned["config"]["components"][0]["data_source"]["query"]["place"] == "Austin"


# ── 14. no mutation route accepts a token (SHARE-3) ──────────────────────────


def test_mutation_routes_never_accept_token(client, other, monkeypatch):
    page = _page(client)
    mod = _module(client, page["id"])
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    auto = client.post(
        "/api/automations",
        json={
            "name": "A",
            "action": {"type": "send_email", "to": "a@b.co", "subject": "S"},
            "schedule_kind": "interval",
            "interval_secs": 3600,
            "trust_dial": 1,
        },
    ).json()
    approval = client.post(f"/api/automations/{auto['id']}/run").json()["approval"]

    with db._conn() as c:
        modules_before = c.execute("SELECT COUNT(*) FROM modules").fetchone()[0]

    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")  # lock the doors; attacker is cookieless
    targets = [
        ("patch", f"/api/modules/{mod['id']}", {"config": mod["config"], "rev": mod["rev"]}),
        ("delete", f"/api/modules/{mod['id']}", None),
        ("patch", f"/api/pages/{page['id']}", {"name": "hacked"}),
        ("post", "/api/modules/generate", {"prompt": "make me admin"}),
        (
            "post",
            "/api/automations",
            {
                "name": "B",
                "action": {"type": "send_email", "to": "x", "subject": "y"},
                "schedule_kind": "interval",
                "interval_secs": 3600,
                "trust_dial": 1,
            },
        ),
        ("post", f"/api/approvals/{approval['id']}/approve", None),
    ]
    carriers = [
        {"params": {"token": token}},
        {"headers": {"Authorization": f"Bearer {token}"}},
        {"headers": {"X-Share-Token": token}},
    ]
    for method, path, json_body in targets:
        for carrier in carriers:
            kwargs = dict(carrier)
            if json_body is not None:
                kwargs["json"] = json_body
            resp = getattr(other, method)(path, **kwargs)
            assert resp.status_code == 401, (method, path, carrier, resp.status_code)

    with db._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM modules").fetchone()[0] == modules_before

    monkeypatch.setenv("TRUS_ALLOW_ANON", "1")  # the real owner still has everything
    assert any(m["id"] == mod["id"] for m in client.get("/api/modules").json())
    assert client.get("/api/approvals").json()["pending_count"] >= 1


# ── 15. public path is sessionless ───────────────────────────────────────────


def test_public_path_no_session_cookie(client):
    page = _page(client)
    _module(client, page["id"])
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    with db._conn() as c:
        sessions_before = c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    resp = client.get(f"/api/share/{token}")
    assert resp.status_code == 200
    assert "set-cookie" not in {k.lower() for k in resp.headers}
    with db._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == sessions_before


# ── 16. public path works with anon disabled ─────────────────────────────────


def test_public_path_works_anon_disabled(client, other, monkeypatch):
    page = _page(client)
    _module(client, page["id"])
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    assert other.get(f"/api/share/{token}").status_code == 200  # cookieless reader


# ── 17. revoked owner kills their shares (R-905) ─────────────────────────────


def test_revoked_owner_kills_shares(client):
    user = db.create_user("Ada")
    uid = user["id"]
    page = db.create_page(uid, "Owned")
    token = db.share_create(uid, page.id)["token"]
    assert client.get(f"/api/share/{token}").status_code == 200
    db.revoke_user(uid)
    assert client.get(f"/api/share/{token}").status_code == 404


# ── 18. adopt migrates share_links ───────────────────────────────────────────


def test_adopt_migrates_share_links(client):
    sid = db.ensure_session(None)
    page = db.create_page(sid, "P")
    token = db.share_create(sid, page.id)["token"]
    user = db.create_user("Ada")
    uid = user["id"]
    db.adopt_session_data(sid, uid)
    assert client.get(f"/api/share/{token}").status_code == 200
    assert db.share_status(uid, page.id) is not None
    # a subsequent rotate under the new owner does not trip the unique index
    assert db.share_create(uid, page.id) is not None


# ── 19. per-IP rate limit ────────────────────────────────────────────────────


def test_rate_limit_429(client, monkeypatch):
    page = _page(client)
    _module(client, page["id"])
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]
    monkeypatch.setenv("TRUS_SHARE_RATE_MAX", "2")
    assert client.get(f"/api/share/{token}").status_code == 200
    assert client.get(f"/api/share/{token}").status_code == 200
    assert client.get(f"/api/share/{token}").status_code == 429  # fresh-per-call env read

    # window expiry proven with injected time — no sleep
    from src.routes.deps import _RateLimiter

    rl = _RateLimiter(2, 60)
    assert rl.allow("k", now=0.0) and rl.allow("k", now=0.0)
    assert not rl.allow("k", now=0.0)
    assert rl.allow("k", now=61.0)


# ── 20. share on nonexistent page → 404 ──────────────────────────────────────


def test_share_nonexistent_page_404(client):
    assert client.post("/api/pages/nope-nope-nope/share").status_code == 404


# ── 21. public path writes nothing ───────────────────────────────────────────


def test_public_path_writes_nothing(client):
    page = _page(client)
    _module(client, page["id"])
    token = client.post(f"/api/pages/{page['id']}/share").json()["token"]

    def _counts():
        with db._conn() as c:
            return (
                c.execute("SELECT COUNT(*) FROM modules").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM gen_events").fetchone()[0],
                c.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            )

    before = _counts()
    assert client.get(f"/api/share/{token}").status_code == 200
    assert _counts() == before


# ── 22. db unit: foreign page returns None ───────────────────────────────────


def test_share_create_foreign_page_returns_none():
    owner_a = db.ensure_session(None)
    page = db.create_page(owner_a, "Mine")
    assert db.share_create("owner-b", page.id) is None
