import os
import tempfile
from pathlib import Path

import pytest

os.environ["MAGI_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["MAGI_SECRET"] = "test-secret"
os.environ["MAGI_PASSWORD"] = "demo"

from fastapi.testclient import TestClient  # noqa: E402

from server import db  # noqa: E402  (тут подтягивается .env)

# Тесты всегда офлайн: внешние/локальные LLM-вызовы запрещены.
os.environ.pop("MAGI_API_KEY", None)
os.environ.pop("MAGI_BASE_URL", None)

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


# ------------------------------------------------------------------ Telegram/промпты/миграция

def test_dynamic_prompts_cover_all_topics_and_minimal_context():
    from server.prompts import TASK_PROMPTS, build_context
    from server.db import TOPICS

    topic_keys = {t[0] for t in TOPICS}
    assert topic_keys <= set(TASK_PROMPTS.keys()) | {"price_book"} or topic_keys <= set(TASK_PROMPTS.keys())

    client = {"name": "Мария К.", "phone": "+375 XX ***-**-**", "email": "***@***",
              "city": "Минск", "tags": "VIP", "notes": "день рождения сына"}
    orders = [{"product": "Фотокнига Premium", "status": "in_production", "promised_at": "2026-11-13T10:00:00Z", "amount": 620}]
    ctx = build_context("order_status", client, orders, [])
    assert "последний_заказ" in ctx and ctx["последний_заказ"]["product"] == "Фотокнига Premium"
    assert "email" not in str(ctx["последний_заказ"]) and "phone" not in str(ctx)

    ctx = build_context("greeting", client, orders, [])
    assert ctx["заметки"] == "день рождения сына"


def test_telegram_ingest_creates_client_and_conversation():
    import asyncio

    from server.telegram_bot import ingest_telegram_message

    reply = asyncio.run(ingest_telegram_message("999888", "Тест Бот", "testbot", "Сколько стоит фотокнига Premium?"))
    assert reply and ("620" in reply or "Premium" in reply)
    with db.get_db() as conn:
        client = conn.execute("SELECT * FROM clients WHERE tg_handle = '999888'").fetchone()
        assert client is not None and client["channel"] == "telegram"
        conv = conn.execute(
            "SELECT * FROM conversations WHERE client_id = ? AND channel = 'telegram'", (client["id"],)
        ).fetchone()
        assert conv is not None and conv["status"] != "closed"
        conv_id = conv["id"]

    # второе сообщение — тот же диалог, без дублей
    asyncio.run(ingest_telegram_message("999888", "Тест Бот", "testbot", "А доставка в Гомель сколько идёт?"))
    with db.get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE client_id = ? AND channel = 'telegram' AND status != 'closed'",
            (client["id"],),
        ).fetchone()[0]
        assert count == 1
        authors = [r["author"] for r in conn.execute(
            "SELECT author FROM messages WHERE conversation_id = ? ORDER BY id", (conv_id,)
        ).fetchall()]
        assert authors.count("lead") == 2 and authors.count("magi") == 2


def test_telegram_complaint_hands_off_and_manager_reply_goes_to_outbox():
    import asyncio

    from server.telegram_bot import ingest_telegram_message

    asyncio.run(ingest_telegram_message("777666", "Бот Жалобщик", None, "У вас брак, страница порвана, вернуть деньги!"))
    with db.get_db() as conn:
        tg_client = conn.execute("SELECT * FROM clients WHERE tg_handle = '777666'").fetchone()
        conv = conn.execute(
            "SELECT * FROM conversations WHERE client_id = ? ORDER BY id DESC LIMIT 1", (tg_client["id"],)
        ).fetchone()
        assert conv["mode"] == "human" and conv["handoff_reason"] and conv["summary"]
        conv_id = conv["id"]

    login("manager@magi.by")
    response = client.post(f"/api/conversations/{conv_id}/messages",
                           json={"author": "agent", "body": "Здравствуйте! Разобрались, перепечатаем бесплатно."})
    assert response.status_code == 200
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM tg_outbox WHERE conversation_id = ? ORDER BY id DESC LIMIT 1", (conv_id,)
        ).fetchone()
        assert row is not None and row["sent_at"] is None and "перепечатаем" in row["body"]


