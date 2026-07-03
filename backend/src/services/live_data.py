"""Live external-data framework (R-701/R-704): keyless server-side proxies for
components that show a real-world value (Metric/Kpi/Ring/Gauge/ProgressBar via
`data_source`). `fetch()` dispatches by provider and is cached server-side
(`live_cache` table) keyed by provider+query — NOT by owner, since weather is
public data (this bounds outbound fetches, it isn't per-user privacy).

Weather: Open-Meteo, keyless. `query` carries {lat, lon} (floats) or
{place: "City"} (geocoded first via Open-Meteo's geocoding API).

Zero-dep urllib, mirroring llm.py's `_openai_chat`/`transcribe` style: a
network/parse failure never raises past this module — `fetch()` always
returns a payload (fresh, stale-cached, or null-value-with-error), never an
exception the route would need to translate into a 500.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, cast

from src import db

_TIMEOUT = 10.0

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _query_hash(query: dict[str, Any]) -> str:
    """A stable cache key for a query dict — canonical (sorted-key) JSON, hashed
    so key length/shape never leaks into the DB row."""
    canon = json.dumps(query, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _empty_payload(source: str, error: str) -> dict[str, Any]:
    return {
        "value": None,
        "unit": None,
        "as_of": None,
        "source": source,
        "stale": False,
        "error": error,
    }


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    # url is always built from a fixed, hardcoded keyless host (Open-Meteo) plus
    # geocoded/numeric params — never raw end-user URL input.
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return cast(dict[str, Any], json.loads(resp.read().decode("utf-8")))


def _geocode(place: str) -> tuple[float, float] | None:
    url = f"{_GEOCODE_URL}?{urllib.parse.urlencode({'name': place, 'count': 1})}"
    payload = _get_json(url)
    results = payload.get("results") or []
    if not results:
        return None
    first = results[0]
    return float(first["latitude"]), float(first["longitude"])


def _fetch_weather(query: dict[str, Any]) -> dict[str, Any]:
    place = query.get("place")
    lat = query.get("lat")
    lon = query.get("lon")
    try:
        if place:
            geo = _geocode(str(place))
            if geo is None:
                return _empty_payload("Open-Meteo", f"Could not find a location named '{place}'.")
            lat, lon = geo
        elif lat is None or lon is None:
            return _empty_payload("Open-Meteo", "Weather needs lat & lon, or a place name.")

        params = {"latitude": lat, "longitude": lon, "current": "temperature_2m"}
        url = f"{_FORECAST_URL}?{urllib.parse.urlencode(params)}"
        payload = _get_json(url)
        current = payload.get("current") or {}
        value = current.get("temperature_2m")
        if value is None:
            return _empty_payload("Open-Meteo", "Open-Meteo returned no current temperature.")
        unit = (payload.get("current_units") or {}).get("temperature_2m", "°C")
        return {
            "value": float(value),
            "unit": unit,
            "as_of": current.get("time"),
            "source": "Open-Meteo",
            "stale": False,
            "error": None,
        }
    except (urllib.error.URLError, OSError) as e:
        return _empty_payload("Open-Meteo", f"Could not reach Open-Meteo: {e}")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        return _empty_payload("Open-Meteo", f"Open-Meteo returned an unusable response: {e}")


_FETCHERS = {"weather": _fetch_weather}

# The providers this module can actually dispatch. The schema's DataSource
# Literal also allows "nutrition" (Task 3 adds its fetcher here) — until then
# a request for it is honestly "unknown", same as any other out-of-domain name.
ALLOWED_PROVIDERS = frozenset(_FETCHERS)


def fetch(provider: str, query: dict[str, Any], refresh_secs: int = 600) -> dict[str, Any]:
    """Cached fetch: a hit within `refresh_secs` of the last successful fetch is
    returned without touching the network; a miss fetches fresh. A fetch error
    degrades to the last cached payload marked `stale=True`, or (if nothing was
    ever cached) a null-value payload with `error` set — never an exception."""
    fetcher = _FETCHERS.get(provider)
    if fetcher is None:
        return _empty_payload(provider, f"Unknown live-data provider: {provider}")

    qhash = _query_hash(query)
    cached = db.live_cache_get(provider, qhash)
    if cached is not None:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        age = (datetime.now(timezone.utc) - fetched_at).total_seconds()
        if age < refresh_secs:
            return dict(cached["payload"])

    fresh = fetcher(query)
    if fresh.get("error") is None:
        db.live_cache_set(provider, qhash, json.dumps(fresh), _now_iso())
        return fresh
    if cached is not None:
        stale_payload = dict(cached["payload"])
        stale_payload["stale"] = True
        return stale_payload
    return fresh
