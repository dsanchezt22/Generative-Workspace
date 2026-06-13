import os
import tempfile

import pytest


@pytest.fixture(autouse=True)
def _isolate_db(monkeypatch):
    """Each test gets a fresh SQLite file so state never leaks across tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("TRUS_DB_PATH", path)
    yield
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