def test_import_preview_and_apply_dedup():
    login("director@magi.by")
    csv_content = (
        "Имя;Телефон;E-mail;Город;Источник;Комментарий\n"
        "Импорт Иванов;+375 29 555-00-11;import1@example.by;Минск;bitrix24;из Битрикс24\n"
        "Импорт Петров;+375 29 555-00-12;import2@example.by;Гомель;bitrix24;\n"
        "Мария Ковалёва;+375 29 145-22-08;maria.kovaleva@example.by;Минск;bitrix24;уже есть в CRM\n"
    ).encode("utf-8")
    preview = client.post("/api/import/preview",
                          files={"file": ("bitrix24.csv", csv_content, "text/csv")}).json()
    assert preview["will_create"] == 2 and preview["will_merge"] == 1
    assert "имя" in " ".join(preview["mapped_columns"].keys()).lower() or preview["mapped_columns"]

    result = client.post("/api/import/apply", files={"file": ("bitrix24.csv", csv_content, "text/csv")}).json()
    assert result["created"] == 2 and result["merged"] == 1

    # повторный импорт — всё объединяется, дублей нет
    again = client.post("/api/import/apply", files={"file": ("bitrix24.csv", csv_content, "text/csv")}).json()
    assert again["created"] == 0 and again["merged"] == 3
    with db.get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM clients WHERE phone LIKE '%555-00-1%'").fetchone()[0]
        assert count == 2
        assert conn.execute("SELECT source FROM clients WHERE phone LIKE '%555-00-11'").fetchone()[0].startswith("import:")

    client.cookies.clear()
    login("manager@magi.by")
    assert client.post("/api/import/preview", files={"file": ("x.csv", csv_content, "text/csv")}).status_code == 403


def test_learning_loop_grows_kb_and_rules():
    login("director@magi.by")
    data = client.get("/api/agent/learning").json()
    assert "acceptance" in data and len(data["acceptance"]) >= 10
    assert "rule_suggestions" in data and "kb_suggestions" in data

    # кандидат на статью базы знаний — из реальных ответов менеджеров
    if data["kb_suggestions"]:
        target = data["kb_suggestions"][0]
        applied = client.post("/api/agent/learning/apply", json={"kind": "kb", "topic": target["topic"]}).json()
        assert applied["ok"] is True
        with db.get_db() as conn:
            kb_row = conn.execute("SELECT * FROM kb WHERE topic = ?", (target["topic"],)).fetchone()
            assert kb_row is not None

    if data["rule_suggestions"]:
        target = data["rule_suggestions"][0]
        applied = client.post("/api/agent/learning/apply",
                              json={"kind": "rule", "reason": target["reason"]}).json()
        assert applied["ok"] is True
        with db.get_db() as conn:
            rule = conn.execute("SELECT * FROM rules WHERE key = ?", (applied["rule"],)).fetchone()
            assert rule is not None and rule["kind"] == "trigger" and rule["enabled"] == 1

    audit_actions = [r["action"] for r in client.get("/api/audit").json()["items"]]
    assert "kb.grow" in audit_actions or "rules.create" in audit_actions


def test_lead_with_telegram_handle_and_client_patch():
    login("director@magi.by")
    created = client.post("/api/leads", json={
        "name": "Тг Лид", "phone": "", "channel": "telegram",
        "message": "Здравствуйте, хочу фотокнигу!", "tg_handle": "ivanov",
    })
    assert created.status_code == 200, created.text
    detail = client.get(f"/api/conversations/{created.json()['conversation_id']}").json()
    client_id = detail["client"]["id"]
    assert detail["client"]["tg_handle"] == "@ivanov"  # нормализовали в @name

    patched = client.patch(
        f"/api/clients/{client_id}",
        json={"phone": "+375 29 111-22-33", "tg_handle": "1287875313"},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["phone"] == "+375 29 111-22-33"
    assert patched.json()["tg_handle"] == "1287875313"

    client.cookies.clear()
    login("analyst@magi.by")
    assert client.patch(f"/api/clients/{client_id}", json={"phone": "x"}).status_code == 403


def test_capture_name_from_dialog():
    login("director@magi.by")
    created = client.post("/api/leads", json={
        "name": "Клиент Telegram", "phone": "", "channel": "telegram",
        "message": "Привет! Меня зовут Артём Сулима.", "tg_handle": "@artem",
    })
    conv_id = created.json()["conversation_id"]
    detail = client.get(f"/api/conversations/{conv_id}").json()
    assert detail["client"]["name"] == "Артём Сулима"  # имя захвачено из первого сообщения

    response = client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"author": "lead", "body": "Меня зовут Пётр Иванов"},
    )
    assert response.status_code == 200
    detail = client.get(f"/api/conversations/{conv_id}").json()
    assert detail["client"]["name"] == "Артём Сулима"  # имя уже известно — не перезаписываем


