"""Tests for the live-data framework: keyless weather via Open-Meteo (R-701/R-704).

Unit-level `live_data.fetch` tests mirror test_providers.py's urlopen-mocking
style; route tests mirror test_transcribe.py's TestClient + owner-gate/rate-limit
style.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from src import db
from src.main import app
from src.services import live_data


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


class _FakeResp:
    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _forecast_payload(temp=21.5, time_="2026-07-03T12:00"):
    return {
        "current": {"time": time_, "temperature_2m": temp},
        "current_units": {"temperature_2m": "°C"},
    }


def _geocode_payload(lat=52.52, lon=13.405):
    return {"results": [{"latitude": lat, "longitude": lon, "name": "Berlin"}]}


# ---------------------------------------------------------------------------
# live_data.fetch — unit level (weather via mocked urlopen)
# ---------------------------------------------------------------------------


def test_fetch_weather_lat_lon_returns_value_and_as_of(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResp(_forecast_payload())

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)
    result = live_data.fetch("weather", {"lat": 52.52, "lon": 13.405})

    assert result["value"] == 21.5
    assert result["unit"] == "°C"
    assert result["as_of"] == "2026-07-03T12:00"
    assert result["source"] == "Open-Meteo"
    assert result["stale"] is False
    assert result["error"] is None
    assert len(calls) == 1
    assert "latitude=52.52" in calls[0]
    assert "longitude=13.405" in calls[0]


def test_fetch_weather_place_geocodes_then_fetches(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        if "geocoding-api" in req.full_url:
            return _FakeResp(_geocode_payload())
        return _FakeResp(_forecast_payload())

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)
    result = live_data.fetch("weather", {"place": "Berlin"})

    assert result["value"] == 21.5
    assert result["error"] is None
    assert len(calls) == 2
    assert "geocoding-api" in calls[0]
    assert "name=Berlin" in calls[0]
    assert "latitude=52.52" in calls[1]


def test_fetch_weather_place_not_found_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        live_data.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp({"results": []})
    )
    result = live_data.fetch("weather", {"place": "Nowhereville"})

    assert result["value"] is None
    assert result["error"] is not None
    assert result["stale"] is False


def test_fetch_weather_missing_query_returns_error_payload():
    result = live_data.fetch("weather", {})
    assert result["value"] is None
    assert result["error"] is not None


def test_fetch_weather_no_current_temperature_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        live_data.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp({"current": {"time": "t"}}),  # no temperature_2m
    )
    result = live_data.fetch("weather", {"lat": 1.0, "lon": 2.0})

    assert result["value"] is None
    assert result["error"] is not None


class _BadJsonResp:
    def read(self):
        return b"not json"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_weather_non_json_response_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        live_data.urllib.request, "urlopen", lambda req, timeout=None: _BadJsonResp()
    )
    result = live_data.fetch("weather", {"lat": 1.0, "lon": 2.0})

    assert result["value"] is None
    assert result["error"] is not None


def test_fetch_unknown_provider_returns_error_payload():
    result = live_data.fetch("stocks", {})
    assert result["value"] is None
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# live_data.fetch — unit level (nutrition via mocked urlopen)
# ---------------------------------------------------------------------------


def _off_payload(kcal=88.1, name="Banana"):
    return {
        "products": [
            {"product_name": name, "nutriments": {"energy-kcal_100g": kcal}},
        ]
    }


def test_fetch_nutrition_returns_kcal_value_and_source(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResp(_off_payload())

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)
    result = live_data.fetch("nutrition", {"food": "banana"})

    assert result["value"] == 88.1
    assert result["unit"] == "kcal/100g"
    assert result["source"] == "Open Food Facts"
    assert result["stale"] is False
    assert result["error"] is None
    assert result["as_of"] is not None
    assert len(calls) == 1
    assert "search_terms=banana" in calls[0]


def test_fetch_nutrition_url_encodes_food_name_with_space_and_ampersand(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResp(_off_payload(name="Mac & Cheese"))

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)
    result = live_data.fetch("nutrition", {"food": "mac & cheese"})

    assert result["error"] is None
    assert len(calls) == 1
    # the raw '&' / space must not leak into the query string unescaped —
    # urlencode quotes them, so the literal substring never appears.
    assert "mac & cheese" not in calls[0]
    assert "search_terms=mac" in calls[0]
    assert "%26" in calls[0] or "search_terms=mac+%26+cheese" in calls[0]


def test_fetch_nutrition_no_products_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        live_data.urllib.request, "urlopen", lambda req, timeout=None: _FakeResp({"products": []})
    )
    result = live_data.fetch("nutrition", {"food": "zzznonexistentfood"})

    assert result["value"] is None
    assert result["error"] is not None
    assert result["stale"] is False


def test_fetch_nutrition_missing_calorie_field_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        live_data.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(
            {"products": [{"product_name": "Mystery Item", "nutriments": {}}]}
        ),
    )
    result = live_data.fetch("nutrition", {"food": "mystery item"})

    assert result["value"] is None
    assert result["error"] is not None


def test_fetch_nutrition_missing_query_returns_error_payload():
    result = live_data.fetch("nutrition", {})
    assert result["value"] is None
    assert result["error"] is not None


def test_fetch_nutrition_ttl_cache_hit_skips_second_urlopen(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        return _FakeResp(_off_payload())

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)
    q = {"food": "apple"}
    first = live_data.fetch("nutrition", q, refresh_secs=600)
    second = live_data.fetch("nutrition", q, refresh_secs=600)

    assert calls["n"] == 1  # second call served from cache, no second urlopen
    assert second == first


def test_fetch_nutrition_error_returns_stale_with_last_cached_value(monkeypatch):
    q = {"food": "bread"}

    monkeypatch.setattr(
        live_data.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(_off_payload()),
    )
    first = live_data.fetch("nutrition", q, refresh_secs=600)
    assert first["error"] is None

    # Age the cache row past its TTL so the next fetch attempts a real refresh.
    qhash = live_data._query_hash(q)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
    with db._conn() as c:
        c.execute(
            "UPDATE live_cache SET fetched_at = ? WHERE provider = ? AND query_hash = ?",
            (expired, "nutrition", qhash),
        )

    def failing_urlopen(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(live_data.urllib.request, "urlopen", failing_urlopen)
    second = live_data.fetch("nutrition", q, refresh_secs=600)

    assert second["value"] == first["value"]
    assert second["stale"] is True


def test_fetch_nutrition_error_never_cached_returns_error_payload(monkeypatch):
    def failing_urlopen(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(live_data.urllib.request, "urlopen", failing_urlopen)
    result = live_data.fetch("nutrition", {"food": "kiwi"})

    assert result["value"] is None
    assert result["stale"] is False
    assert result["error"] is not None


def test_fetch_nutrition_non_json_response_returns_error_payload(monkeypatch):
    monkeypatch.setattr(
        live_data.urllib.request, "urlopen", lambda req, timeout=None: _BadJsonResp()
    )
    result = live_data.fetch("nutrition", {"food": "kale"})

    assert result["value"] is None
    assert result["error"] is not None


def test_fetch_weather_ttl_cache_hit_skips_second_urlopen(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        return _FakeResp(_forecast_payload())

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)
    q = {"lat": 1.0, "lon": 2.0}
    first = live_data.fetch("weather", q, refresh_secs=600)
    second = live_data.fetch("weather", q, refresh_secs=600)

    assert calls["n"] == 1  # second call served from cache, no second urlopen
    assert second == first


def test_fetch_weather_error_returns_stale_with_last_cached_value(monkeypatch):
    q = {"lat": 1.0, "lon": 2.0}

    monkeypatch.setattr(
        live_data.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResp(_forecast_payload()),
    )
    first = live_data.fetch("weather", q, refresh_secs=600)
    assert first["error"] is None

    # Age the cache row past its TTL so the next fetch attempts a real refresh.
    qhash = live_data._query_hash(q)
    expired = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
    with db._conn() as c:
        c.execute(
            "UPDATE live_cache SET fetched_at = ? WHERE provider = ? AND query_hash = ?",
            (expired, "weather", qhash),
        )

    def failing_urlopen(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(live_data.urllib.request, "urlopen", failing_urlopen)
    second = live_data.fetch("weather", q, refresh_secs=600)

    assert second["value"] == first["value"]
    assert second["stale"] is True


def test_fetch_weather_error_never_cached_returns_error_payload(monkeypatch):
    def failing_urlopen(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(live_data.urllib.request, "urlopen", failing_urlopen)
    result = live_data.fetch("weather", {"lat": 9.0, "lon": 9.0})

    assert result["value"] is None
    assert result["stale"] is False
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# GET /api/live/{provider} — route level
# ---------------------------------------------------------------------------


def _mock_fetch_ok(monkeypatch, value=21.5):
    def fake(provider, query, refresh_secs=600):
        return {
            "value": value,
            "unit": "°C",
            "as_of": "2026-07-03T12:00",
            "source": "Open-Meteo",
            "stale": False,
            "error": None,
        }

    monkeypatch.setattr("src.routes.live.live_data.fetch", fake)


def test_live_route_weather_lat_lon_success(client, monkeypatch):
    _mock_fetch_ok(monkeypatch)
    resp = client.get("/api/live/weather", params={"lat": 52.5, "lon": 13.4})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == 21.5
    assert body["source"] == "Open-Meteo"


def test_live_route_weather_place_success(client, monkeypatch):
    captured = {}

    def fake(provider, query, refresh_secs=600):
        captured["query"] = query
        return {
            "value": 21.5,
            "unit": "°C",
            "as_of": "2026-07-03T12:00",
            "source": "Open-Meteo",
            "stale": False,
            "error": None,
        }

    monkeypatch.setattr("src.routes.live.live_data.fetch", fake)
    resp = client.get("/api/live/weather", params={"place": "Berlin"})
    assert resp.status_code == 200, resp.text
    assert captured["query"] == {"place": "Berlin"}


def test_live_route_disabled_returns_marker(client, monkeypatch):
    monkeypatch.setenv("TRUS_LIVE_DATA", "off")
    resp = client.get("/api/live/weather", params={"lat": 1, "lon": 2})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] is None
    # R-701 hardening: the STRUCTURED flag is the off-mode signal the frontend
    # keys on; the human-readable string stays for back-compat only.
    assert body["disabled"] is True
    assert body["error"] == "Live data is disabled"


def test_live_route_enabled_payload_has_no_disabled_flag(client, monkeypatch):
    _mock_fetch_ok(monkeypatch)
    resp = client.get("/api/live/weather", params={"lat": 52.5, "lon": 13.4})
    assert resp.status_code == 200, resp.text
    assert not resp.json().get("disabled")


def test_live_route_bad_provider_422(client):
    resp = client.get("/api/live/stocks", params={"lat": 1, "lon": 2})
    assert resp.status_code == 422, resp.text


def test_live_route_bad_query_422(client):
    resp = client.get("/api/live/weather")
    assert resp.status_code == 422, resp.text


def test_live_route_nutrition_success(client, monkeypatch):
    captured = {}

    def fake(provider, query, refresh_secs=600):
        captured["provider"] = provider
        captured["query"] = query
        return {
            "value": 88.1,
            "unit": "kcal/100g",
            "as_of": "2026-07-03T12:00",
            "source": "Open Food Facts",
            "stale": False,
            "error": None,
        }

    monkeypatch.setattr("src.routes.live.live_data.fetch", fake)
    resp = client.get("/api/live/nutrition", params={"food": "banana"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["value"] == 88.1
    assert body["unit"] == "kcal/100g"
    assert body["source"] == "Open Food Facts"
    assert captured["provider"] == "nutrition"
    assert captured["query"] == {"food": "banana"}


def test_live_route_nutrition_missing_food_422(client):
    resp = client.get("/api/live/nutrition")
    assert resp.status_code == 422, resp.text


def test_live_route_owner_gated_401_when_anon_off(client, monkeypatch):
    monkeypatch.setenv("TRUS_ALLOW_ANON", "0")
    resp = client.get("/api/live/weather", params={"lat": 1, "lon": 2})
    assert resp.status_code == 401, resp.text


def test_live_cache_is_owner_free_two_owners_share_one_fetch(monkeypatch):
    """R-903 safety half: the live cache is public/owner-free by construction, so
    two DIFFERENT owners requesting the SAME provider+query share ONE cache row
    (one upstream fetch serves both) and the stored row carries NO owner data.

    Two separate TestClients = two separate anonymous sessions = two owners. We
    mock the network boundary (urlopen) so the REAL `live_data.fetch` runs and
    actually populates `live_cache`; a shared row means the second owner's
    request performs no second upstream fetch."""
    upstream_calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        upstream_calls["n"] += 1
        return _FakeResp(_forecast_payload())

    monkeypatch.setattr(live_data.urllib.request, "urlopen", fake_urlopen)

    params = {"lat": 48.85, "lon": 2.35}
    with TestClient(app) as owner_a, TestClient(app) as owner_b:
        r_a = owner_a.get("/api/live/weather", params=params)
        r_b = owner_b.get("/api/live/weather", params=params)

    assert r_a.status_code == 200, r_a.text
    assert r_b.status_code == 200, r_b.text
    assert r_a.json()["value"] == r_b.json()["value"] == 21.5
    # The crux: owner B was served from the row owner A populated — one fetch, not
    # two. If the cache were owner-scoped, B would have missed and refetched.
    assert upstream_calls["n"] == 1

    # And the shared row carries no owner-identifying data: the live_cache table
    # has no owner column at all (structurally impossible to owner-scope), and
    # the cached payload has only the public data fields.
    with db._conn() as c:
        cols = {row["name"] for row in c.execute("PRAGMA table_info(live_cache)").fetchall()}
    assert cols == {"provider", "query_hash", "payload_json", "fetched_at"}
    assert not any("owner" in col or "session" in col or "uid" in col for col in cols)

    qhash = live_data._query_hash({"lat": 48.85, "lon": 2.35})
    cached = db.live_cache_get("weather", qhash)
    assert cached is not None
    assert set(cached["payload"].keys()) == {"value", "unit", "as_of", "source", "stale", "error"}


def test_live_route_rate_limited_429(client, monkeypatch):
    _mock_fetch_ok(monkeypatch)
    for _ in range(60):
        resp = client.get("/api/live/weather", params={"lat": 1, "lon": 2})
        assert resp.status_code == 200, resp.text
    resp = client.get("/api/live/weather", params={"lat": 1, "lon": 2})
    assert resp.status_code == 429, resp.text


# ---------------------------------------------------------------------------
# live_cache eviction (R-701 hardening): the public cache is bounded
# ---------------------------------------------------------------------------


def _seed_cache_rows(n: int) -> None:
    """Insert n distinct rows with strictly increasing fetched_at (hash-00000
    oldest … hash-{n-1} newest)."""
    base = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for i in range(n):
        db.live_cache_set(
            "weather",
            f"hash-{i:05d}",
            json.dumps({"value": i}),
            (base + timedelta(seconds=i)).isoformat(),
        )


def _cache_row_count() -> int:
    with db._conn() as c:
        return int(c.execute("SELECT COUNT(*) FROM live_cache").fetchone()[0])


def test_live_cache_set_evicts_oldest_over_cap(monkeypatch):
    """Inserting cap+K distinct rows leaves exactly cap: the K oldest (by
    fetched_at) are pruned on write, the newest survive."""
    monkeypatch.setenv("TRUS_LIVE_CACHE_MAX", "10")
    _seed_cache_rows(13)

    assert _cache_row_count() == 10
    # The 3 oldest are gone…
    for i in range(3):
        assert db.live_cache_get("weather", f"hash-{i:05d}") is None
    # …and everything newer survived, newest included.
    assert db.live_cache_get("weather", "hash-00003") is not None
    assert db.live_cache_get("weather", "hash-00012") is not None


def test_live_cache_upsert_same_key_does_not_evict(monkeypatch):
    """Refreshing an existing provider+query row (the common case) doesn't grow
    the table, so it never triggers eviction of an innocent row."""
    monkeypatch.setenv("TRUS_LIVE_CACHE_MAX", "3")
    _seed_cache_rows(3)
    now = datetime.now(timezone.utc).isoformat()
    db.live_cache_set("weather", "hash-00001", json.dumps({"value": 99}), now)

    assert _cache_row_count() == 3
    refreshed = db.live_cache_get("weather", "hash-00001")
    assert refreshed is not None
    assert refreshed["payload"]["value"] == 99


def test_live_cache_cap_defaults_to_5000_and_survives_bad_env(monkeypatch):
    assert db._live_cache_max() == 5000
    monkeypatch.setenv("TRUS_LIVE_CACHE_MAX", "not-a-number")
    assert db._live_cache_max() == 5000
    monkeypatch.setenv("TRUS_LIVE_CACHE_MAX", "0")
    assert db._live_cache_max() == 5000
    monkeypatch.setenv("TRUS_LIVE_CACHE_MAX", "250")
    assert db._live_cache_max() == 250
