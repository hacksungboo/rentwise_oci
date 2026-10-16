import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def client(tmp_path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/test.db"
    from rentwise.db import database
    database.reset_engine_for_tests(os.environ["DATABASE_URL"])
    from fastapi.testclient import TestClient
    from rentwise.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def admin(client):
    r = client.post("/api/v1/sessions", json={"username": "admin", "password": "rentwise2026"})
    assert r.status_code == 200, r.text
    return client