def test_rescue_run_sends_and_does_not_repeat():
    login("director@magi.by")
    with db.get_db() as conn:
        cid = conn.execute(
            "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, tg_handle, created_at) "
            "VALUES ('Rescue Клиент', '', '', '', 'telegram', 'telegram', 'customer', 0, 1, 3, 'Клиентский сервис', '', '', '7700000099', '2026-01-01T00:00:00Z')"
        ).lastrowid
        oid = conn.execute(
            "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, promised_at, defect) "
            "VALUES (?, 'Фотокнига Rescue', 50, 20, 'telegram', 'online', 'in_production', '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z', 0)",
            (cid,),
        ).lastrowid
        cvid = conn.execute(
            "INSERT INTO conversations (client_id, channel, subject, topic, status, mode, assignee_id, team, magi_enabled, last_message_at, created_at) "
            "VALUES (?, 'telegram', 'Rescue', 'order_status', 'open', 'magi', 3, 'Клиентский сервис', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (cid,),
        ).lastrowid

    result = client.post("/api/rescue/run")
    assert result.status_code == 200, result.text
    assert result.json()["sent"] >= 1

    messages = client.get(f"/api/conversations/{cvid}").json()["messages"]
    rescue_messages = [m for m in messages if m["intent"] == "rescue"]
    assert len(rescue_messages) == 1
    assert "Фотокнига Rescue" in rescue_messages[0]["body"]

    # повторный скан не шлёт второе сообщение по тому же заказу
    result2 = client.post("/api/rescue/run").json()
    assert result2["sent"] == 0
    messages = client.get(f"/api/conversations/{cvid}").json()["messages"]
    assert len([m for m in messages if m["intent"] == "rescue"]) == 1


def test_order_actions_rush_promo_extend_redone():
    login("director@magi.by")
    with db.get_db() as conn:
        cid = conn.execute(
            "INSERT INTO clients (name, phone, email, city, channel, source, status, ltv, consent, owner_id, team, tags, notes, created_at) "
            "VALUES ('Action Клиент', '', '', '', 'site', 'magi', 'customer', 0, 1, 3, 'Клиентский сервис', '', '', '2026-01-01T00:00:00Z')"
        ).lastrowid
        oid = conn.execute(
            "INSERT INTO orders (client_id, product, amount, cost, channel, payment, status, created_at, defect) "
            "VALUES (?, 'Фотокнига Act', 50, 20, 'site', 'online', 'in_production', '2026-01-01T00:00:00Z', 0)",
            (cid,),
        ).lastrowid
        conn.execute(
            "INSERT INTO pickups (order_id, location, ready_at, expires_at) VALUES (?, 'ПВЗ Минск', '2026-01-02T00:00:00Z', '2026-01-05T00:00:00Z')",
            (oid,),
        )

    rush = client.post(f"/api/orders/{oid}/action", json={"action": "rush"})
    assert rush.status_code == 200, rush.text
    with db.get_db() as conn:
        job = conn.execute("SELECT * FROM machine_jobs WHERE order_id = ?", (oid,)).fetchone()
        assert job is not None

    promo = client.post(f"/api/orders/{oid}/action", json={"action": "promo"})
    assert promo.status_code == 200 and "MAGI10" in promo.json()["message"]
    detail = client.get(f"/api/clients/{cid}").json()
    assert "MAGI10" in detail["client"]["notes"]

    extend = client.post(f"/api/orders/{oid}/action", json={"action": "extend"})
    assert extend.status_code == 200 and "продлено" in extend.json()["message"]

    redone = client.post(f"/api/orders/{oid}/action", json={"action": "redone"})
    assert redone.status_code == 200
    detail = client.get(f"/api/clients/{cid}").json()
    assert any("(повтор печати)" in o["product"] for o in detail["orders"])


def test_telegram_matches_lead_created_by_handle():
    """Лид из CRM по @name: сообщение от этого пользователя бэкфиллит числовой ID."""
    import asyncio

    from server.telegram_bot import ingest_telegram_message

    login("director@magi.by")
    created = client.post("/api/leads", json={
        "name": "Матч Лид", "channel": "telegram", "message": "Привет!", "tg_handle": "@match_user",
    })
    conv_id = created.json()["conversation_id"]

    reply = asyncio.run(ingest_telegram_message("555000", "Матч Лид", "match_user", "Когда будет доставка?"))
    assert reply is not None
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM clients WHERE tg_handle = '555000'").fetchone()
        assert row is not None and row["name"] == "Матч Лид"  # тот же клиент, ID бэкфиллен
        detail = client.get(f"/api/conversations/{conv_id}").json()
        bodies = [m["body"] for m in detail["messages"]]
        assert "Когда будет доставка?" in bodies  # сообщение попало в тот же диалог


