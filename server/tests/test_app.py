import os
import tempfile
from pathlib import Path

import pytest

os.environ["MAGI_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["MAGI_SECRET"] = "test-secret"
os.environ["MAGI_PASSWORD"] = "demo"
os.environ.pop("MAGI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from server import db  # noqa: E402

db.reset_db()

from server.app import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_session():
    client.cookies.clear()
    yield
    client.cookies.clear()


def login(email: str):
    response = client.post("/api/auth/login", json={"email": email, "password": "demo"})
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_login():
    assert client.get("/api/health").json()["status"] == "ok"
    user = login("director@magi.by")
    assert user["role"] == "director"
    assert client.get("/api/auth/me").json()["email"] == "director@magi.by"


def test_role_scoping_and_audit():
    login("director@magi.by")
    director_clients = client.get("/api/clients").json()["items"]
    assert len(director_clients) >= 50
    assert client.get("/api/audit").status_code == 200

    client.cookies.clear()
    login("operator@magi.by")
    operator_clients = client.get("/api/clients").json()["items"]
    assert 0 < len(operator_clients) < len(director_clients)
    assert client.get("/api/audit").status_code == 403


def test_magi_answers_with_client_context_and_hands_off_complaint():
    login("operator@magi.by")
    conversations = client.get("/api/conversations").json()["items"]
    hero = next(c for c in conversations if c["client_name"] == "Мария Ковалёва")

    response = client.post(
        f"/api/conversations/{hero['id']}/messages",
        json={"author": "lead", "body": "Здравствуйте! Успеет ли фотокнига к 14 ноября?"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    magi = payload["magi_message"]
    assert magi is not None
    assert magi["author"] == "magi"
    assert magi["intent"] == "order_status"
    assert magi["confidence"] >= 0.55

    created = client.post(
        "/api/leads",
        json={
            "name": "Тестовый Лид",
            "phone": "+375 29 000-00-00",
            "channel": "site",
            "message": "В заказе брак, фотокнига порвана. Хочу вернуть деньги!",
        },
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["conversation_id"]
    detail = client.get(f"/api/conversations/{conversation_id}").json()
    assert detail["conversation"]["mode"] == "human"
    assert detail["conversation"]["handoff_reason"]
    assert detail["messages"][-1]["author"] == "magi"


def test_agent_settings_are_director_only():
    login("operator@magi.by")
    assert client.patch("/api/agent", json={"confidence_threshold": 0.7}).status_code == 403

    client.cookies.clear()
    login("director@magi.by")
    response = client.patch("/api/agent", json={"confidence_threshold": 0.7})
    assert response.status_code == 200
    assert client.get("/api/agent").json()["settings"]["confidence_threshold"] == 0.7
    assert any(row["action"] == "agent.settings" for row in client.get("/api/audit").json()["items"])
