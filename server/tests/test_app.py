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
    assert len(director_clients) >= 200  # ≥200 клиентов (данные хакатона)
    assert client.get("/api/audit").status_code == 200

    client.cookies.clear()
    login("manager@magi.by")  # оператор
    operator_clients = client.get("/api/clients").json()["items"]
    assert 0 < len(operator_clients) < len(director_clients)
    assert client.get("/api/audit").status_code == 403

    client.cookies.clear()
    login("head.production@magi.by")  # руководитель производства
    # УП-05: руководитель не видит закрытые показатели другого подразделения
    assert client.get("/api/finance").status_code == 403
    assert client.get("/api/production").status_code == 200
    assert client.get("/api/conversations").json()["items"] == []

    client.cookies.clear()
    login("analyst@magi.by")  # аналитик: чтение всей компании
    assert client.get("/api/pulse").status_code == 200
    assert client.get("/api/analyst").status_code == 200


def test_pulse_kpis_registry_and_drilldown():
    login("director@magi.by")
    pulse = client.get("/api/pulse").json()
    # УП-02: не менее 10 KPI с формулой, источником и статусом
    assert len(pulse["kpis"]) >= 10
    for kpi in pulse["kpis"]:
        assert kpi["formula"] and kpi["source"] and kpi["unit"]
        assert kpi["status"] in ("green", "amber", "red", "neutral")
    assert len(pulse["weeks"]) == 6  # прогноз мощности на 6 недель
    assert pulse["load_risk_week"] is not None  # неделя перегрузки найдена
    # детализация причины просрочки (УП-03)
    prod = client.get("/api/production").json()
    assert len(prod["causes"]) == 3
    top_cause = prod["causes"][0]
    detail = client.get(f"/api/production/causes/{top_cause['cause']}/orders").json()
    assert len(detail["items"]) > 0
    assert "client_name" in detail["items"][0] and "owner_name" in detail["items"][0]


def test_decisions_flow_and_audit():
    login("head.finance@magi.by")
    created = client.post("/api/decisions", json={
        "kpi_key": "cash_exec",
        "problem": "Исполнение БДДС ниже плана",
        "impact": "Кассовый разрыв в Н2",
        "cause": "Задержка оплат B2B",
        "action": "Договориться о переносе платежа и ускорить инкассацию",
        "owner_id": 5,
        "priority": "high",
    })
    assert created.status_code == 200, created.text
    decision_id = created.json()["id"]
    patched = client.patch(f"/api/decisions/{decision_id}", json={"status": "in_progress"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "in_progress"
    items = client.get("/api/decisions").json()["items"]
    assert any(d["id"] == decision_id for d in items)

    client.cookies.clear()
    login("director@magi.by")
    audit_items = client.get("/api/audit").json()["items"]
    actions = [row["action"] for row in audit_items]
    assert "decision.create" in actions and "decision.update" in actions  # УП-04


def test_operator_cannot_create_decision():
    login("manager@magi.by")
    assert client.post("/api/decisions", json={
        "problem": "Проблема тест", "action": "Действие тест",
    }).status_code == 403


def test_magi_answers_with_client_context_and_hands_off_complaint():
    login("manager@magi.by")
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
    assert detail["conversation"]["summary"]  # AI-сводка для менеджера
    assert "Тема" in detail["conversation"]["summary"]
    assert detail["messages"][-1]["author"] == "magi"


def test_handoff_generates_summary_without_pii_leak():
    login("manager@magi.by")
    conversations = client.get("/api/conversations").json()["items"]
    hero = next(c for c in conversations if c["client_name"] == "Мария Ковалёва")
    response = client.post(f"/api/conversations/{hero['id']}/handoff", json={"reason": "Нужен разбор брака"})
    assert response.status_code == 200
    summary = response.json()["summary"]
    assert "Мария Ковалёва" in summary  # сводка для сотрудника — ПДн не маскируются внутри CRM


def test_templates_and_pickups():
    login("manager@magi.by")
    templates = client.get("/api/templates").json()["items"]
    assert len(templates) >= 8

    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at) "
            "VALUES ('ПВЗ Тест', '+375 29 999-99-99', 'pvz@example.by', 'Минск', 'site', 'test', 'customer', 0, 1, 3, 'Клиентский сервис', '', '', ?)",
            ("2026-01-01T00:00:00Z",),
        )
        client_id = conn.execute("SELECT id FROM clients WHERE name = 'ПВЗ Тест'").fetchone()[0]
        order_id = conn.execute(
            "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at) "
            "VALUES (?, 'Фотокнига Classic', 290, 145, 'site', 'online', 'ready', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z')",
            (client_id,),
        ).lastrowid
        conv_id = conn.execute(
            "INSERT INTO conversations (client_id, channel, subject, topic, status, mode, assignee_id, team, magi_enabled, last_message_at, created_at) "
            "VALUES (?, 'site', 'ПВЗ', 'pickup', 'open', 'magi', 3, 'Клиентский сервис', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (client_id,),
        ).lastrowid
        conn.execute("INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, 'lead', 'Здравствуйте!', '2026-01-01T00:00:00Z')", (conv_id,))
        pickup_id = conn.execute(
            "INSERT INTO pickups (order_id, location, ready_at, expires_at) VALUES (?, 'Минск, Тимирязева 65Б', '2026-01-02T00:00:00Z', '2026-01-07T00:00:00Z')",
            (order_id,),
        ).lastrowid

    response = client.post(f"/api/pickups/{pickup_id}/remind")
    assert response.status_code == 200, response.text
    assert "Тимирязева" in response.json()["message"]