def test_offline_confidence_on_skenls_phrases():
    """Фразы из реального диалога, где Magi «плыл» (conf 0.32) — теперь уверенные ответы."""
    from server.magi import local_reply, rules_map_from_db

    login("director@magi.by")
    with db.get_db() as conn:
        client = dict(conn.execute("SELECT * FROM clients WHERE name = 'Мария Ковалёва'").fetchone())
        orders = [dict(r) for r in conn.execute(
            "SELECT * FROM orders WHERE client_id = ? ORDER BY created_at DESC", (client["id"],)
        )]
        kb = [dict(r) for r in conn.execute("SELECT * FROM kb ORDER BY id")]
        rules = rules_map_from_db(conn.execute("SELECT * FROM rules WHERE enabled = 1"))

    confident = [
        ("каково состояние моего последнего заказа", 0.8),
        ("куда доставите заказ", 0.7),
        ("пришли список моих заказов", 0.8),
        ("меня зовут даниил", 0.8),
        ("Сколько стоит холст 40×60?", 0.7),  # теперь отвечает прайсом холстов, не книг
    ]
    for text, min_conf in confident:
        result = local_reply(text, client, orders, kb, 0.55, rules, "telegram")
        assert result.confidence >= min_conf, (text, result.confidence, result.reply)
        assert not result.handoff, (text, result.reply)

    # чужой номер заказа → честная передача человеку, а не ответ про другой заказ
    result = local_reply("что с моим заказом #999?", client, orders, kb, 0.55, rules, "telegram")
    assert result.handoff and "999" in result.reply

    # представился и сразу спросил — вопрос не теряется
    result = local_reply("меня зовут Даниил, где мой заказ?", client, orders, kb, 0.55, rules, "telegram")
    assert result.intent == "order_status" and not result.handoff

    # имя с маленькой буквы тоже распознаётся
    from server.magi import extract_name
    assert extract_name("меня зовут даниил") == "Даниил"


def test_openai_two_step_prompt_selection(monkeypatch):
    """Шаг 1: LLM-классификатор выбирает задачу; шаг 2: система отдаёт промпт этой задачи."""
    import asyncio

    from server import magi

    calls = []

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": calls[-1]["content"]}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, headers=None, json=None):
            calls.append(dict(json))
            calls[-1]["content"] = (
                '{"topic": "delivery"}' if len(calls) == 1
                else '{"reply": "Доставляем за 1 день.", "confidence": 0.9, "handoff": false, "handoff_reason": null}'
            )
            return FakeResponse()

    monkeypatch.setattr(magi.httpx, "AsyncClient", FakeClient)
    monkeypatch.setenv("MAGI_API_KEY", "test-key")
    try:
        result = asyncio.run(magi.openai_reply("куда доставите заказ", {"name": "Тест"}, [], [], "telegram"))
    finally:
        monkeypatch.undo()

    assert result is not None, "openai_reply должен вернуть результат"
    assert result.topic == "delivery" and result.confidence == 0.9
    # шаг 1 — короткий классификационный вызов с промптом классификатора
    assert calls[0]["messages"][0]["content"] == magi.classifier_prompt()
    assert calls[0]["max_tokens"] == 24
    # шаг 2 — системный промпт именно выбранной задачи
    assert calls[1]["messages"][0]["content"] == magi.task_prompt("delivery")

    # без ключа модель недоступна → None, движок уходит в оффлайн-правила
    assert asyncio.run(magi.classify_topic("привет")) is None


def test_accounting_ledger_invariant_and_reports():
    """Ядро двойной записи: баланс сходится, ОСВ симметрична, P&L считается."""
    from server import accounting as acc

    login("director@magi.by")
    data = client.get("/api/accounting").json()
    assert data["balanced"] is True
    assert abs(data["osv_totals"]["assets"] - data["osv_totals"]["passives"]) < 0.01
    assert data["pnl"], "P&L пуст"
    assert any(m["revenue"] > 0 for m in data["pnl"])

    # ОСВ: Дт обороты = Кт обороты, все счета типовой цепочки задействованы
    osv = client.get("/api/accounting/osv", params={"from_date": "2000-01-01", "to_date": "2099-12-31"}).json()
    assert osv["balanced"] is True
    codes_debit = {r["code"] for r in osv["rows"] if r["debit"] > 0}
    codes_credit = {r["code"] for r in osv["rows"] if r["credit"] > 0}
    assert {"57", "51", "62", "90.2", "43", "20", "26"} <= codes_debit
    assert {"62", "90.1", "43", "20", "10", "60"} <= codes_credit

    # аномалий в сиде нет (cost < amount у всех заказов)
    assert client.get("/api/accounting").json()["anomalies"] == []


