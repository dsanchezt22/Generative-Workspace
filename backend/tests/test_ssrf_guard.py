"""Stage-1 final review security decision B: image_url SSRF guard."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client(monkeypatch):
    # Force offline stub mode so no test hits a live LLM endpoint.
    monkeypatch.setenv("TRUS_LLM_PROVIDER", "stub")
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/api/health",
        "http://localhost:11434/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/internal",
        "http://192.168.1.1/router",
    ],
)
def test_private_and_metadata_urls_are_refused(tmp_path, monkeypatch, url):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = client.post("/api/studio/use-cases/calorie/import", data={"image_url": url})
        assert r.status_code == 422
        assert "url" in str(r.json().get("detail", "")).lower()


def test_ipv6_loopback_url_is_refused(client):
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "http://[::1]:8000/img.png"},
    )
    assert r.status_code == 422
    assert "url" in str(r.json().get("detail", "")).lower()


def test_url_import_disabled_in_prod_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("TRUS_ENV", "prod")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.delenv("TRUS_ALLOW_URL_IMPORT", raising=False)
    # NOTE: main.py's prod boot-guard runs at import; the app is already imported
    # in dev shape. Test the guard FUNCTION directly instead of re-importing app:
    from src.routes import studio as studio_routes

    with pytest.raises(HTTPException):
        studio_routes._check_url_allowed("https://example.com/img.png")


def test_url_import_enabled_in_prod_with_flag(monkeypatch):
    monkeypatch.setenv("TRUS_ENV", "prod")
    monkeypatch.setenv("TRUS_ALLOW_URL_IMPORT", "1")
    from src.routes import studio as studio_routes

    # A public host, prod-disabled gate lifted by the flag: must not raise.
    studio_routes._check_url_allowed("https://example.com/img.png")


def test_dns_resolution_failure_is_a_clean_422(client):
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "https://this-host-does-not-exist.invalid/img.png"},
    )
    assert r.status_code == 422
    assert "url" in str(r.json().get("detail", "")).lower()


def test_redirect_to_metadata_address_is_refused(client, monkeypatch):
    """Classic SSRF bypass: the initial host is public and passes the pre-fetch
    check, but the server responds with a redirect that lands on a link-local
    metadata address. urlopen follows the redirect itself (stdlib behavior), so
    the guard must re-check the FINAL resp.url before the response is trusted."""
    import urllib.request

    class _FakeHeaders:
        def get(self, key, default=None):
            return "image/png" if key == "Content-Type" else default

    class _FakeRedirectedResp:
        headers = _FakeHeaders()
        url = "http://169.254.169.254/latest/meta-data/"

        def read(self, n=-1):
            return b"fake-image-bytes"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeRedirectedResp())
    r = client.post(
        "/api/studio/use-cases/calorie/import",
        data={"image_url": "https://example.com/redirects-to-metadata.png"},
    )
    assert r.status_code == 422
    assert "url" in str(r.json().get("detail", "")).lower()
