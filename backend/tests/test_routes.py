from unittest.mock import patch
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_generate_returns_text():
    with patch("src.routes.generate.llm.generate", return_value="hello"):
        resp = client.post("/api/generate", json={"prompt": "say hi"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "hello"


def test_generate_empty_prompt_rejected():
    resp = client.post("/api/generate", json={"prompt": "   "})
    assert resp.status_code == 422


def test_generate_with_system_prompt():
    with patch("src.routes.generate.llm.generate", return_value="ok") as mock:
        resp = client.post("/api/generate", json={"prompt": "hi", "system": "be brief"})
    assert resp.status_code == 200
    mock.assert_called_once_with("hi", "be brief")
