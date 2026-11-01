from __future__ import annotations

import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="chore_helper_"))
os.environ["CHORE_HELPER_DATA"] = str(_tmp)
os.environ["CHORE_HELPER_PARENT_PASSWORD"] = "secret"
os.environ["CHORE_HELPER_PARENT_USER"] = "parent"

import pytest
from fastapi.testclient import TestClient

from server.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
    from sqlalchemy import delete

    from server import db as db_mod
    from server.models import Assignment, Child, ChildChore, LedgerEntry, Redemption

    session = db_mod.SessionLocal()
    if session is None:
        return
    try:
        session.execute(delete(LedgerEntry))
        session.execute(delete(Redemption))
        session.execute(delete(Assignment))
        session.execute(delete(ChildChore))
        session.execute(delete(Child))
        session.commit()
    finally:
        session.close()


@pytest.fixture()
def parent(client: TestClient):
    r = client.post("/api/parent/login", json={"username": "parent", "password": "secret"})
    assert r.status_code == 200, r.text
    return client
