"""Stage-1 final review security decision A: cross-site multipart CSRF gate."""

from fastapi.testclient import TestClient
from src.main import app


def _post_file(client, origin=None):
    headers = {"Origin": origin} if origin else {}
    return client.post(
        "/api/modules/generate_from_file",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"prompt": "track this"},
        headers=headers,
    )


def test_foreign_origin_multipart_is_403(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        r = _post_file(client, origin="https://evil.example")
        assert r.status_code == 403


def test_allowed_origin_and_no_origin_pass_the_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        # Allowed origin (default list): not 403 (may be 4xx/2xx further down — stub mode refuses honestly)
        r = _post_file(client, origin="http://localhost:3000")
        assert r.status_code != 403
        r2 = _post_file(client)  # no Origin header (curl / same-origin)
        assert r2.status_code != 403


def test_studio_import_and_capture_are_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("TRUS_DB_PATH", str(tmp_path / "t.db"))
    with TestClient(app) as client:
        for path in (
            "/api/studio/use-cases/calorie/import",
            "/api/studio/use-cases/calorie/capture",
        ):
            r = client.post(
                path,
                files={"file": ("s.png", b"png", "image/png")},
                headers={"Origin": "https://evil.example"},
            )
            assert r.status_code == 403, path