def test_rules_constructor_changes_magi_live():
    login("head.crm@magi.by")
    rules = client.get("/api/rules").json()["items"]
    assert len(rules) >= 5

    # контрольное сообщение темы «документы»: попадает в финальную проверку порога
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at) "
            "VALUES ('Контроль Правил', '+375 29 888-88-88', 'rules@example.by', 'Минск', 'site', 'test', 'customer', 0, 1, 3, 'Клиентский сервис', '', '', '2026-01-01T00:00:00Z')"
        )
        rc = conn.execute("SELECT id FROM clients WHERE name = 'Контроль Правил'").fetchone()[0]
        rconv = conn.execute(
            "INSERT INTO conversations (client_id, channel, subject, topic, status, mode, assignee_id, team, magi_enabled, last_message_at, created_at) "
            "VALUES (?, 'site', 'Счёт', 'docs', 'open', 'magi', 3, 'Клиентский сервис', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (rc,),
        ).lastrowid
        conn.execute(
            "INSERT INTO messages (conversation_id, author, body, created_at) VALUES (?, 'lead', 'Выставите, пожалуйста, счёт на компанию.', '2026-01-01T00:00:00Z')",
            (rconv,),
        )

    # 1. Тест правил на потоке: высокий порог → меньше автоответов, низкий → больше
    current = client.get("/api/rules").json()["items"]
    current_threshold = next(r for r in current if r["key"] == "threshold.confidence")["config"]
    result = client.post("/api/rules/test", json={"key": "threshold.confidence", "config": {"value": 0.2}})
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["total"] >= 100
    high = client.post("/api/rules/test", json={"key": "threshold.confidence", "config": {"value": 0.95}}).json()
    assert data["new"]["auto"] > high["new"]["auto"]
    assert data["new"]["auto"] - high["new"]["auto"] >= 1  # контрольное сообщение меняет исход

    # 2. Правка порога меняет поведение Magi без перезапуска
    created = client.post(
        "/api/leads",
        json={"name": "Порог Лид", "phone": "+375 29 777-77-77", "channel": "site",
              "message": "Здравствуйте! Хочу заказать фотокнигу."},
    )
    assert created.status_code == 200, created.text
    conv_id = created.json()["conversation_id"]
    patched = client.patch("/api/rules/threshold.confidence", json={"config": {"value": 0.97}})
    assert patched.status_code == 200
    response = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"author": "lead", "body": "Сколько стоит календарь настенный?"},
    )
    magi = response.json()["magi_message"]
    assert magi is not None
    conv = client.get(f"/api/conversations/{conv_id}").json()["conversation"]
    # уверенность ответа базы знаний (~0.7) ниже порога 0.97 → передача человеку
    assert conv["mode"] == "human" and conv["handoff_reason"]
    # вернуть порог обратно
    client.patch("/api/rules/threshold.confidence", json={"config": current_threshold})

    client.cookies.clear()
    login("manager@magi.by")
    assert client.patch("/api/rules/threshold.confidence", json={"config": {"value": 0.3}}).status_code == 403


def test_agent_settings_and_pii_mask():
    login("manager@magi.by")
    assert client.patch("/api/agent", json={"confidence_threshold": 0.7}).status_code == 403

    client.cookies.clear()
    login("director@magi.by")
    agent = client.get("/api/agent").json()
    example = agent["pii_mask_example"]
    assert "145-22-08" not in example["phone"] and "***" in example["phone"]
    assert "kovaleva" not in example["email"] and "@example.by" not in example["email"]
    assert not example["name"].startswith("Мария")