def test_accounting_storno_restores_balance():
    """Сторно: зеркальная проводка, исходная строка не удаляется, баланс сходится."""
    from server import accounting as acc

    login("director@magi.by")
    data = client.get("/api/accounting").json()
    target = next(t for t in data["transactions"] if t["doc_type"] == "order_delivered")

    response = client.post("/api/accounting/storno", json={"tx_id": target["id"], "reason": "Ошибка"})
    assert response.status_code == 200, response.text
    after = client.get("/api/accounting").json()
    assert after["balanced"] is True

    # повторное сторно запрещено
    assert client.post("/api/accounting/storno", json={"tx_id": target["id"], "reason": "ещё раз"}).status_code == 422

    # оператор не может сторнировать
    client.cookies.clear()
    login("manager@magi.by")
    assert client.post("/api/accounting/storno", json={"tx_id": target["id"], "reason": "x"}).status_code == 403


def test_bank_statement_import_and_reconcile():
    """Импорт выписки: парсер 1CClientBankExchange, дедуп, матчинг заказа, разнесение Дт 51 Кт 62."""
    statement = """1CClientBankExchange
ВерсияФормата=1.01
СекцияРасчСчет=BY17BLBB30150001000123456789
НачальныйОстаток=25000.00
СекцияДокумент=Платежное поручение
Номер=1184
Дата=10.11.2026
Сумма=350.00
Плательщик=Ковалева Мария
Получатель=ООО "Фотопринт", УНП 190000000
НазначениеПлатежа=Оплата заказа #21 фотокнига
КонецДокумента
СекцияДокумент=Платежное поручение
Номер=1185
Дата=10.11.2026
Сумма=120.00
Плательщик=Неизвестный платеж
Получатель=ООО "Фотопринт", УНП 190000000
НазначениеПлатежа=Оплата без номера заказа
КонецДокумента
"""
    login("director@magi.by")
    result = client.post("/api/accounting/import-statement", json={"text": statement}).json()
    assert result["duplicate"] is False
    assert result["matched"] == 1 and result["unmatched"] == 1

    # дедуп: повторный импорт той же выписки
    dup = client.post("/api/accounting/import-statement", json={"text": statement}).json()
    assert dup["duplicate"] is True

    # разнесение сопоставленной строки
    data = client.get("/api/accounting").json()
    matched = [l for l in data["bank_lines"] if l["status"] == "matched"]
    assert matched, "строка с заказом не нашлась"
    posted = client.post("/api/accounting/bank/post", json={"line_ids": [l["id"] for l in matched]}).json()
    assert posted["posted"] == 1
    # строка ушла из pending, в журнале появилась bank_payment
    data = client.get("/api/accounting").json()
    assert all(l["status"] != "matched" for l in data["bank_lines"])

    # оператор не импортирует выписки
    client.cookies.clear()
    login("manager@magi.by")
    assert client.post("/api/accounting/import-statement", json={"text": statement}).status_code == 403


def test_accounting_documents_and_reconciliation():
    """Первичка: счёт по заказу с НДС 20% + акт сверки по контрагенту."""
    from server import accounting as acc

    login("director@magi.by")
    order_ref = next(t["doc_id"] for t in client.get("/api/accounting").json()["transactions"]
                     if t["doc_id"] and t["doc_id"].startswith("order:"))
    order_pk = int(order_ref.split(":")[1])

    doc = client.post("/api/accounting/documents", json={"kind": "invoice", "order_id": order_pk}).json()
    assert doc["number"].startswith("SCH-"), doc

    printed = client.get(f"/api/accounting/documents/{doc['id']}/print")
    assert printed.status_code == 200 and "Фотопринт" in printed.text

    with db.get_db() as conn:
        cp = conn.execute("SELECT id FROM counterparties LIMIT 1").fetchone()[0]
    rec = client.get("/api/accounting/reconciliation", params={"counterparty_id": cp}).json()
    assert "name" in rec and "closing" in rec

    # аналитик читает, но не создаёт документы
    client.cookies.clear()
    login("analyst@magi.by")
    assert client.get("/api/accounting").status_code == 200
    assert client.post("/api/accounting/documents", json={"kind": "invoice", "order_id": order_pk}).status_code == 403
